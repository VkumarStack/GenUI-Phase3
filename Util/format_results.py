"""
Format a test_model.py results JSON file into readable markdown.

Usage:
    python Util/format_results.py Results/gemini_base_two_stage.json
    python Util/format_results.py Results/gemini_base_two_stage.json --out Results/gemini_base_two_stage.md
    python Util/format_results.py Results/gemini_base.json --incorrect-only
"""

import argparse
import json
from pathlib import Path


def verdict_icon(entry: dict) -> str:
    if entry["prediction"] == "UNKNOWN":
        return "?"
    return "✓" if entry["correct"] else "✗"


def format_entry(entry: dict) -> str:
    icon = verdict_icon(entry)
    header = f"## {entry['name']} — {icon} {entry['prediction']} (truth: {entry['ground_truth']})"

    parts = [header]

    checklist = entry.get("checklist", "").strip()
    if checklist:
        parts.append("\n**Checklist**\n")
        parts.append(checklist)

    code = entry.get("code_reasoning", "").strip()
    if code:
        parts.append(f"\n**Code Reasoning:** {code}")

    image = entry.get("image_reasoning", "").strip()
    if image:
        parts.append(f"\n**Image Reasoning:** {image}")

    if entry.get("worker_results"):
        parts.append("\n**Worker Verdicts**")
        for w in entry["worker_results"]:
            parts.append(f"- {w['worker']}: {w['verdict']}")

    return "\n".join(parts)


def format_results(data: dict, incorrect_only: bool = False) -> str:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    examples = data.get("examples", [])

    lines = []

    # Header
    lines.append(f"# Results: {meta.get('backend', '?')} / {meta.get('model', '?')}"
                 f"  ({meta.get('eval_method', 'single')})")
    lines.append("")

    # Summary
    cm = metrics.get("confusion_matrix", {})
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric    | Value |")
    lines.append(f"|-----------|-------|")
    lines.append(f"| Accuracy  | {metrics.get('accuracy', 'N/A')} |")
    lines.append(f"| Precision | {metrics.get('precision', 'N/A')} |")
    lines.append(f"| Recall    | {metrics.get('recall', 'N/A')} |")
    lines.append(f"| F1        | {metrics.get('f1', 'N/A')} |")
    lines.append("")
    lines.append(f"**{metrics.get('correct', 0)}/{metrics.get('total', 0)} correct**"
                 f" | {metrics.get('unknown', 0)} unknown"
                 f" | TP {cm.get('tp',0)}  FP {cm.get('fp',0)}"
                 f"  TN {cm.get('tn',0)}  FN {cm.get('fn',0)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Examples
    shown = 0
    for entry in examples:
        if incorrect_only and entry.get("correct", False):
            continue
        lines.append(format_entry(entry))
        lines.append("")
        lines.append("---")
        lines.append("")
        shown += 1

    if shown == 0:
        lines.append("_No entries to display._")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Format results JSON as markdown.")
    parser.add_argument("input", metavar="PATH", help="Path to the results JSON file.")
    parser.add_argument("--out", metavar="PATH", default=None,
                        help="Output .md file path. Defaults to <input>.md.")
    parser.add_argument("--incorrect-only", action="store_true",
                        help="Only include examples where the prediction was wrong.")
    args = parser.parse_args()

    input_path = Path(args.input)
    data = json.loads(input_path.read_text())

    md = format_results(data, incorrect_only=args.incorrect_only)

    out_path = Path(args.out) if args.out else input_path.with_suffix(".md")
    out_path.write_text(md)
    print(f"Written to {out_path}")


if __name__ == "__main__":
    main()
