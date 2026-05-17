"""
Generate Step 1 expected-change specs for all RawDataset examples that don't
have one yet, writing step1_spec.txt directly into each example folder.

Step 1 takes the revision task + Before screenshot and produces a grounded spec
of what the revised interface should look like. It is shared input for Step 2.

Because Step 1 only depends on the task + Before screenshot (identical across
all model variants of the same case study), deduplication is applied: the model
is called once per unique Participant+CaseStudy key, and the result is written to
all model-variant folders (CLAUDE, GEMINI, OPENAI) for that case study.

Running:
    python DatasetBuilder/EvaluatorModel/fill_step1.py
    python DatasetBuilder/EvaluatorModel/fill_step1.py --model gemini-2.5-flash
    python DatasetBuilder/EvaluatorModel/fill_step1.py --dataset path/to/Datasets/RawDataset
"""

import argparse
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
from backends import GeminiBackend

sys.path.insert(0, str(_ROOT / "Evaluator"))
from step1 import run_one

_DATASET = _ROOT / "Datasets" / "RawDataset"
_MODEL_SUFFIX = re.compile(r"-(CLAUDE|GEMINI|OPENAI)$")
_DEFAULT_MODEL = "gemini-2.5-pro"
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
        description="Fill missing Step 1 specs into RawDataset example folders."
    )
    parser.add_argument("--model", default=_DEFAULT_MODEL,
                        help=f"Gemini model (default: {_DEFAULT_MODEL}).")
    parser.add_argument("--dataset", default=str(_DATASET), metavar="PATH",
                        help=f"RawDataset directory (default: {_DATASET}).")
    args = parser.parse_args()

    dataset = Path(args.dataset)
    groups = _group_folders(dataset)

    # A group needs filling if ANY of its folders is missing step1_spec.txt
    missing_groups = {
        key: folders
        for key, folders in groups.items()
        if any(not (f / _SPEC_FILENAME).exists() for f in folders)
    }

    if not missing_groups:
        print(f"All {len(groups)} examples already have {_SPEC_FILENAME}.")
        return

    print(f"Running Step 1 for {len(missing_groups)} example(s) (of {len(groups)} total)")

    backend = GeminiBackend(args.model)
    n = len(missing_groups)
    done = errors = 0

    for i, (key, folders) in enumerate(sorted(missing_groups.items()), start=1):
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
