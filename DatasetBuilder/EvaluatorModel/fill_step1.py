"""
Generate Step 1 expected-change specs for all EvaluatorModelDataset examples
that don't have one yet, writing step1_spec.txt directly into each example folder.

Step 1 takes the revision task + Before screenshot and produces a grounded spec
of what the revised interface should look like. It is shared input for Step 2.

Because Step 1 only depends on the task + Before screenshot (identical across
all model variants of the same case study), deduplication is applied: the model
is called once per unique Participant+CaseStudy key, and the result is written to
all model-variant folders (CLAUDE, GEMINI, OPENAI) for that case study.

Running:
    python DatasetBuilder/EvaluatorModel/fill_step1.py
    python DatasetBuilder/EvaluatorModel/fill_step1.py --model gemini-2.5-flash
    python DatasetBuilder/EvaluatorModel/fill_step1.py --dataset path/to/Datasets/EvaluatorModelDataset
"""

import argparse
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
from backends import get_backend

sys.path.insert(0, str(_ROOT / "Evaluator"))
from step1 import run_one

_DATASET = _ROOT / "Datasets" / "EvaluatorModelDataset"
_MODEL_SUFFIX = re.compile(r"-(CLAUDE|GEMINI|OPENAI)$")
_SPEC_FILENAME = "step1_spec.txt"


def _group_folders(dataset_dir: Path) -> dict[str, list[Path]]:
    """Return {key: [all variant folders]} for every unique case study."""
    groups: dict[str, list[Path]] = {}
    for folder in sorted(dataset_dir.iterdir()):
        if not folder.is_dir():
            continue
        key = _MODEL_SUFFIX.sub("", folder.name)
        groups.setdefault(key, []).append(folder)
    return groups


def main():
    parser = argparse.ArgumentParser(
        description="Fill missing Step 1 specs into EvaluatorModelDataset example folders."
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
    groups = _group_folders(dataset)

    if args.force:
        target_groups = dict(groups)
    else:
        # A group needs filling if ANY of its folders is missing step1_spec.txt
        target_groups = {
            key: folders
            for key, folders in groups.items()
            if any(not (f / _SPEC_FILENAME).exists() for f in folders)
        }

    if not target_groups:
        print(f"All {len(groups)} examples already have {_SPEC_FILENAME}.")
        return

    print(f"Running Step 1 for {len(target_groups)} example(s) (of {len(groups)} total)")

    backend = get_backend(args.backend, args.model)
    n = len(target_groups)
    done = errors = 0

    for i, (key, folders) in enumerate(sorted(target_groups.items()), start=1):
        rep = sorted(folders)[0]
        print(f"  [{i}/{n}] {key} ... ", end="", flush=True)
        try:
            result = run_one(rep, backend)
            if "error" in result:
                print(f"SKIP — {result['error']}")
                errors += 1
                continue

            spec = result["expected_change_spec"]
            print(spec.splitlines()[0][:80])

            for folder in folders:
                (folder / _SPEC_FILENAME).write_text(spec)
            done += 1
        except Exception as e:
            print(f"ERROR: {e}")
            errors += 1

    print(f"\nDone. Labeled: {done}  Errors: {errors}")


if __name__ == "__main__":
    main()
