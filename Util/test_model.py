"""
Run a model against a test set and evaluate its performance.

Each example must have an Output.txt containing the ground-truth verdict
(PASS or FAIL on the first non-empty line). The model's response is compared
against this label and results are written to a JSON file.

Usage:
    python Util/test_model.py \\
        --dir Examples/TestExamples \\
        --results results/gemini_base.json

    python Util/test_model.py \\
        --example Examples/TestExamples/task-8.1-claude \\
        --results results/single.json \\
        --backend vertexai

    python Util/test_model.py \\
        --dir Examples/TestExamples \\
        --backend gemini \\
        --model gemini-2.5-pro \\
        --results results/gemini_base.json

    # Ensemble mode (--config implies ensemble; --backend/--model are ignored):
    python Util/test_model.py \\
        --dir Examples/TestExamples \\
        --config Evaluation/ensemble_config.json \\
        --results results/ensemble.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / "Evaluation" / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent / "Evaluation"))
from backends import get_backend
from eval_core import evaluate, parse_verdict
from ensemble_eval import ensemble_evaluate


def _load_ensemble_config(config_path: Path):
    """Parse ensemble config JSON. Returns (worker_backends, aggregator_backend)."""
    cfg = json.loads(config_path.read_text())

    workers = cfg.get("workers")
    if not workers or not isinstance(workers, list):
        raise ValueError("Ensemble config must have a non-empty 'workers' list.")

    agg_cfg = cfg.get("aggregator")
    if not agg_cfg:
        raise ValueError("Ensemble config must have an 'aggregator' entry.")

    worker_backends = []
    for w in workers:
        name = w["backend"]
        model = w.get("model")
        label = f"{name}/{model or 'default'}"
        worker_backends.append((label, get_backend(name, model)))

    aggregator_backend = get_backend(agg_cfg["backend"], agg_cfg.get("model"))
    return worker_backends, aggregator_backend


def load_ground_truth(example_dir: Path) -> str | None:
    """Read the ground-truth verdict from Output.txt. Returns 'PASS', 'FAIL', or None."""
    output_path = example_dir / "Output.txt"
    if not output_path.exists():
        return None
    for line in output_path.read_text().splitlines():
        line = line.strip().upper()
        if line in ("PASS", "FAIL"):
            return line
    return None


def parse_reasoning(response_text: str) -> tuple[str, str]:
    """Extract Code Reasoning and Image Reasoning sections from the model response."""
    code_match  = re.search(r"Code Reasoning:\s*",  response_text, re.IGNORECASE)
    image_match = re.search(r"Image Reasoning:\s*", response_text, re.IGNORECASE)

    if code_match and image_match:
        code_reasoning  = response_text[code_match.end():image_match.start()].strip()
        image_reasoning = response_text[image_match.end():].strip()
    elif code_match:
        code_reasoning  = response_text[code_match.end():].strip()
        image_reasoning = ""
    elif image_match:
        code_reasoning  = ""
        image_reasoning = response_text[image_match.end():].strip()
    else:
        code_reasoning  = ""
        image_reasoning = ""

    return code_reasoning, image_reasoning


def compute_metrics(examples: list[dict]) -> dict:
    """Compute accuracy, precision, recall, F1, and per-class counts."""
    labeled = [e for e in examples if e["ground_truth"] in ("PASS", "FAIL")]
    total   = len(labeled)

    if total == 0:
        return {"error": "No examples with valid ground truth labels."}

    # Treat PASS as the positive class.
    tp = sum(1 for e in labeled if e["ground_truth"] == "PASS" and e["prediction"] == "PASS")
    fp = sum(1 for e in labeled if e["ground_truth"] == "FAIL" and e["prediction"] == "PASS")
    tn = sum(1 for e in labeled if e["ground_truth"] == "FAIL" and e["prediction"] == "FAIL")
    fn = sum(1 for e in labeled if e["ground_truth"] == "PASS" and e["prediction"] == "FAIL")
    unknown = sum(1 for e in labeled if e["prediction"] == "UNKNOWN")

    accuracy  = (tp + tn) / total if total > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return {
        "total":     total,
        "correct":   tp + tn,
        "incorrect": fp + fn,
        "unknown":   unknown,
        "accuracy":  round(accuracy,  4),
        "precision": round(precision, 4),
        "recall":    round(recall,    4),
        "f1":        round(f1,        4),
        "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
    }


def main():
    parser = argparse.ArgumentParser(description="Test a VLM backend against a labeled test set.")

    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--example", metavar="PATH", help="Path to a single example directory.")
    target.add_argument("--dir",     metavar="PATH", help="Path to a directory of examples.")

    parser.add_argument("--results", required=True, metavar="PATH",
                        help="Output JSON file path for results (required).")
    parser.add_argument("--backend", choices=["gemini", "vertexai", "anthropic", "openai", "ollama", "hf"],
                        default="gemini", help="Model backend (default: gemini). Ignored when --config is used.")
    parser.add_argument("--model", default=None,
                        help="Model name override. Omit to use the backend default or env vars. Ignored when --config is used.")
    parser.add_argument("--config", default=None, metavar="PATH",
                        help="Path to ensemble config JSON. When provided, runs ensemble evaluation "
                             "instead of single-model evaluation; --backend and --model are ignored.")
    args = parser.parse_args()

    results_path = Path(args.results)
    results_path.parent.mkdir(parents=True, exist_ok=True)

    if args.config:
        worker_backends, aggregator_backend = _load_ensemble_config(Path(args.config))
        print("Ensemble mode")
        print("Workers:")
        for label, backend in worker_backends:
            print(f"  {label}  (model: {backend.model})")
        print(f"Aggregator: {aggregator_backend.model}")
        use_ensemble = True
        meta_backend = "ensemble"
        meta_model = aggregator_backend.model
    else:
        backend = get_backend(args.backend, args.model)
        print(f"Backend: {args.backend}  |  Model: {backend.model}")
        use_ensemble = False
        meta_backend = args.backend
        meta_model = backend.model

    if args.example:
        example_dirs = [Path(args.example)]
    else:
        example_dirs = sorted(d for d in Path(args.dir).iterdir() if d.is_dir())

    print(f"Examples: {len(example_dirs)}\n")

    examples_output = []
    skipped = 0

    for example_dir in example_dirs:
        ground_truth = load_ground_truth(example_dir)
        if ground_truth is None:
            print(f"  [SKIP] {example_dir.name}: no valid ground truth in Output.txt")
            skipped += 1
            continue

        print(f"  {example_dir.name} (truth: {ground_truth}) ...", end=" ", flush=True)

        try:
            if use_ensemble:
                result = ensemble_evaluate(example_dir, worker_backends, aggregator_backend)
                raw_output = result["aggregator_response"]
                worker_info = [
                    {"worker": w["worker_label"], "verdict": w["verdict"], "response": w["response"]}
                    for w in result["worker_results"]
                ]
            else:
                result = evaluate(example_dir, backend)
                raw_output = result["response"]
                worker_info = None
        except Exception as e:
            print(f"ERROR: {e}")
            entry = {
                "name":            example_dir.name,
                "ground_truth":    ground_truth,
                "prediction":      "ERROR",
                "code_reasoning":  "",
                "image_reasoning": "",
                "raw_output":      str(e),
                "correct":         False,
            }
            if use_ensemble:
                entry["worker_results"] = []
            examples_output.append(entry)
            continue

        code_reasoning, image_reasoning = parse_reasoning(raw_output)

        entry = {
            "name":            example_dir.name,
            "ground_truth":    ground_truth,
            "prediction":      result["verdict"],
            "code_reasoning":  code_reasoning,
            "image_reasoning": image_reasoning,
            "raw_output":      raw_output,
            "correct":         result["verdict"] == ground_truth,
        }
        if use_ensemble:
            entry["worker_results"] = worker_info
        examples_output.append(entry)

        status = "✓" if entry["correct"] else "✗" if entry["prediction"] != "UNKNOWN" else "?"
        print(f"{status}  (predicted: {result['verdict']})")

    metrics = compute_metrics(examples_output)

    output = {
        "meta": {
            "backend": meta_backend,
            "model":   meta_model,
            "total_examples": len(example_dirs),
            "skipped":        skipped,
        },
        "metrics": metrics,
        "examples": examples_output,
    }

    results_path.write_text(json.dumps(output, indent=2))

    print(f"\n{'─'*50}")
    print(f"  Accuracy:  {metrics.get('accuracy',  'N/A')}")
    print(f"  Precision: {metrics.get('precision', 'N/A')}")
    print(f"  Recall:    {metrics.get('recall',    'N/A')}")
    print(f"  F1:        {metrics.get('f1',        'N/A')}")
    print(f"  ({metrics.get('correct', 0)}/{metrics.get('total', 0)} correct"
          f", {metrics.get('unknown', 0)} unknown)")
    print(f"\nResults written to {results_path}")


if __name__ == "__main__":
    main()
