"""
Temporary script: format a results JSON into markdown for manual inspection.

Examples are ordered wrong-first (ground truth != predicted), then correct ones.
Ground truth reasoning is fetched from label.txt in the test dataset.

Usage:
    python Testing/Evaluator/inspect_results.py Testing/Evaluator/Results/finetuned-v1.json
    python Testing/Evaluator/inspect_results.py Testing/Evaluator/Results/finetuned-v1.json > review.md
"""

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
_TEST_DIR = _ROOT / "Datasets" / "EvaluatorModelDataset" / "Test"


def _label_text(folder_name: str) -> str:
    p = _TEST_DIR / folder_name / "label.txt"
    return p.read_text().strip() if p.exists() else "(label.txt not found)"


def _task_text(folder_name: str) -> str:
    p = _TEST_DIR / folder_name / "task.txt"
    return p.read_text().strip() if p.exists() else "(task.txt not found)"


def _render_example(ex: dict, idx: int, wrong: bool) -> str:
    folder      = ex["folder"]
    gt          = ex.get("ground_truth") or "?"
    pred        = ex.get("predicted")    or "?"
    response    = ex.get("response")     or "(no response)"
    label_full  = _label_text(folder)
    task        = _task_text(folder)

    status = "WRONG" if wrong else "correct"
    verdict_line = f"`{gt}` → predicted `{pred}`" if wrong else f"`{pred}` ✓"

    img_base = f"../../../Datasets/EvaluatorModelDataset/Test/{folder}"

    lines = [
        f"## {idx}. {folder}  —  {status}",
        "",
        f"**Verdict:** {verdict_line}",
        "",
        "**Task**",
        "",
        task,
        "",
        "| Before | After |",
        "|:---:|:---:|",
        f"| ![Before]({img_base}/before_screenshot.png) | ![After]({img_base}/after_screenshot.png) |",
        "",
        "**Ground truth reasoning** *(from label.txt)*",
        "",
        label_full,
        "",
        "**Model response**",
        "",
        response,
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python inspect_results.py <results.json>")

    results_path = Path(sys.argv[1])
    if not results_path.exists():
        raise SystemExit(f"File not found: {results_path}")

    data = json.loads(results_path.read_text())
    examples  = data.get("examples", [])
    metrics   = data.get("metrics", {})
    run_name  = data.get("run_name", results_path.stem)
    model     = data.get("model") or data.get("backend", "")

    wrong   = [e for e in examples if e.get("ground_truth") != e.get("predicted")]
    correct = [e for e in examples if e.get("ground_truth") == e.get("predicted")]
    ordered = wrong + correct

    # Header
    parts = [
        f"# Evaluator Results: {run_name}",
        "",
        f"**Model:** {model}  |  **Dataset:** {data.get('dataset', '?')}",
        f"**Timestamp:** {data.get('timestamp', '?')}",
        "",
    ]

    if metrics:
        parts += [
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|---|---|",
            f"| Accuracy | {metrics.get('accuracy', '?'):.1%} |",
            f"| Macro F1 | {metrics.get('macro_f1', '?'):.4f} |",
            f"| Wrong / Total | {len(wrong)} / {len(examples)} |",
            "",
        ]
        pc = metrics.get("per_class", {})
        if pc:
            parts += [
                "| Class | Precision | Recall | F1 | Support |",
                "|---|---|---|---|---|",
            ]
            for v in ["PASS", "PARTIAL", "FAIL"]:
                if v in pc:
                    c = pc[v]
                    parts.append(
                        f"| {v} | {c['precision']:.3f} | {c['recall']:.3f} "
                        f"| {c['f1']:.3f} | {c['support']} |"
                    )
            parts.append("")

        cm = metrics.get("confusion_matrix", {})
        if cm:
            verdicts = ["PASS", "PARTIAL", "FAIL"]
            parts += [
                "**Confusion matrix** (rows = actual, cols = predicted)",
                "",
                "| | PASS | PARTIAL | FAIL |",
                "|---|---|---|---|",
            ]
            for actual in verdicts:
                row = cm.get(actual, {})
                parts.append(
                    f"| **{actual}** | {row.get('PASS',0)} "
                    f"| {row.get('PARTIAL',0)} | {row.get('FAIL',0)} |"
                )
            parts.append("")

    parts += [
        f"---",
        "",
        f"*{len(wrong)} wrong first, then {len(correct)} correct.*",
        "",
    ]

    # Examples
    for i, ex in enumerate(ordered, 1):
        is_wrong = ex.get("ground_truth") != ex.get("predicted")
        parts.append(_render_example(ex, i, is_wrong))

    print("\n".join(parts))


if __name__ == "__main__":
    main()
