"""
Temporary script: copy updated dom_diff.txt files from RawDataset into
EvaluatorModelDataset/Train and Test without reshuffling the split.

Run after cache_dom_diffs.py --force has recomputed the diffs in RawDataset.

Usage:
    python DatasetBuilder/EvaluatorModel/sync_dom_diffs.py
"""

import json
import shutil
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
_SUMMARY = Path(__file__).parent / "split_summary.json"
_RAW = _ROOT / "Datasets" / "RawDataset"
_OUT = _ROOT / "Datasets" / "EvaluatorModelDataset"


def main():
    summary = json.loads(_SUMMARY.read_text())
    copied = missing = 0

    for split in ("train", "test"):
        base = _OUT / split.capitalize()
        for entry in summary[split]:
            src = _RAW / entry["source"] / "dom_diff.txt"
            dst = base / entry["folder"] / "dom_diff.txt"
            if src.exists():
                shutil.copy2(src, dst)
                copied += 1
            else:
                print(f"  [MISSING] {entry['source']}/dom_diff.txt")
                missing += 1

    print(f"Copied {copied} dom_diff.txt files ({missing} missing in RawDataset).")


if __name__ == "__main__":
    main()
