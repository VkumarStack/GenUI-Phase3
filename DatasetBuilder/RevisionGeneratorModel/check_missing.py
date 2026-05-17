"""
Find and label RawDataset examples that are missing a revision Taxonomy.txt.

Scans Datasets/RawDataset/ for folders where Taxonomy.txt is absent. For each
unique case study (Participant_X_CaseStudy-Y.Z) that has any missing folder,
makes one API call to assign categories from the existing revision taxonomy, then
writes Taxonomy.txt to every model-variant folder for that case study (CLAUDE,
GEMINI, OPENAI) — keeping the dataset consistent across variants.

Running:
    python DatasetBuilder/RevisionGeneratorModel/check_missing.py
    python DatasetBuilder/RevisionGeneratorModel/check_missing.py --dry-run
    python DatasetBuilder/RevisionGeneratorModel/check_missing.py --model gemini-2.5-flash
    python DatasetBuilder/RevisionGeneratorModel/check_missing.py --dataset path/to/Datasets/RawDataset
"""

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
from backends import GeminiBackend

sys.path.insert(0, str(_ROOT / "Taxonomy" / "RevisionTaxonomy"))
from assign import assign

_DATASET = _ROOT / "Datasets" / "RawDataset"
_TAXONOMY_JSON = _ROOT / "Taxonomy" / "RevisionTaxonomy" / "Results" / "taxonomy.json"
_MODEL_SUFFIX = re.compile(r"-(CLAUDE|GEMINI|OPENAI)$")
_DEFAULT_MODEL = "gemini-2.5-pro"


def main():
    parser = argparse.ArgumentParser(
        description="Label RawDataset examples that are missing a revision taxonomy."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be labeled without making API calls or writing files.")
    parser.add_argument("--model", default=_DEFAULT_MODEL,
                        help=f"Gemini model (default: {_DEFAULT_MODEL}).")
    parser.add_argument("--dataset", default=str(_DATASET), metavar="PATH",
                        help=f"RawDataset directory (default: {_DATASET}).")
    args = parser.parse_args()

    if not _TAXONOMY_JSON.exists():
        raise SystemExit(
            f"Taxonomy not found: {_TAXONOMY_JSON}\n"
            "Run Taxonomy/RevisionTaxonomy/consolidate.py first."
        )

    taxonomy = json.loads(_TAXONOMY_JSON.read_text())
    dataset = Path(args.dataset)

    # Group folders by unique case study key
    groups: dict[str, list[Path]] = {}
    for folder in sorted(dataset.iterdir()):
        if not folder.is_dir():
            continue
        key = _MODEL_SUFFIX.sub("", folder.name)
        groups.setdefault(key, []).append(folder)

    # Only process groups where at least one folder is missing Taxonomy.txt
    missing_groups = {
        key: folders
        for key, folders in groups.items()
        if any(not (f / "Taxonomy.txt").exists() for f in folders)
    }

    if not missing_groups:
        print("All examples have Taxonomy.txt — nothing to do.")
        return

    print(f"Found {len(missing_groups)} unique example(s) with missing Taxonomy.txt:")
    for key in sorted(missing_groups):
        missing = [f.name for f in missing_groups[key] if not (f / "Taxonomy.txt").exists()]
        present = len(missing_groups[key]) - len(missing)
        parts = [f"{len(missing)} missing"]
        if present:
            parts.append(f"{present} already labeled")
        print(f"  {key}: {', '.join(parts)}")

    if args.dry_run:
        print("\n--dry-run: no API calls or file writes performed.")
        return

    backend = GeminiBackend(args.model)
    n = len(missing_groups)
    labeled = errors = 0

    for i, (key, folders) in enumerate(sorted(missing_groups.items()), start=1):
        rep = sorted(folders)[0]
        screenshot = rep / "Before" / "screenshot.png"
        task_file = rep / "Task.txt"

        if not screenshot.exists() or not task_file.exists():
            print(f"  [{i}/{n}] SKIP {key}: missing Task.txt or Before/screenshot.png")
            errors += 1
            continue

        task = task_file.read_text().strip()
        print(f"  [{i}/{n}] {key} ... ", end="", flush=True)

        try:
            categories = assign(task, screenshot.read_bytes(), taxonomy, backend)
            print(categories)
            for folder in folders:
                (folder / "Taxonomy.txt").write_text("\n".join(categories) + "\n")
            labeled += 1
        except Exception as e:
            print(f"ERROR: {e}")
            errors += 1

    print(f"\nDone. Labeled: {labeled}  Errors: {errors}")


if __name__ == "__main__":
    main()
