"""
Compute and cache html_diff.txt for every example in Datasets/RawDataset/.

Writes <example_folder>/html_diff.txt — a standard unified diff of the raw
Before/After HTML source.  Safe to re-run: skips folders that already have a
cached file unless --force is passed.

Run this before split.py so all HTML diffs are available to copy into
EvaluatorModelDataset.

Running:
    python DatasetBuilder/EvaluatorModel/cache_html_diffs.py
    python DatasetBuilder/EvaluatorModel/cache_html_diffs.py --force
    python DatasetBuilder/EvaluatorModel/cache_html_diffs.py --dataset path/to/Datasets/RawDataset

To generate html_diff.txt for the EvaluatorModelDataset directly (e.g. after
filtering), use --dataset Datasets/EvaluatorModelDataset.
"""

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT / "Util"))
from html_diff import html_diff

_DATASET = _ROOT / "Datasets" / "RawDataset"


def main():
    parser = argparse.ArgumentParser(
        description="Cache html_diff.txt for all examples in a dataset directory."
    )
    parser.add_argument("--dataset", default=str(_DATASET), metavar="PATH",
                        help=f"Dataset directory (default: {_DATASET}).")
    parser.add_argument("--force", action="store_true",
                        help="Recompute even if html_diff.txt already exists.")
    args = parser.parse_args()

    dataset = Path(args.dataset)
    folders = sorted(f for f in dataset.iterdir() if f.is_dir())
    written = skipped = errors = 0

    for i, folder in enumerate(folders, start=1):
        out = folder / "html_diff.txt"
        if out.exists() and not args.force:
            skipped += 1
            continue

        before = folder / "Before" / "index.html"
        after  = folder / "After"  / "index.html"

        if not before.exists() or not after.exists():
            print(f"  [{i}/{len(folders)}] SKIP {folder.name}: missing HTML")
            errors += 1
            continue

        print(f"  [{i}/{len(folders)}] {folder.name}", end="", flush=True)
        try:
            result = html_diff(before, after)
            out.write_text(result, encoding="utf-8")
            print(" ✓")
            written += 1
        except Exception as e:
            print(f" ERROR: {e}")
            errors += 1

    print(f"\nDone. Written: {written}  Skipped (cached): {skipped}  Errors: {errors}")


if __name__ == "__main__":
    main()
