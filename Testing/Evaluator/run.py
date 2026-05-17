"""
Run the evaluator model over the EvaluatorModelDataset test split and compute
classification metrics against the ground-truth labels.

Each example's predicted verdict is compared to the PASS / PARTIAL / FAIL label
in label.txt. Raw per-example outputs are saved to Results/<run-name>.json.
Metrics (accuracy, per-class precision/recall/F1, macro F1, confusion matrix)
are printed and stored in the same file.

Usage:
    # Gemini baseline
    python Testing/Evaluator/run.py --backend gemini

    # Fine-tuned evaluator on Vertex AI
    python Testing/Evaluator/run.py --backend vertexai --run-name finetuned-v1

    # Resume an interrupted run
    python Testing/Evaluator/run.py --backend gemini --resume

    # Custom test split path
    python Testing/Evaluator/run.py --backend gemini \\
        --dataset Datasets/EvaluatorModelDataset/Test
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

_TEST_DATASET = _ROOT / "Datasets" / "EvaluatorModelDataset" / "Test"
_RESULTS_DIR  = Path(__file__).parent / "Results"
_VERDICTS     = ["PASS", "PARTIAL", "FAIL"]


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------

def _ground_truth(folder: Path) -> str | None:
    """Return the verdict from label.txt (first non-empty line, uppercased)."""
    label_file = folder / "label.txt"
    if not label_file.exists():
        return None
    for line in label_file.read_text().splitlines():
        v = line.strip().upper()
        if v in _VERDICTS:
            return v
    return None


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _compute_metrics(examples: list[dict]) -> dict:
    """Compute accuracy, per-class P/R/F1, macro F1, and confusion matrix."""
    scored = [e for e in examples if e["ground_truth"] and e["predicted"]]
    if not scored:
        return {}

    total   = len(scored)
    correct = sum(1 for e in scored if e["ground_truth"] == e["predicted"])

    # confusion[actual][predicted]
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
        "n_scored":       total,
        "n_no_prediction": len(examples) - total,
        "accuracy":        round(correct / total, 4),
        "macro_f1":        round(sum(f1_scores) / len(f1_scores), 4),
        "per_class":       per_class,
        "confusion_matrix": conf,
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _print_metrics(metrics: dict) -> None:
    if not metrics:
        print("No scored examples — cannot compute metrics.")
        return

    n = metrics["n_scored"]
    print(f"\n{'─'*55}")
    print(f"  Examples scored:  {n}  "
          f"(+{metrics['n_no_prediction']} unpredictable)")
    print(f"  Accuracy:         {metrics['accuracy']:.1%}")
    print(f"  Macro F1:         {metrics['macro_f1']:.4f}")
    print()
    print(f"  {'Class':<10}  {'Prec':>6}  {'Rec':>6}  {'F1':>6}  {'Support':>7}")
    print(f"  {'─'*10}  {'─'*6}  {'─'*6}  {'─'*6}  {'─'*7}")
    for v in _VERDICTS:
        pc = metrics["per_class"][v]
        print(f"  {v:<10}  {pc['precision']:>6.3f}  {pc['recall']:>6.3f}"
              f"  {pc['f1']:>6.3f}  {pc['support']:>7}")

    print(f"\n  Confusion matrix (rows=actual, cols=predicted):")
    header = f"  {'':12}" + "".join(f"  {v:>8}" for v in _VERDICTS)
    print(header)
    for actual in _VERDICTS:
        row = f"  {actual:<12}" + "".join(
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
        # Strip long Vertex AI resource paths down to the endpoint ID
        m = re.search(r"/endpoints/(\d+)$", model_attr)
        return m.group(1) if m else re.sub(r"[/:]", "_", model_attr)
    return backend_name


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate a model on the EvaluatorModelDataset test split."
    )
    parser.add_argument("--backend", default="gemini",
                        choices=["gemini", "vertexai", "anthropic", "openai"],
                        help="Model backend (default: gemini). Use 'vertexai' for the "
                             "fine-tuned evaluator (reads VERTEXAI_EVALUATOR_ENDPOINT_ID).")
    parser.add_argument("--model", default=None,
                        help="Override model/endpoint (optional).")
    parser.add_argument("--dataset", default=str(_TEST_DATASET), metavar="PATH",
                        help=f"Test split directory (default: {_TEST_DATASET}).")
    parser.add_argument("--run-name", default=None, metavar="NAME",
                        help="Name for this run — used as the output filename. "
                             "Defaults to the model name or endpoint ID.")
    parser.add_argument("--resume", action="store_true",
                        help="Skip examples already present in the results file.")
    args = parser.parse_args()

    dataset = Path(args.dataset)
    if not dataset.exists():
        raise SystemExit(f"Dataset not found: {dataset}")

    backend = get_backend(args.backend, args.model,
                          endpoint_env_var="VERTEXAI_EVALUATOR_ENDPOINT_ID")

    model_attr = getattr(backend, "model", None)
    run_name   = args.run_name or _default_run_name(args.backend, model_attr)

    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = _RESULTS_DIR / f"{run_name}.json"

    example_dirs = sorted(d for d in dataset.iterdir() if d.is_dir())

    # Load previous results if resuming
    existing: dict[str, dict] = {}
    if args.resume and output_path.exists():
        saved = json.loads(output_path.read_text())
        existing = {e["folder"]: e for e in saved.get("examples", [])}
        print(f"Resuming: {len(existing)} done, "
              f"{len(example_dirs) - len(existing)} remaining")

    print(f"Backend:  {args.backend}  |  Model: {model_attr or '—'}")
    print(f"Dataset:  {dataset}  ({len(example_dirs)} examples)")
    print(f"Output:   {output_path.relative_to(_ROOT)}")
    print()

    examples: list[dict] = list(existing.values())
    done_folders = set(existing)
    n = len(example_dirs)

    for i, folder in enumerate(example_dirs, 1):
        if folder.name in done_folders:
            continue

        gt = _ground_truth(folder)
        print(f"  [{i:>3}/{n}] {folder.name}  (truth: {gt or '?'}) ... ",
              end="", flush=True)

        try:
            result = _run_one(folder, backend)
            if "error" in result:
                print(f"SKIP — {result['error']}")
                examples.append({
                    "folder":       folder.name,
                    "ground_truth": gt,
                    "predicted":    None,
                    "response":     None,
                    "error":        result["error"],
                })
            else:
                pred = result["verdict"]
                match = "✓" if pred == gt else "✗"
                print(f"{pred}  {match}")
                examples.append({
                    "folder":       folder.name,
                    "ground_truth": gt,
                    "predicted":    pred,
                    "response":     result["response"],
                })
        except Exception as e:
            print(f"ERROR: {e}")
            examples.append({
                "folder":       folder.name,
                "ground_truth": gt,
                "predicted":    None,
                "response":     None,
                "error":        str(e),
            })

        # Write after each example so a partial run is always recoverable
        output_path.write_text(json.dumps({
            "run_name":  run_name,
            "backend":   args.backend,
            "model":     model_attr,
            "dataset":   str(dataset),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "examples":  examples,
        }, indent=2))

    metrics = _compute_metrics(examples)
    _print_metrics(metrics)

    # Write final file with metrics included
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
