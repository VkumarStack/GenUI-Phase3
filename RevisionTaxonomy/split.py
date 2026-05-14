"""
Train/test split with multi-label iterative stratification.

Each unique example (Participant_X_CaseStudy-Y.Z) may have 1–2 taxonomy
labels; expanding by label yields one training instance per (example, label)
pair. All pairs from a given example land in the same split — no screenshot
leaks across train/test.

Algorithm: simplified Sechidis (2011) iterative stratification.
  1. Process examples in order of rarest label first.
  2. Assign each to whichever split has the greater remaining need for that label.
  3. Break ties by which split still has more space overall.

Output layout (one folder per (example, label) pair):
  RevisionFineTuning/
    Train/
      Example-000/
        screenshot.png
        prompt.txt       ← input: "Category: X\\nDescription: Y"
        task.txt         ← target: the original revision task text
        meta.json        ← provenance
      ...
    Test/
      ...
    split_summary.json   ← full provenance + coverage stats

Running:
    python RevisionTaxonomy/split.py
    python RevisionTaxonomy/split.py --test-size 10 --seed 42
"""

import argparse
import json
import re
import shutil
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_DATASET = _ROOT / "FilteredDataset"
_TAXONOMY_JSON = Path(__file__).parent / "taxonomy.json"
_OUT_ROOT = _ROOT / "RevisionFineTuning"
_MODEL_SUFFIX = re.compile(r"-(CLAUDE|GEMINI|OPENAI)$")

_PROMPT_TEMPLATE = "Category: {name}\nDescription: {description}"


# ---------------------------------------------------------------------------
# Stratification
# ---------------------------------------------------------------------------

def _iterative_stratify(keys: list[str], labels_map: dict[str, list[str]], n_test: int):
    """Return (train_keys, test_keys) using multi-label iterative stratification."""
    n_total = len(keys)
    n_train = n_total - n_test

    # Desired per-label counts in each split
    label_totals = Counter(l for k in keys for l in labels_map[k])
    desired_test = {l: max(1, round(c * n_test / n_total)) for l, c in label_totals.items()}
    desired_train = {l: max(1, round(c * n_train / n_total)) for l, c in label_totals.items()}

    remaining = list(keys)
    test: list[str] = []
    train: list[str] = []

    while remaining:
        pool_counts = Counter(l for k in remaining for l in labels_map[k])

        # Rarest label still in pool
        rarest = min(pool_counts, key=pool_counts.get)

        # Most-constrained example with that label (most total labels → hardest to place)
        candidates = [k for k in remaining if rarest in labels_map[k]]
        chosen = max(candidates, key=lambda k: len(labels_map[k]))
        remaining.remove(chosen)

        # Compute remaining need for rarest label in each split
        test_have = sum(1 for k in test if rarest in labels_map[k])
        train_have = sum(1 for k in train if rarest in labels_map[k])
        test_need = desired_test[rarest] - test_have
        train_need = desired_train[rarest] - train_have

        if test_need > train_need:
            test.append(chosen)
        elif train_need > test_need:
            train.append(chosen)
        else:
            # Tie: fill whichever split still has room
            test.append(chosen) if len(test) < n_test else train.append(chosen)

    return train, test


# ---------------------------------------------------------------------------
# Dataset expansion: one instance per (example, label) pair
# ---------------------------------------------------------------------------

def _expand(keys: list[str], labels_map: dict[str, list[str]], rep_map: dict[str, Path]):
    """Yield (example_key, label, screenshot_path, task_text) for each pair."""
    for key in keys:
        folder = rep_map[key]
        screenshot = folder / "Before" / "screenshot.png"
        task_text = (folder / "Task.txt").read_text().strip()
        for label in labels_map[key]:
            yield key, label, screenshot, task_text


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _write_instances(instances, split_dir: Path, categories: dict[str, str], counter_start: int):
    """Write Example-XXX folders. Returns list of metadata dicts."""
    records = []
    for i, (key, label, screenshot, task_text) in enumerate(instances, start=counter_start):
        folder = split_dir / f"Example-{i:03d}"
        folder.mkdir(parents=True, exist_ok=True)

        shutil.copy2(screenshot, folder / "screenshot.png")
        (folder / "prompt.txt").write_text(
            _PROMPT_TEMPLATE.format(name=label, description=categories[label])
        )
        (folder / "task.txt").write_text(task_text + "\n")
        (folder / "meta.json").write_text(json.dumps({
            "example_key": key,
            "label": label,
            "source_folder": screenshot.parent.parent.name,
        }, indent=2))

        records.append({"folder": folder.name, "example_key": key, "label": label})
    return records


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------

def _coverage(keys: list[str], labels_map: dict[str, list[str]], split_name: str):
    counts = Counter(l for k in keys for l in labels_map[k])
    print(f"\n{split_name} ({len(keys)} examples, {sum(counts.values())} instances):")
    for label, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {label}: {count}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Multi-label stratified train/test split.")
    parser.add_argument("--test-size", type=int, default=10, metavar="N",
                        help="Number of unique examples to reserve for test (default: 10).")
    args = parser.parse_args()

    taxonomy = json.loads(_TAXONOMY_JSON.read_text())
    assignments: dict[str, list[str]] = taxonomy["assignments"]
    categories: dict[str, str] = {c["name"]: c["description"] for c in taxonomy["categories"]}

    # Build representative folder map (one folder per unique example key)
    rep_map: dict[str, Path] = {}
    for folder in sorted(_DATASET.iterdir()):
        if not folder.is_dir():
            continue
        key = _MODEL_SUFFIX.sub("", folder.name)
        if key not in rep_map:
            rep_map[key] = folder  # first alphabetically = CLAUDE when available

    # Only include examples that have taxonomy assignments
    all_keys = sorted(k for k in assignments if k in rep_map)
    missing = [k for k in rep_map if k not in assignments]
    if missing:
        print(f"WARNING: {len(missing)} example(s) have no taxonomy assignment and will be skipped:")
        for k in missing:
            print(f"  {k}")

    train_keys, test_keys = _iterative_stratify(all_keys, assignments, args.test_size)

    _coverage(train_keys, assignments, "Train")
    _coverage(test_keys, assignments, "Test")

    # Expand to (example, label) pairs
    train_instances = list(_expand(train_keys, assignments, rep_map))
    test_instances = list(_expand(test_keys, assignments, rep_map))

    # Write folders
    train_dir = _OUT_ROOT / "Train"
    test_dir = _OUT_ROOT / "Test"
    train_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)

    train_records = _write_instances(train_instances, train_dir, categories, counter_start=0)
    test_records = _write_instances(test_instances, test_dir, categories, counter_start=0)

    # Summary
    summary = {
        "n_unique_train": len(train_keys),
        "n_unique_test": len(test_keys),
        "n_train_instances": len(train_records),
        "n_test_instances": len(test_records),
        "train_keys": train_keys,
        "test_keys": test_keys,
        "train": train_records,
        "test": test_records,
    }
    (_OUT_ROOT / "split_summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\nWrote {len(train_records)} train instances → RevisionFineTuning/Train/")
    print(f"Wrote {len(test_records)} test instances  → RevisionFineTuning/Test/")
    print(f"Saved split_summary.json")


if __name__ == "__main__":
    main()
