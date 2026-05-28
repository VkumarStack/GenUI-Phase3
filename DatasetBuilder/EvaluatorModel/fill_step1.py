"""
Generate Step 1 code-analysis specs for all EvaluatorModelDataset examples
that don't have one yet, writing step1_spec.txt directly into each folder.

Step 1 now depends on the HTML diff (Before → After), which differs per model
variant, so each folder is processed independently — no deduplication.

Running:
    python DatasetBuilder/EvaluatorModel/fill_step1.py
    python DatasetBuilder/EvaluatorModel/fill_step1.py --dataset path/to/Datasets/EvaluatorModelDataset
    python DatasetBuilder/EvaluatorModel/fill_step1.py --force
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
from backends import get_backend

sys.path.insert(0, str(_ROOT / "Evaluator"))
from step1 import run_one

_DATASET       = _ROOT / "Datasets" / "EvaluatorModelDataset"
_SPEC_FILENAME = "step1_spec.txt"
_DEFAULT_MODEL = "gemini-3.1-pro-preview"


def main():
    parser = argparse.ArgumentParser(
        description="Fill missing Step 1 code-analysis specs into EvaluatorModelDataset folders."
    )
    parser.add_argument("--backend", default="gemini",
                        choices=["gemini", "vertexai", "anthropic", "openai"],
                        help="Model backend (default: gemini).")
    parser.add_argument("--model", default=None,
                        help="Override model/endpoint (optional; uses backend default).")
    parser.add_argument("--dataset", default=str(_DATASET), metavar="PATH",
                        help=f"EvaluatorModelDataset directory (default: {_DATASET}).")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate step1_spec.txt even if it already exists.")
    args = parser.parse_args()

    dataset = Path(args.dataset)
    folders = sorted(f for f in dataset.iterdir() if f.is_dir())

    if args.force:
        targets = folders
    else:
        targets = [f for f in folders if not (f / _SPEC_FILENAME).exists()]

    if not targets:
        print(f"All {len(folders)} folders already have {_SPEC_FILENAME}.")
        return

    print(f"Running Step 1 for {len(targets)} folder(s) (of {len(folders)} total)")

    model   = args.model or (_DEFAULT_MODEL if args.backend == "gemini" else None)
    backend = get_backend(args.backend, model)
    n = len(targets)
    done = errors = 0

    for i, folder in enumerate(targets, start=1):
        print(f"  [{i}/{n}] {folder.name} ... ", end="", flush=True)
        try:
            result = run_one(folder, backend)
            if "error" in result:
                print(f"SKIP — {result['error']}")
                errors += 1
                continue

            spec = result["code_analysis"]
            print(spec.splitlines()[0][:80])
            (folder / _SPEC_FILENAME).write_text(spec, encoding="utf-8")
            done += 1
        except Exception as e:
            print(f"ERROR: {e}")
            errors += 1

    print(f"\nDone. Written: {done}  Errors: {errors}")


if __name__ == "__main__":
    main()
