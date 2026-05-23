"""
Build the RevisionGeneratorModelDataset from RawDataset.

No train/test split — all examples land in a single flat directory:
    Datasets/RevisionGeneratorModelDataset/All/

Each unique example (Participant_X_CaseStudy-Y.Z) with a taxonomy assignment
is expanded into one folder per (example, label) pair.

Output layout:
    Datasets/RevisionGeneratorModelDataset/All/
        Example-000/
            screenshot.png
            prompt.txt       ← "Category: X\\nDescription: Y"
            task.txt         ← revision task text
            meta.json        ← provenance
        ...
    DatasetBuilder/RevisionGeneratorModel/split_summary.json

Running:
    python DatasetBuilder/RevisionGeneratorModel/split.py
    python DatasetBuilder/RevisionGeneratorModel/split.py --dataset path/to/RawDataset
"""

import argparse
import json
import re
import shutil
from collections import Counter
from pathlib import Path

_ROOT          = Path(__file__).parent.parent.parent
_DATASET       = _ROOT / "Datasets" / "RawDataset"
_TAXONOMY_JSON = _ROOT / "Taxonomy" / "RevisionTaxonomy" / "Results" / "taxonomy.json"
_OUT_DIR       = _ROOT / "Datasets" / "RevisionGeneratorModelDataset" / "All"
_SUMMARY_FILE  = Path(__file__).parent / "split_summary.json"
_MODEL_SUFFIX  = re.compile(r"-(CLAUDE|GEMINI|OPENAI)$")

_PROMPT_TEMPLATE = "Category: {name}\nDescription: {description}"


def main():
    parser = argparse.ArgumentParser(
        description="Build RevisionGeneratorModelDataset (no train/test split)."
    )
    parser.add_argument("--dataset", default=str(_DATASET), metavar="PATH",
                        help=f"RawDataset directory (default: {_DATASET}).")
    args = parser.parse_args()

    taxonomy    = json.loads(_TAXONOMY_JSON.read_text())
    assignments = taxonomy["assignments"]
    categories  = {c["name"]: c["description"] for c in taxonomy["categories"]}

    # One representative folder per unique key (first alphabetically = CLAUDE when available)
    dataset = Path(args.dataset)
    rep_map: dict[str, Path] = {}
    for folder in sorted(dataset.iterdir()):
        if not folder.is_dir():
            continue
        key = _MODEL_SUFFIX.sub("", folder.name)
        if key not in rep_map:
            rep_map[key] = folder

    # Only include examples that have taxonomy assignments
    all_keys = sorted(k for k in assignments if k in rep_map)
    skipped  = sorted(k for k in rep_map if k not in assignments)

    if skipped:
        print(f"WARNING: {len(skipped)} example(s) have no taxonomy assignment and will be skipped.")
        print("  Run DatasetBuilder/RevisionGeneratorModel/check_missing.py to label them.")
        for k in skipped:
            print(f"    {k}")

    # Category distribution
    label_counts = Counter(l for k in all_keys for l in assignments[k])
    print(f"\nDataset: {len(all_keys)} unique examples → "
          f"{sum(label_counts.values())} (example, label) pairs")
    for label, count in sorted(label_counts.items(), key=lambda x: -x[1]):
        print(f"  {label}: {count}")

    # Write output
    _OUT_DIR.mkdir(parents=True, exist_ok=True)

    records = []
    i = 0
    for key in all_keys:
        folder = rep_map[key]
        screenshot = folder / "Before" / "screenshot.png"
        task_file  = folder / "Task.txt"

        if not screenshot.exists() or not task_file.exists():
            print(f"  [SKIP] {key}: missing screenshot or Task.txt")
            continue

        task_text = task_file.read_text().strip()

        for label in assignments[key]:
            out_folder = _OUT_DIR / f"Example-{i:03d}"
            out_folder.mkdir(exist_ok=True)

            shutil.copy2(screenshot, out_folder / "screenshot.png")
            (out_folder / "prompt.txt").write_text(
                _PROMPT_TEMPLATE.format(name=label, description=categories[label])
            )
            (out_folder / "task.txt").write_text(task_text + "\n")
            (out_folder / "meta.json").write_text(json.dumps({
                "example_key":   key,
                "label":         label,
                "source_folder": folder.name,
            }, indent=2))

            records.append({"folder": f"Example-{i:03d}", "example_key": key, "label": label})
            i += 1

    summary = {
        "n_unique_examples": len(all_keys),
        "n_instances":       len(records),
        "n_skipped":         len(skipped),
        "records":           records,
    }
    _SUMMARY_FILE.write_text(json.dumps(summary, indent=2))

    print(f"\nWrote {len(records)} instances → Datasets/RevisionGeneratorModelDataset/All/")
    print(f"Saved split_summary.json")


if __name__ == "__main__":
    main()
