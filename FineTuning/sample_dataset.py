"""
Randomly sample training examples from the evaluator and revision generator
datasets and print them as markdown for spot-checking.

Usage:
    python FineTuning/sample_dataset.py
    python FineTuning/sample_dataset.py --n 5
    python FineTuning/sample_dataset.py --seed 42
    python FineTuning/sample_dataset.py > review.md
"""

import argparse
import json
import random
import re
import textwrap
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_EVALUATOR_JSONL   = Path(__file__).parent / "Evaluator"   / "train.jsonl"
_REVISION_JSONL    = Path(__file__).parent / "RevisionGenerator" / "train.jsonl"

_DIFF_TRUNCATE = 600


def _source_name(record: dict) -> str:
    """Extract RawDataset folder name from the first GCS URI in the record."""
    for turn in record["contents"]:
        for part in turn["parts"]:
            if "fileData" in part:
                m = re.search(r"/([^/]+)/(before|after)\.png$", part["fileData"]["fileUri"], re.I)
                if m:
                    return m.group(1)
    return "(unknown)"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n*[… {len(text) - limit} chars truncated]*"


def _render_evaluator(record: dict, idx: int) -> str:
    source = _source_name(record)
    user_parts = record["contents"][0]["parts"]
    model_text = record["contents"][1]["parts"][0]["text"]

    # user_parts: [text(task+spec+diff+instructions), text("Before screenshot:"),
    #              fileData, text("After screenshot:"), fileData]
    main_text = user_parts[0]["text"]

    # Split out task / spec / diff from the combined user text block
    task = spec = diff = main_text
    if "Expected-change specification:" in main_text:
        parts = main_text.split("Expected-change specification:", 1)
        task = parts[0].replace("Revision task:", "").strip()
        rest = parts[1]
        if "DOM diff (supporting context):" in rest:
            spec_raw, diff_raw = rest.split("DOM diff (supporting context):", 1)
            spec = spec_raw.strip()
            diff = diff_raw.split("Assess the Before")[0].strip()
        else:
            spec = rest.strip()
            diff = "(not present)"

    lines = [
        f"### Example {idx} — `{source}`",
        "",
        "**Task**",
        "",
        task,
        "",
        "**Expected-change spec**",
        "",
        spec,
        "",
        "**DOM diff**",
        "",
        _truncate(diff, _DIFF_TRUNCATE),
        "",
        "**Label (model target)**",
        "",
        model_text,
        "",
        "---",
    ]
    return "\n".join(lines)


def _render_revision(record: dict, idx: int) -> str:
    source = _source_name(record)
    user_text = record["contents"][0]["parts"][0]["text"]
    model_text = record["contents"][1]["parts"][0]["text"]

    # user_text: "REVISION TYPE — Category: Desc\n\nGenerate the revision task..."
    category_line = user_text.split("\n")[0].removeprefix("REVISION TYPE — your task must belong to this category:").strip()
    if not category_line:
        # fallback: grab second line
        lines_raw = user_text.strip().splitlines()
        category_line = lines_raw[1].strip() if len(lines_raw) > 1 else user_text

    lines = [
        f"### Example {idx} — `{source}`",
        "",
        "**Revision type**",
        "",
        category_line,
        "",
        "**Task (model target)**",
        "",
        model_text,
        "",
        "---",
    ]
    return "\n".join(lines)


def sample_dataset(path: Path, n: int, renderer, label: str) -> str:
    if not path.exists():
        return f"*{path} not found — run build_dataset.py first.*\n"

    records = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    chosen = random.sample(records, min(n, len(records)))

    sections = [f"## {label}  ({n} of {len(records)} sampled)\n"]
    for i, record in enumerate(chosen, 1):
        sections.append(renderer(record, i))
    return "\n".join(sections)


def main():
    parser = argparse.ArgumentParser(description="Spot-check SFT training examples.")
    parser.add_argument("--n",    type=int, default=10, help="Samples per dataset (default: 10).")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility.")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    print("# SFT Training Data Spot-Check\n")

    print(sample_dataset(_EVALUATOR_JSONL, args.n, _render_evaluator,
                         "Evaluator Model"))
    print()
    print(sample_dataset(_REVISION_JSONL, args.n, _render_revision,
                         "Revision Generator Model"))


if __name__ == "__main__":
    main()
