"""
Convert a results JSON file (from test_model.py) to a readable Markdown report.

Usage:
    python Util/results_to_markdown.py Results/ensemble.json
    python Util/results_to_markdown.py Results/ensemble.json --output Results/ensemble.md
"""

import argparse
import json
from pathlib import Path


def verdict_icon(verdict: str, ground_truth: str) -> str:
    if verdict == "ERROR":
        return "⚠️"
    return "✅" if verdict == ground_truth else "❌"


def render_example(ex: dict) -> list[str]:
    gt         = ex.get("ground_truth", "?")
    prediction = ex.get("prediction", "UNKNOWN")
    icon       = verdict_icon(prediction, gt)
    lines      = []

    lines.append(f"## {icon} {ex['name']}")
    lines.append(f"**Ground truth:** {gt} &nbsp;|&nbsp; **Prediction:** {prediction}")
    lines.append("")

    worker_results = ex.get("worker_results")
    if worker_results:
        lines.append("### Aggregator response")
        lines.append("")
        lines.append(ex.get("raw_output", "").strip())
        lines.append("")
        lines.append("### Worker responses")
        lines.append("")
        for w in worker_results:
            lines.append(f"**{w['worker']}** — {w['verdict']}")
            lines.append("")
            lines.append(w.get("response", "").strip())
            lines.append("")
    else:
        lines.append("### Model response")
        lines.append("")
        lines.append(ex.get("raw_output", "").strip())
        lines.append("")

    lines.append("---")
    lines.append("")
    return lines


def render_report(data: dict) -> str:
    meta    = data.get("meta", {})
    metrics = data.get("metrics", {})
    examples = data.get("examples", [])

    lines = []

    lines.append("# Evaluation Report")
    lines.append("")
    lines.append(f"**Backend:** {meta.get('backend', '?')}  ")
    lines.append(f"**Model:** {meta.get('model', '?')}  ")
    lines.append(f"**Examples:** {meta.get('total_examples', '?')}  ")
    if meta.get("skipped"):
        lines.append(f"**Skipped:** {meta['skipped']}  ")
    lines.append("")

    if metrics and "error" not in metrics:
        cm = metrics.get("confusion_matrix", {})
        lines.append("## Metrics")
        lines.append("")
        lines.append(f"| Accuracy | Precision | Recall | F1 |")
        lines.append(f"|---|---|---|---|")
        lines.append(f"| {metrics.get('accuracy')} | {metrics.get('precision')} | {metrics.get('recall')} | {metrics.get('f1')} |")
        lines.append("")
        lines.append(f"**Correct:** {metrics.get('correct')}/{metrics.get('total')}  ")
        if metrics.get("unknown"):
            lines.append(f"**Unknown:** {metrics['unknown']}  ")
        if cm:
            lines.append(f"**Confusion matrix:** TP={cm.get('tp')} FP={cm.get('fp')} TN={cm.get('tn')} FN={cm.get('fn')}  ")
        lines.append("")

    lines.append("---")
    lines.append("")

    incorrect = [e for e in examples if not e.get("correct", True)]
    correct   = [e for e in examples if e.get("correct", False)]

    if incorrect:
        lines.append("# Incorrect Predictions")
        lines.append("")
        for ex in incorrect:
            lines.extend(render_example(ex))

    if correct:
        lines.append("# Correct Predictions")
        lines.append("")
        for ex in correct:
            lines.extend(render_example(ex))

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Convert a results JSON to Markdown.")
    parser.add_argument("input", metavar="INPUT", help="Path to the results JSON file.")
    parser.add_argument("--output", metavar="PATH", default=None,
                        help="Output Markdown file path. Defaults to <input>.md.")
    args = parser.parse_args()

    input_path  = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.with_suffix(".md")

    data = json.loads(input_path.read_text())
    report = render_report(data)
    output_path.write_text(report)
    print(f"Written to {output_path}")


if __name__ == "__main__":
    main()
