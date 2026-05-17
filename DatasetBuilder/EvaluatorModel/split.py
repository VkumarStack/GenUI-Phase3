"""
Stratified train/test split for evaluation fine-tuning.

Split unit: Participant_X_CaseStudy-Y.Z groups — all model variants of the same
task stay in the same split to prevent data leakage.

Stratification: iterative multi-label stratification over groups using verdict
types (PASS / PARTIAL / FAIL) as labels, so the verdict distribution is
proportional across splits.

Target: ~20% of groups → test, remainder → train.

Each output example folder contains:
  before_screenshot.png  — Before/screenshot.png
  after_screenshot.png   — After/screenshot.png
  before.html            — Before/index.html  (reference; not used for training)
  after.html             — After/index.html   (reference; not used for training)
  dom_diff.txt           — semantic DOM diff (must run cache_dom_diffs.py first)
  step1_spec.txt         — expected-change spec (must run fill_step1.py first)
  task.txt               — revision task text
  label.txt              — expert verdict + reasons (from Output.txt)
  meta.json              — provenance (source folder name, group key)

Running:
    python DatasetBuilder/EvaluatorModel/split.py
    python DatasetBuilder/EvaluatorModel/split.py --test-groups 11
    python DatasetBuilder/EvaluatorModel/split.py --dataset path/to/Datasets/RawDataset
"""

import argparse
import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
_DATASET = _ROOT / "Datasets" / "RawDataset"
_OUT_ROOT = _ROOT / "Datasets" / "EvaluatorModelDataset"
_SUMMARY_FILE = Path(__file__).parent / "split_summary.json"
_MODEL_SUFFIX = re.compile(r"-(CLAUDE|GEMINI|OPENAI)$")


# ---------------------------------------------------------------------------
# Iterative multi-label stratification (same algorithm as RevisionGeneratorModel)
# ---------------------------------------------------------------------------

def _iterative_stratify(keys: list[str], labels_map: dict[str, list[str]], n_test: int):
    n_total = len(keys)
    n_train = n_total - n_test
    label_totals = Counter(l for k in keys for l in labels_map[k])
    desired_test = {l: max(1, round(c * n_test / n_total)) for l, c in label_totals.items()}
    desired_train = {l: max(1, round(c * n_train / n_total)) for l, c in label_totals.items()}

    remaining = list(keys)
    test, train = [], []

    while remaining:
        pool_counts = Counter(l for k in remaining for l in labels_map[k])
        rarest = min(pool_counts, key=pool_counts.get)
        candidates = [k for k in remaining if rarest in labels_map[k]]
        chosen = max(candidates, key=lambda k: len(labels_map[k]))
        remaining.remove(chosen)

        test_have = sum(1 for k in test if rarest in labels_map[k])
        train_have = sum(1 for k in train if rarest in labels_map[k])
        test_need = desired_test[rarest] - test_have
        train_need = desired_train[rarest] - train_have

        if test_need > train_need:
            test.append(chosen)
        elif train_need > test_need:
            train.append(chosen)
        else:
            test.append(chosen) if len(test) < n_test else train.append(chosen)

    return train, test


# ---------------------------------------------------------------------------
# File copying
# ---------------------------------------------------------------------------

def _copy_example(src: Path, dest: Path) -> bool:
    """Copy all needed files from a RawDataset folder into dest."""
    dest.mkdir(parents=True, exist_ok=True)

    copies = [
        (src / "Before" / "screenshot.png", dest / "before_screenshot.png"),
        (src / "After"  / "screenshot.png", dest / "after_screenshot.png"),
        (src / "Before" / "index.html",     dest / "before.html"),
        (src / "After"  / "index.html",     dest / "after.html"),
        (src / "Task.txt",                  dest / "task.txt"),
        (src / "Output.txt",                dest / "label.txt"),
    ]
    for src_file, dest_file in copies:
        if src_file.exists():
            shutil.copy2(src_file, dest_file)

    for filename, warning in [
        ("dom_diff.txt",   "(not computed — run cache_dom_diffs.py)"),
        ("step1_spec.txt", "(not computed — run fill_step1.py)"),
    ]:
        src_file = src / filename
        if src_file.exists():
            shutil.copy2(src_file, dest / filename)
        else:
            (dest / filename).write_text(warning)

    return True


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------

def _coverage(groups: list[str], labels_map: dict[str, list[str]], folders_map: dict[str, list[str]], name: str):
    folder_verdicts = Counter(v for k in groups for v in labels_map[k])
    n_folders = sum(len(folders_map[k]) for k in groups)
    print(f"\n{name} ({len(groups)} groups, {n_folders} folders):")
    for verdict in ("PASS", "PARTIAL", "FAIL"):
        print(f"  {verdict}: {folder_verdicts.get(verdict, 0)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Stratified train/test split for evaluation fine-tuning.")
    parser.add_argument("--test-groups", type=int, default=11, metavar="N",
                        help="Number of unique case study groups to reserve for test (default: 11).")
    parser.add_argument("--dataset", default=str(_DATASET), metavar="PATH")
    args = parser.parse_args()

    dataset = Path(args.dataset)

    # Build group → folders map and verdict labels
    groups: dict[str, list[Path]] = defaultdict(list)
    for folder in sorted(dataset.iterdir()):
        if not folder.is_dir():
            continue
        key = _MODEL_SUFFIX.sub("", folder.name)
        groups[key].append(folder)

    # Per-group label set = all verdict types present in that group's folders
    labels_map: dict[str, list[str]] = {}
    folders_map: dict[str, list[str]] = {}
    for key, folders in groups.items():
        verdicts = set()
        for folder in folders:
            out = folder / "Output.txt"
            if out.exists():
                verdict = out.read_text().strip().splitlines()[0].strip()
                verdicts.add(verdict)
        labels_map[key] = sorted(verdicts)
        folders_map[key] = [f.name for f in folders]

    all_keys = sorted(groups.keys())
    train_keys, test_keys = _iterative_stratify(all_keys, labels_map, args.test_groups)

    _coverage(train_keys, labels_map, folders_map, "Train")
    _coverage(test_keys,  labels_map, folders_map, "Test")

    # Warn if any expected files are missing in the source dataset
    for filename, fixer in [
        ("dom_diff.txt",   "cache_dom_diffs.py"),
        ("step1_spec.txt", "fill_step1.py"),
    ]:
        missing = [
            folder.name
            for key in all_keys
            for folder in groups[key]
            if not (folder / filename).exists()
        ]
        if missing:
            print(f"\nWARNING: {len(missing)} folder(s) have no {filename} — run {fixer} first.")

    # Copy files into Train/ and Test/
    summary = {"train_groups": train_keys, "test_groups": test_keys, "train": [], "test": []}

    for split_name, split_keys in [("Train", train_keys), ("Test", test_keys)]:
        split_dir = _OUT_ROOT / split_name
        idx = 0
        for key in split_keys:
            for folder in sorted(groups[key]):
                dest = split_dir / f"Example-{idx:03d}"
                _copy_example(folder, dest)
                (dest / "meta.json").write_text(json.dumps({
                    "source": folder.name,
                    "group": key,
                }, indent=2))
                record = {"folder": dest.name, "source": folder.name, "group": key}
                summary[split_name.lower()].append(record)
                idx += 1

        print(f"\nWrote {idx} examples → Datasets/EvaluatorModelDataset/{split_name}/")

    _SUMMARY_FILE.write_text(json.dumps(summary, indent=2))
    print(f"Saved split_summary.json")


if __name__ == "__main__":
    main()
