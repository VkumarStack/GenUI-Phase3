"""
Stratified train/test split for the EvaluatorModelDataset.

Grouping:
  All model variants of the same Participant_X_CaseStudy-Y.Z stay in the same
  split to prevent data leakage (e.g. CLAUDE/GEMINI/OPENAI for the same task).

Stratification:
  Binary PASS/FAIL balance only (from RubricEvaluation.json, majority per group).
  Target: 70% train / 30% test.

Difficult-case handling:
  Loads a previous full-pipeline evaluator run JSON to find groups where the
  model was wrong. A configurable fraction of those groups is guaranteed in the
  training set before the stratified split runs on the remainder — ensuring the
  model sees the hardest cases during fine-tuning.

Output:
  - Datasets/EvaluatorModelDataset/split_manifest.json
  - Datasets/EvaluatorModelDataset/Train/  (symlinks → flat dataset folders)
  - Datasets/EvaluatorModelDataset/Test/   (symlinks → flat dataset folders)

Running:
    python DatasetBuilder/EvaluatorModel/split.py
    python DatasetBuilder/EvaluatorModel/split.py --test-frac 0.30 --difficult-train-frac 0.50 --difficult-test-frac 0.25
    python DatasetBuilder/EvaluatorModel/split.py \\
        --difficult-results Testing/Evaluator/Results/gemini-2.5-pro.json
    python DatasetBuilder/EvaluatorModel/split.py --seed 42 --dry-run
"""

import argparse
import json
import os
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

