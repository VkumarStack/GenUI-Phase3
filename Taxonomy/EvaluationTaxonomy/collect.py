"""
Phase 1 — parse all Output.txt files in Datasets/EvaluatorModelDataset/ into raw_data.json.

No API calls; just structured extraction. Validates data before spending
API credits on labeling.

Running:
    python EvaluationTaxonomy/collect.py
    python EvaluationTaxonomy/collect.py --dataset path/to/Datasets/EvaluatorModelDataset
"""

import argparse
import json
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
_DATASET = _ROOT / "Datasets" / "EvaluatorModelDataset"
_OUTPUT = Path(__file__).parent / "raw_data.json"


def parse_output(text: str) -> dict:
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    verdict = lines[0] if lines else "UNKNOWN"
    pass_reason = None
    fail_reason = None
    for line in lines[1:]:
        if line.startswith("Pass Reasons:"):
            pass_reason = line.removeprefix("Pass Reasons:").strip() or None
        elif line.startswith("Fail Reasons:"):
            fail_reason = line.removeprefix("Fail Reasons:").strip() or None
    return {"verdict": verdict, "pass_reason": pass_reason, "fail_reason": fail_reason}


def main():
    parser = argparse.ArgumentParser(description="Parse Output.txt files into raw_data.json.")
    parser.add_argument("--dataset", default=str(_DATASET), metavar="PATH")
    args = parser.parse_args()

    dataset = Path(args.dataset)
    results = {}
    missing = []

    for folder in sorted(dataset.iterdir()):
        if not folder.is_dir():
            continue
        output_file = folder / "Output.txt"
        if not output_file.exists():
            missing.append(folder.name)
            continue
        results[folder.name] = parse_output(output_file.read_text(errors="replace"))

    _OUTPUT.write_text(json.dumps(results, indent=2))

    verdicts = {}
    for entry in results.values():
        verdicts[entry["verdict"]] = verdicts.get(entry["verdict"], 0) + 1
    pass_count = sum(1 for e in results.values() if e["pass_reason"])
    fail_count = sum(1 for e in results.values() if e["fail_reason"])

    print(f"Parsed {len(results)} folders.  Verdicts: {verdicts}")
    print(f"Pass reason entries: {pass_count}  |  Fail reason entries: {fail_count}")
    if missing:
        print(f"WARNING: {len(missing)} folder(s) missing Output.txt: {missing}")
    print(f"Saved → {_OUTPUT.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
