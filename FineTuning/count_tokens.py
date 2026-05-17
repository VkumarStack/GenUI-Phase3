"""
Estimate training token count and cost for a Vertex AI SFT dataset.

Reads train.jsonl and substitutes GCS image URIs with local image bytes so the
Gemini countTokens API can measure the full token cost of each example (text +
images). Multiplies by epochs to give total billable training tokens.

Authentication: uses GOOGLE_API_KEY from the environment (same key used for
evaluation). No Vertex AI credentials required.

Usage:
    # Evaluator model dataset
    python FineTuning/count_tokens.py \\
        --dataset FineTuning/Evaluator/train.jsonl

    # Revision generator model dataset
    python FineTuning/count_tokens.py \\
        --dataset FineTuning/RevisionGenerator/train.jsonl

    # Full options
    python FineTuning/count_tokens.py \\
        --dataset FineTuning/Evaluator/train.jsonl \\
        --raw-dataset Datasets/RawDataset \\
        --model gemini-2.5-pro \\
        --epochs 3 \\
        --price-per-million 25.00
"""

import argparse
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).parent.parent / "Util" / ".env")

_ROOT = Path(__file__).parent.parent


def gcs_uri_to_local(uri: str, raw_dataset: Path) -> Path | None:
    """
    Map a GCS URI like gs://bucket/sft-assets/Participant_X_CaseStudy-Y.Z-MODEL/before.png
    to its local path under raw_dataset/Participant_X_CaseStudy-Y.Z-MODEL/Before/screenshot.png.
    """
    m = re.search(r"/([^/]+)/(before|after)\.png$", uri, re.IGNORECASE)
    if not m:
        return None
    folder_name, variant = m.group(1), m.group(2).lower()
    subdir = "Before" if variant == "before" else "After"
    return raw_dataset / folder_name / subdir / "screenshot.png"


def build_api_contents(record: dict, raw_dataset: Path) -> tuple[list, list]:
    """
    Convert a JSONL record into google-genai Content objects, replacing
    fileData GCS URIs with inline image bytes from local files.

    Returns (contents, warnings) where warnings is a list of any missing files.
    """
    contents = []
    warnings = []

    for turn in record["contents"]:
        parts = []
        for part in turn["parts"]:
            if "text" in part:
                parts.append(types.Part.from_text(text=part["text"]))
            elif "fileData" in part:
                uri = part["fileData"]["fileUri"]
                local_path = gcs_uri_to_local(uri, raw_dataset)
                if local_path and local_path.exists():
                    image_bytes = local_path.read_bytes()
                    parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/png"))
                else:
                    warnings.append(f"Missing local file for {uri}")
                    parts.append(types.Part.from_text(text=f"[image: {uri}]"))
        contents.append(types.Content(role=turn["role"], parts=parts))

    return contents, warnings


def main():
    parser = argparse.ArgumentParser(description="Count SFT training tokens and estimate cost.")
    parser.add_argument("--dataset",      required=True,
                        help="Path to train.jsonl (e.g. FineTuning/Evaluator/train.jsonl).")
    parser.add_argument("--raw-dataset",  default=str(_ROOT / "Datasets" / "RawDataset"),
                        help="Path to Datasets/RawDataset/ for local image resolution.")
    parser.add_argument("--model",        default="gemini-2.5-pro")
    parser.add_argument("--epochs",       type=int,   default=3)
    parser.add_argument("--price-per-million", type=float, default=25.0,
                        help="Cost per 1M training tokens (USD). Default: 25.0.")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    raw_dataset  = Path(args.raw_dataset)

    if not dataset_path.exists():
        raise SystemExit(f"Dataset not found: {dataset_path}")

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise SystemExit("GOOGLE_API_KEY not set in environment or Util/.env")

    client = genai.Client(api_key=api_key)

    lines = [l for l in dataset_path.read_text().splitlines() if l.strip()]
    print(f"Dataset:      {dataset_path}  ({len(lines)} examples)")
    print(f"Model:        {args.model}")
    print(f"Epochs:       {args.epochs}")
    print()

    total_tokens = 0
    all_warnings = []

    for i, line in enumerate(lines):
        record = json.loads(line)

        sys_text = " ".join(
            p["text"] for p in record.get("systemInstruction", {}).get("parts", [])
        )

        contents, warnings = build_api_contents(record, raw_dataset)
        all_warnings.extend(warnings)

        all_contents = []
        if sys_text:
            all_contents.append(types.Content(
                role="user",
                parts=[types.Part.from_text(text=sys_text)],
            ))
        all_contents.extend(contents)

        result = client.models.count_tokens(
            model=args.model,
            contents=all_contents,
        )

        tokens = result.total_tokens
        total_tokens += tokens

        try:
            first_file_uri = next(
                p["fileData"]["fileUri"]
                for turn in record["contents"]
                for p in turn["parts"]
                if "fileData" in p
            )
            m = re.search(r"/([^/]+)/(before|after)\.png$", first_file_uri, re.IGNORECASE)
            name = m.group(1) if m else f"example-{i+1}"
        except StopIteration:
            name = f"example-{i+1}"

        print(f"  {name:<45}  {tokens:>6,} tokens")

    print()
    print(f"{'─'*65}")
    print(f"  Total tokens (1 epoch):   {total_tokens:>10,}")
    print(f"  × {args.epochs} epochs:              {total_tokens * args.epochs:>10,}")

    billable = total_tokens * args.epochs
    cost = billable / 1_000_000 * args.price_per_million
    print(f"  Estimated cost:           ${cost:>9.4f}  (at ${args.price_per_million}/M tokens)")

    if all_warnings:
        print(f"\nWarnings ({len(all_warnings)}):")
        for w in all_warnings:
            print(f"  {w}")


if __name__ == "__main__":
    main()
