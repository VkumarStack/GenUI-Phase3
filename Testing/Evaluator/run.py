"""
Run the evaluator model over the EvaluatorModelDataset and compute binary
PASS/FAIL accuracy against the ground-truth labels in RubricEvaluation.json.

Raw per-example outputs and metrics are saved to Results/<run-name>.json.

Usage:
    # Gemini baseline
    python Testing/Evaluator/run.py --backend gemini

    # Override model
    python Testing/Evaluator/run.py --backend gemini --model gemini-2.5-pro-preview

    # Resume an interrupted run
    python Testing/Evaluator/run.py --backend gemini --resume

    # Rerun only the wrong examples from a previous run
    python Testing/Evaluator/run.py --rerun-failed Testing/Evaluator/Results/gemini.json

    # Custom dataset path
    python Testing/Evaluator/run.py --dataset Datasets/EvaluatorModelDataset
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
sys.path.insert(0, str(_ROOT / "Evaluator"))

from backends import get_backend
from step2 import _run_one

_DATASET     = _ROOT / "Datasets" / "EvaluatorModelDataset"
_RESULTS_DIR = Path(__file__).parent / "Results"
_VERDICTS    = ["PASS", "FAIL"]


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------

def _ground_truth(folder: Path) -> str | None:
    """Return PASS or FAIL from RubricEvaluation.json, or None if missing."""
    rubric_file = folder / "RubricEvaluation.json"
    if not rubric_file.exists():
        return None
    rubric = json.loads(rubric_file.read_text())
    verdict = rubric.get("overallEvaluation", "").strip().upper()
    return verdict if verdict in _VERDICTS else None


def _ground_truth_criteria(folder: Path) -> dict:
    """Return the rubric criteria dict from RubricEvaluation.json (uppercased values)."""
    rubric_file = folder / "RubricEvaluation.json"
    if not rubric_file.exists():
        return {}
    rubric = json.loads(rubric_file.read_text())
    raw = rubric.get("criteria", {})
    return {k: v.upper() for k, v in raw.items()}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _compute_metrics(examples: list[dict]) -> dict:
    """Binary PASS/FAIL accuracy, precision, recall, F1 per class."""
    scored = [e for e in examples if e.get("ground_truth") and e.get("predicted")]
    if not scored:
        return {}

    total   = len(scored)
    correct = sum(1 for e in scored if e["ground_truth"] == e["predicted"])

    conf: dict[str, dict[str, int]] = {v: {p: 0 for p in _VERDICTS} for v in _VERDICTS}
    for e in scored:
        gt, pred = e["ground_truth"], e["predicted"]
        if gt in conf and pred in conf:
            conf[gt][pred] += 1

    per_class = {}
    f1_scores = []
    for v in _VERDICTS:
        tp = conf[v][v]
        fp = sum(conf[r][v] for r in _VERDICTS if r != v)
        fn = sum(conf[v][p] for p in _VERDICTS if p != v)
        support = tp + fn

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1        = (2 * precision * recall / (precision + recall)
                     if (precision + recall) > 0 else 0.0)
        f1_scores.append(f1)

        per_class[v] = {
            "precision": round(precision, 4),
            "recall":    round(recall,    4),
            "f1":        round(f1,        4),
            "support":   support,
        }

    return {
        "n_scored":          total,
        "n_no_prediction":   len(examples) - total,
        "accuracy":          round(correct / total, 4),
        "macro_f1":          round(sum(f1_scores) / len(f1_scores), 4),
        "per_class":         per_class,
        "confusion_matrix":  conf,
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _print_metrics(metrics: dict) -> None:
    if not metrics:
        print("No scored examples — cannot compute metrics.")
        return

    n = metrics["n_scored"]
    print(f"\n{'─'*50}")
    print(f"  Examples scored:  {n}  (+{metrics['n_no_prediction']} unpredictable)")
    print(f"  Accuracy:         {metrics['accuracy']:.1%}")
    print(f"  Macro F1:         {metrics['macro_f1']:.4f}")
    print()
    print(f"  {'Class':<8}  {'Prec':>6}  {'Rec':>6}  {'F1':>6}  {'Support':>7}")
    print(f"  {'─'*8}  {'─'*6}  {'─'*6}  {'─'*6}  {'─'*7}")
    for v in _VERDICTS:
        pc = metrics["per_class"][v]
        print(f"  {v:<8}  {pc['precision']:>6.3f}  {pc['recall']:>6.3f}"
              f"  {pc['f1']:>6.3f}  {pc['support']:>7}")

    print(f"\n  Confusion matrix (rows=actual, cols=predicted):")
    header = f"  {'':10}" + "".join(f"  {v:>8}" for v in _VERDICTS)
    print(header)
    for actual in _VERDICTS:
        row = f"  {actual:<10}" + "".join(
            f"  {metrics['confusion_matrix'][actual][pred]:>8}"
            for pred in _VERDICTS
        )
        print(row)
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _default_run_name(backend_name: str, model_attr: str | None) -> str:
    if model_attr:
        m = re.search(r"/endpoints/(\d+)$", model_attr)
        return m.group(1) if m else re.sub(r"[/:]", "_", model_attr)
    return backend_name


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate a model on EvaluatorModelDataset with binary PASS/FAIL metrics."
    )
    parser.add_argument("--backend", default="gemini",
                        choices=["gemini", "vertexai", "anthropic", "openai"],
                        help="Model backend (default: gemini).")
    parser.add_argument("--model", default=None,
                        help="Override model/endpoint (optional).")
    parser.add_argument("--dataset", default=str(_DATASET), metavar="PATH",
                        help=f"EvaluatorModelDataset directory (default: {_DATASET}).")
    parser.add_argument("--run-name", default=None, metavar="NAME",
                        help="Name for this run (used as output filename). "
                             "Defaults to model name + ablation suffix.")
    parser.add_argument("--no-step1", action="store_true",
                        help="Ablation: skip Step 1 code analysis and pass the raw HTML diff "
                             "directly to Step 2. Appends '-no_step1' to the run name.")
    parser.add_argument("--resume", action="store_true",
                        help="Skip examples already present in the results file.")
    parser.add_argument("--rerun-failed", metavar="RESULTS_JSON",
                        help="Load a previous results file and rerun only the examples "
                             "where ground_truth != predicted (the wrong ones).")
    args = parser.parse_args()

    dataset = Path(args.dataset)
    if not dataset.exists():
        raise SystemExit(f"Dataset not found: {dataset}")

    backend    = get_backend(args.backend, args.model)
    model_attr = getattr(backend, "model", None)
    base_name  = _default_run_name(args.backend, model_attr)
    ablation_suffix = "-no_step1" if args.no_step1 else ""
    if args.run_name:
        run_name = args.run_name
    elif args.rerun_failed:
        source_stem = Path(args.rerun_failed).stem
        run_name = f"{source_stem}-rerun{ablation_suffix}"
    else:
        run_name = f"{base_name}{ablation_suffix}"

    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path  = _RESULTS_DIR / f"{run_name}.json"
    example_dirs = sorted(d for d in dataset.iterdir() if d.is_dir())

    # --rerun-failed: restrict to the wrong examples from a previous run
    rerun_only: set[str] | None = None
    if args.rerun_failed:
        prev = json.loads(Path(args.rerun_failed).read_text())
        rerun_only = {
            e["folder"] for e in prev.get("examples", [])
            if e.get("ground_truth") != e.get("predicted")
        }
        print(f"Rerunning {len(rerun_only)} failed examples from {args.rerun_failed}")

    existing: dict[str, dict] = {}
    if args.resume and output_path.exists():
        saved    = json.loads(output_path.read_text())
        existing = {e["folder"]: e for e in saved.get("examples", [])}
        print(f"Resuming: {len(existing)} done, "
              f"{len(example_dirs) - len(existing)} remaining")

    print(f"Backend:  {args.backend}  |  Model: {model_attr or '—'}")
    print(f"Dataset:  {dataset}  ({len(example_dirs)} examples)")
    print(f"Output:      {output_path.relative_to(_ROOT)}")
    print()

    examples: list[dict] = list(existing.values())
    done_folders = set(existing)
    n = len(example_dirs)

    for i, folder in enumerate(example_dirs, 1):
        if folder.name in done_folders:
            continue
        if rerun_only is not None and folder.name not in rerun_only:
            continue

        gt             = _ground_truth(folder)
        gt_criteria    = _ground_truth_criteria(folder)
        print(f"  [{i:>3}/{n}] {folder.name}  (truth: {gt or '?'}) ... ",
              end="", flush=True)

        try:
            result = _run_one(folder, backend, no_step1=args.no_step1)
            if "error" in result:
                print(f"SKIP — {result['error']}")
                examples.append({
                    "folder":        folder.name,
                    "ground_truth":  gt,
                    "gt_criteria":   gt_criteria,
                    "predicted":     None,
                    "pred_criteria": None,
                    "comment":       None,
                    "response":      None,
                    "error":         result["error"],
                })
            else:
                pred  = result["overall"]
                match = "✓" if pred == gt else "✗"
                print(f"{pred}  {match}")
                examples.append({
                    "folder":        folder.name,
                    "ground_truth":  gt,
                    "gt_criteria":   gt_criteria,
                    "predicted":     pred,
                    "pred_criteria": result.get("criteria"),
                    "comment":       result.get("comment"),
                    "response":      result.get("response"),
                })
        except Exception as e:
            print(f"ERROR: {e}")
            examples.append({
                "folder":        folder.name,
                "ground_truth":  gt,
                "gt_criteria":   gt_criteria,
                "predicted":     None,
                "pred_criteria": None,
                "comment":       None,
                "response":      None,
                "error":         str(e),
            })

        output_path.write_text(json.dumps({
            "run_name":    run_name,
            "backend":     args.backend,
            "model":       model_attr,
            "dataset":     str(dataset),
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "examples":    examples,
        }, indent=2))

    metrics = _compute_metrics(examples)
    _print_metrics(metrics)

    output_path.write_text(json.dumps({
        "run_name":  run_name,
        "backend":   args.backend,
        "model":     model_attr,
        "dataset":   str(dataset),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "examples":  examples,
        "metrics":   metrics,
    }, indent=2))

    print(f"Results saved to {output_path.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
