"""
Find and label RawDataset examples that are missing a revision Taxonomy.txt.

Two-stage resolution:
  1. Reuse — if another participant's folder for the same CaseStudy-Y.Z already
     has a taxonomy assignment in taxonomy.json, copy it without an API call.
  2. Assign — if no match exists, call the LLM to assign categories from the
     existing taxonomy, then write Taxonomy.txt to all model-variant folders for
     that case study.

In both cases the taxonomy.json assignments dict is updated so future runs skip
already-resolved keys.

Running:
    python DatasetBuilder/RevisionGeneratorModel/check_missing.py
    python DatasetBuilder/RevisionGeneratorModel/check_missing.py --dry-run
    python DatasetBuilder/RevisionGeneratorModel/check_missing.py --backend gemini
    python DatasetBuilder/RevisionGeneratorModel/check_missing.py --dataset path/to/RawDataset
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
from backends import get_backend

sys.path.insert(0, str(_ROOT / "Taxonomy" / "RevisionTaxonomy"))
from assign import assign

_DATASET      = _ROOT / "Datasets" / "RawDataset"
_TAXONOMY_JSON = _ROOT / "Taxonomy" / "RevisionTaxonomy" / "Results" / "taxonomy.json"
_MODEL_SUFFIX = re.compile(r"-(CLAUDE|GEMINI|OPENAI)$")
_CS_RE        = re.compile(r"CaseStudy-(.+)")


def _cs_key(folder_name: str) -> str | None:
    """Extract CaseStudy-Y.Z from a folder or assignment key."""
    m = _CS_RE.search(folder_name)
    return m.group(1) if m else None


def main():
    parser = argparse.ArgumentParser(
        description="Label RawDataset examples missing a revision taxonomy."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be done without writing files or API calls.")
    parser.add_argument("--backend", default="gemini",
                        choices=["gemini", "vertexai", "anthropic", "openai"])
    parser.add_argument("--model", default=None,
                        help="Override model (optional).")
    parser.add_argument("--dataset", default=str(_DATASET), metavar="PATH",
                        help=f"RawDataset directory (default: {_DATASET}).")
    args = parser.parse_args()

    if not _TAXONOMY_JSON.exists():
        raise SystemExit(
            f"Taxonomy not found: {_TAXONOMY_JSON}\n"
            "Run Taxonomy/RevisionTaxonomy/consolidate.py first."
        )

    taxonomy      = json.loads(_TAXONOMY_JSON.read_text())
    assignments   = taxonomy.setdefault("assignments", {})
    dataset       = Path(args.dataset)

    # Build CaseStudy-Y.Z → categories lookup from existing assignments
    cs_to_cats: dict[str, list[str]] = {}
    for key, cats in assignments.items():
        cs = _cs_key(key)
        if cs and cs not in cs_to_cats:
            cs_to_cats[cs] = cats

    # Group folders by unique case study key (strip model suffix)
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

    # Split into reusable vs genuinely new
    reuse_groups: dict[str, list[str]] = {}   # key -> categories from matched cs
    new_groups:   dict[str, list[Path]] = {}

    for key, folders in missing_groups.items():
        cs = _cs_key(key)
        if cs and cs in cs_to_cats and key not in assignments:
            reuse_groups[key] = cs_to_cats[cs]
        else:
            new_groups[key] = folders

    print(f"Missing Taxonomy.txt in {len(missing_groups)} unique example(s):")
    print(f"  {len(reuse_groups)} can reuse existing assignment by CaseStudy-Y.Z")
    print(f"  {len(new_groups)} are genuinely new and need LLM assignment")

    if args.dry_run:
        print("\nReuse candidates:")
        for key, cats in sorted(reuse_groups.items()):
            print(f"  {key}: {cats}")
        print("\nNew (need API):")
        for key in sorted(new_groups):
            print(f"  {key}")
        print("\n--dry-run: no file writes or API calls performed.")
        return

    reused = api_labeled = errors = 0

    # Stage 1: reuse
    for key, cats in sorted(reuse_groups.items()):
        folders = groups[key]
        missing_folders = [f for f in folders if not (f / "Taxonomy.txt").exists()]
        print(f"  [REUSE] {key}: {cats}")
        for folder in missing_folders:
            (folder / "Taxonomy.txt").write_text("\n".join(cats) + "\n")
        assignments[key] = cats
        reused += 1

    # Stage 2: API for genuinely new
    if new_groups:
        backend = get_backend(args.backend, args.model)
        n = len(new_groups)
        for i, (key, folders) in enumerate(sorted(new_groups.items()), start=1):
            rep = sorted(folders)[0]
            screenshot = rep / "Before" / "screenshot.png"
            task_file  = rep / "Task.txt"

            if not screenshot.exists() or not task_file.exists():
                print(f"  [{i}/{n}] SKIP {key}: missing Task.txt or Before/screenshot.png")
                errors += 1
                continue

            task = task_file.read_text().strip()
            print(f"  [{i}/{n}] {key} ... ", end="", flush=True)

            try:
                cats = assign(task, screenshot.read_bytes(), taxonomy, backend)
                print(cats)
                for folder in folders:
                    (folder / "Taxonomy.txt").write_text("\n".join(cats) + "\n")
                assignments[key] = cats
                cs = _cs_key(key)
                if cs and cs not in cs_to_cats:
                    cs_to_cats[cs] = cats
                api_labeled += 1
            except Exception as e:
                print(f"ERROR: {e}")
                errors += 1

    # Write updated taxonomy.json
    taxonomy["assignments"] = assignments
    _TAXONOMY_JSON.write_text(json.dumps(taxonomy, indent=2))

    print(f"\nDone. Reused: {reused}  API-labeled: {api_labeled}  Errors: {errors}")
    print(f"Updated {_TAXONOMY_JSON.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