_ROOT    = Path(__file__).parent.parent.parent
_DATASET = _ROOT / "Datasets" / "EvaluatorModelDataset"
_DEFAULT_DIFFICULT = _ROOT / "Testing" / "Evaluator" / "Results" / "gemini-2.5-pro.json"
_MANIFEST_FILE     = _DATASET / "split_manifest.json"
_MODEL_SUFFIX      = re.compile(r"-(CLAUDE|GEMINI|OPENAI)$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _group_key(folder_name: str) -> str:
    return _MODEL_SUFFIX.sub("", folder_name)


def _load_label(folder: Path) -> str | None:
    """PASS or FAIL from RubricEvaluation.json, uppercased."""
    rubric = folder / "RubricEvaluation.json"
    if not rubric.exists():
        return None
    data = json.loads(rubric.read_text())
    v = data.get("overallEvaluation", "").strip().upper()
    return v if v in ("PASS", "FAIL") else None


def _group_label(folders: list[Path]) -> str | None:
    """Majority PASS/FAIL across all variants in a group."""
    labels = [_load_label(f) for f in folders]
    labels = [l for l in labels if l]
    if not labels:
        return None
    return Counter(labels).most_common(1)[0][0]


def _load_difficult_groups(results_path: Path, all_groups: set[str]) -> set[str]:
    """Groups (stripped key) where any variant was predicted wrong."""
    if not results_path.exists():
        print(f"  Note: difficult-results file not found: {results_path}")
        return set()
    data = json.loads(results_path.read_text())
    wrong_folders = {
        e["folder"] for e in data.get("examples", [])
        if e.get("ground_truth") and e.get("predicted")
        and e["ground_truth"] != e["predicted"]
    }
    wrong_groups = {_group_key(f) for f in wrong_folders} & all_groups
    return wrong_groups


def _stratified_split(groups: list[str], label_map: dict[str, str],
                      test_frac: float, rng: random.Random) -> tuple[list[str], list[str]]:
    """Simple proportional stratified split by PASS/FAIL label."""
    pass_groups = [g for g in groups if label_map.get(g) == "PASS"]
    fail_groups = [g for g in groups if label_map.get(g) == "FAIL"]

    rng.shuffle(pass_groups)
    rng.shuffle(fail_groups)

    n_test_pass = round(len(pass_groups) * test_frac)
    n_test_fail = round(len(fail_groups) * test_frac)

    test  = pass_groups[:n_test_pass] + fail_groups[:n_test_fail]
    train = pass_groups[n_test_pass:] + fail_groups[n_test_fail:]
    return train, test


def _make_symlinks(split_dir: Path, folders: list[Path], dry_run: bool) -> None:
    """Create symlinks in split_dir pointing back to the flat dataset folders."""
    if dry_run:
        return
    split_dir.mkdir(parents=True, exist_ok=True)
    # Remove stale symlinks
    for entry in split_dir.iterdir():
        if entry.is_symlink():
            entry.unlink()
    for folder in folders:
        link = split_dir / folder.name
        target = Path("..") / folder.name   # relative to split_dir
        if not link.exists():
            link.symlink_to(target)


def _print_split_stats(name: str, groups: list[str], label_map: dict[str, str],
                       group_folders: dict[str, list[str]], difficult: set[str]) -> None:
    labels   = [label_map.get(g, "?") for g in groups]
    n_pass   = labels.count("PASS")
    n_fail   = labels.count("FAIL")
    n_diff   = sum(1 for g in groups if g in difficult)
    n_folder = sum(len(group_folders[g]) for g in groups)
    print(f"\n  {name}: {len(groups)} groups  ({n_folder} folders)")
    print(f"    PASS: {n_pass}  FAIL: {n_fail}  difficult: {n_diff}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Stratified train/test split for EvaluatorModelDataset."
    )
    parser.add_argument("--dataset", default=str(_DATASET), metavar="PATH",
                        help=f"EvaluatorModelDataset directory (default: {_DATASET}).")
    parser.add_argument("--test-frac", type=float, default=0.30, metavar="F",
                        help="Fraction of groups reserved for test (default: 0.30).")
    parser.add_argument("--difficult-results", default=str(_DEFAULT_DIFFICULT), metavar="PATH",
                        help="Evaluator results JSON used to identify difficult cases.")
    parser.add_argument("--difficult-train-frac", type=float, default=0.50, metavar="F",
                        help="Fraction of difficult groups guaranteed in training (default: 0.50).")
    parser.add_argument("--difficult-test-frac", type=float, default=0.25, metavar="F",
                        help="Fraction of difficult groups guaranteed in test (default: 0.25).")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the split without writing any files.")
    args = parser.parse_args()

    dataset = Path(args.dataset)
    rng     = random.Random(args.seed)

    # -- Build groups ---------------------------------------------------------
    group_folders: dict[str, list[Path]] = defaultdict(list)
    for folder in sorted(dataset.iterdir()):
        if not folder.is_dir() or folder.name in ("Train", "Test"):
            continue
        group_folders[_group_key(folder.name)].append(folder)

    all_groups = set(group_folders)
    label_map: dict[str, str] = {
        g: lbl
        for g, folders in group_folders.items()
        if (lbl := _group_label(folders)) is not None
    }

    unlabeled = [g for g in all_groups if g not in label_map]
    if unlabeled:
        print(f"Warning: {len(unlabeled)} group(s) have no label — skipping.")

    labeled_groups = sorted(label_map)

    # -- Identify difficult groups -------------------------------------------
    difficult = _load_difficult_groups(Path(args.difficult_results), all_groups)
    n_force_train = round(len(difficult) * args.difficult_train_frac)
    n_force_test  = round(len(difficult) * args.difficult_test_frac)
    # Clamp so forced sets don't exceed the total number of difficult groups
    n_force_train = min(n_force_train, max(0, len(difficult) - n_force_test))

    difficult_list = sorted(difficult)
    rng.shuffle(difficult_list)
    forced_train = set(difficult_list[:n_force_train])
    forced_test  = set(difficult_list[n_force_train:n_force_train + n_force_test])
    difficult_pool = set(difficult_list[n_force_train + n_force_test:])

    print(f"\nDataset:   {dataset}  ({len(labeled_groups)} labeled groups)")
    print(f"Difficult: {len(difficult)} groups identified  "
          f"→  {len(forced_train)} forced-train,  {len(forced_test)} forced-test,  "
          f"{len(difficult_pool)} in pool")

    # -- Stratified split on remaining pool -----------------------------------
    pool = [g for g in labeled_groups if g not in forced_train and g not in forced_test]
    rng.shuffle(pool)

    pool_train, pool_test = _stratified_split(pool, label_map, args.test_frac, rng)

    train_groups = sorted(set(pool_train) | forced_train)
    test_groups  = sorted(set(pool_test) | forced_test)

    _print_split_stats("Train", train_groups, label_map, group_folders, difficult)
    _print_split_stats("Test",  test_groups,  label_map, group_folders, difficult)

    total_folders = sum(len(group_folders[g]) for g in train_groups + test_groups)
    print(f"\n  Total folders: {total_folders}")

    if args.dry_run:
        print("\nDry run — no files written.")
        return

    # -- Write symlinks -------------------------------------------------------
    train_folders = [f for g in train_groups for f in group_folders[g]]
    test_folders  = [f for g in test_groups  for f in group_folders[g]]

    _make_symlinks(dataset / "Train", train_folders, dry_run=False)
    _make_symlinks(dataset / "Test",  test_folders,  dry_run=False)

    print(f"\n  Symlinks written:")
    print(f"    {dataset / 'Train'}  ({len(train_folders)} links)")
    print(f"    {dataset / 'Test'}   ({len(test_folders)} links)")

    # -- Write manifest -------------------------------------------------------
    manifest = {
        "seed":                   args.seed,
        "test_frac":              args.test_frac,
        "difficult_results":      args.difficult_results,
        "difficult_train_frac":   args.difficult_train_frac,
        "difficult_test_frac":    args.difficult_test_frac,
        "n_difficult_groups":     len(difficult),
        "n_forced_train":         len(forced_train),
        "n_forced_test":          len(forced_test),
        "train": {
            "groups":  train_groups,
            "folders": [f.name for f in train_folders],
            "n_pass":  sum(1 for g in train_groups if label_map[g] == "PASS"),
            "n_fail":  sum(1 for g in train_groups if label_map[g] == "FAIL"),
            "n_difficult": sum(1 for g in train_groups if g in difficult),
        },
        "test": {
            "groups":  test_groups,
            "folders": [f.name for f in test_folders],
            "n_pass":  sum(1 for g in test_groups if label_map[g] == "PASS"),
            "n_fail":  sum(1 for g in test_groups if label_map[g] == "FAIL"),
            "n_difficult": sum(1 for g in test_groups if g in difficult),
        },
    }
    _MANIFEST_FILE.write_text(json.dumps(manifest, indent=2))
    print(f"\n  Manifest: {_MANIFEST_FILE.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
