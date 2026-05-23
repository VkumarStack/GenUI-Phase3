"""
Temporary script: sample N training examples from train.jsonl and render as
markdown with the Before screenshot, category, and target task text for
manual verification before committing to fine-tuning.

Usage:
    python FineTuning/RevisionGenerator/inspect_dataset.py
    python FineTuning/RevisionGenerator/inspect_dataset.py --n 5 --seed 7
    python FineTuning/RevisionGenerator/inspect_dataset.py > review.md
"""

import argparse
import json
import random
import re
import sys
from pathlib import Path

_ROOT     = Path(__file__).parent.parent.parent
_JSONL    = Path(__file__).parent / "train.jsonl"
_MANIFEST = _ROOT / "FineTuning" / "manifest.json"
_RAW      = _ROOT / "Datasets" / "RawDataset"

_CAT_RE = re.compile(r"REVISION TYPE[^:]*:\s*\n\s*([^:]+):", re.DOTALL)


def _gcs_to_local(gcs_uri: str, manifest_inv: dict[str, str]) -> Path | None:
    """Map a GCS before URI back to the local RawDataset screenshot."""
    return Path(manifest_inv[gcs_uri]) if gcs_uri in manifest_inv else None


def _parse_record(record: dict) -> dict:
    user_parts  = record["contents"][0]["parts"]
    model_parts = record["contents"][1]["parts"]

    # System instruction
    sys_parts = record.get("systemInstruction", {}).get("parts", [])
    system_text = next((p["text"] for p in sys_parts if "text" in p), "")

    # Category from user text
    user_text = next((p["text"] for p in user_parts if "text" in p), "")
    cat_match = _CAT_RE.search(user_text)
    category  = cat_match.group(1).strip() if cat_match else "Unknown"

    # GCS URI
    gcs_uri = next(
        (p["fileData"]["fileUri"] for p in user_parts if "fileData" in p), ""
    )

    # Target task (model response)
    target = next((p["text"] for p in model_parts if "text" in p), "")

    return {"category": category, "gcs_uri": gcs_uri, "target": target,
            "user_text": user_text, "system_text": system_text}


def main():
    parser = argparse.ArgumentParser(
        description="Sample training examples from train.jsonl as markdown."
    )
    parser.add_argument("--n",    type=int, default=10, metavar="N",
                        help="Number of examples to sample (default: 10).")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--jsonl", default=str(_JSONL), metavar="PATH")
    args = parser.parse_args()

    jsonl_path = Path(args.jsonl)
    if not jsonl_path.exists():
        raise SystemExit(f"JSONL not found: {jsonl_path}\n"
                         "Run FineTuning/RevisionGenerator/build_dataset.py first.")
    if not _MANIFEST.exists():
        raise SystemExit(f"Manifest not found: {_MANIFEST}\n"
                         "Run FineTuning/upload_assets.py first.")

    records = [json.loads(l) for l in jsonl_path.read_text().splitlines() if l.strip()]
    manifest = json.loads(_MANIFEST.read_text())

    # Build inverse map: gcs_before_uri -> local screenshot path
    manifest_inv: dict[str, str] = {}
    for folder_name, uris in manifest.items():
        if "before" in uris:
            local = _RAW / folder_name / "Before" / "screenshot.png"
            manifest_inv[uris["before"]] = str(local)

    rng = random.Random(args.seed)
    sample = rng.sample(records, min(args.n, len(records)))

    # Header
    print(f"# RevisionGenerator Training Sample")
    print(f"")
    print(f"**JSONL:** `{jsonl_path.relative_to(_ROOT)}`  ")
    print(f"**Total records:** {len(records)}  |  **Sampled:** {len(sample)}  "
          f"|  **Seed:** {args.seed}")
    print(f"")
    print(f"---")
    print(f"")

    for i, record in enumerate(sample, 1):
        parsed = _parse_record(record)
        local  = _gcs_to_local(parsed["gcs_uri"], manifest_inv)

        if local and local.exists():
            # Relative path from project root for IDE preview
            img_tag = f"![screenshot]({local.relative_to(_ROOT)})"
        elif local:
            img_tag = f"_screenshot not found at `{local.relative_to(_ROOT)}`_"
        else:
            img_tag = f"_GCS URI not in manifest: `{parsed['gcs_uri']}`_"

        print(f"## {i}. {parsed['category']}")
        print(f"")
        print(img_tag)
        print(f"")
        if parsed["system_text"] and i == 1:
            # Only print system prompt once — it's identical for every record
            print(f"**System instruction** _(same for all records)_**:**")
            print(f"")
            print(f"```")
            print(parsed["system_text"])
            print(f"```")
            print(f"")
        print(f"**Prompt (user turn):**")
        print(f"")
        print(f"```")
        print(parsed["user_text"])
        print(f"```")
        print(f"")
        print(f"**Target task:**")
        print(f"")
        print(f"> {parsed['target']}")
        print(f"")
        print(f"---")
        print(f"")


if __name__ == "__main__":
    main()
