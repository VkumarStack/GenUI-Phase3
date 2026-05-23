"""
Format a results JSON into markdown for manual inspection.

Examples are ordered wrong-first (ground truth != predicted), then correct ones.
Ground truth rubric criteria are read from RubricEvaluation.json in the dataset.

Usage:
    python Testing/Evaluator/inspect_results.py Testing/Evaluator/Results/gemini.json
    python Testing/Evaluator/inspect_results.py Testing/Evaluator/Results/gemini.json > review.md
"""

import json
import sys
from pathlib import Path

_ROOT    = Path(__file__).parent.parent.parent
_DATASET = _ROOT / "Datasets" / "EvaluatorModelDataset"

# Maps predicted criteria keys → display labels
_CRITERIA_LABELS = {
    "requirementFulfillment": "Requirement Fulfillment",
    "consistency":            "Consistency",
    "visualUsability":        "Visual & Usability",
    "minimality":             "Minimality",
    "noRegressions":          "No Regressions",
}

# Maps ground-truth criteria keys (from RubricEvaluation.json) → display labels
_GT_CRITERIA_LABELS = {
    "requirementFulfillment": "Requirement Fulfillment",
    "consistencyOriginal":    "Consistency",
    "visualUsability":        "Visual & Usability",
    "minimality":             "Minimality",
    "noRegressions":          "No Regressions",
}


def _task_text(folder_name: str, dataset: Path) -> str:
    p = dataset / folder_name / "Task.txt"
    return p.read_text().strip() if p.exists() else "(Task.txt not found)"


def _step1_spec(folder_name: str, dataset: Path) -> str:
    p = dataset / folder_name / "step1_spec.txt"
    return p.read_text().strip() if p.exists() else "(step1_spec.txt not found)"


def _dom_diff(folder_name: str, dataset: Path) -> str:
    p = dataset / folder_name / "dom_diff.txt"
    return p.read_text().strip() if p.exists() else "(dom_diff.txt not found)"


def _gt_comment(folder_name: str, dataset: Path) -> str:
    p = dataset / folder_name / "RubricEvaluation.json"
    if not p.exists():
        return "(RubricEvaluation.json not found)"
    rubric = json.loads(p.read_text())
    return rubric.get("overallComment", "(no comment)")


def _criteria_table(gt_criteria: dict | None, pred_criteria: dict | None) -> list[str]:
    """Render a side-by-side criteria comparison table."""
    lines = [
        "| Criterion | Ground Truth | Predicted |",
        "|---|---|---|",
    ]
    for pred_key, label in _CRITERIA_LABELS.items():
        gt_key = next(
            (k for k, v in _GT_CRITERIA_LABELS.items() if v == label), pred_key
        )
        gt_val   = (gt_criteria or {}).get(gt_key, "—").upper()
        pred_val = (pred_criteria or {}).get(pred_key, "—")
        if pred_val:
            pred_val = pred_val.upper()
        lines.append(f"| {label} | {gt_val} | {pred_val or '—'} |")
    return lines


def _render_example(ex: dict, idx: int, wrong: bool, dataset: Path) -> str:
    folder      = ex["folder"]
    gt          = ex.get("ground_truth") or "?"
    pred        = ex.get("predicted")    or "?"
    response    = ex.get("response")     or "(no response)"
    comment     = ex.get("comment")      or "(no comment)"
    task        = _task_text(folder, dataset)
    step1       = _step1_spec(folder, dataset)
    dom_diff    = _dom_diff(folder, dataset)
    gt_comment  = _gt_comment(folder, dataset)

    status       = "WRONG" if wrong else "correct"
    verdict_line = f"`{gt}` → predicted `{pred}`" if wrong else f"`{pred}` ✓"

    img_dir  = f"../{_ROOT.name}/Datasets/EvaluatorModelDataset/{folder}"
    before   = f"{img_dir}/Before/screenshot.png"
    after    = f"{img_dir}/After/screenshot.png"

    lines = [
        f"## {idx}. {folder}  —  {status}",
        "",
        f"**Verdict:** {verdict_line}",
        "",
        "**Task**",
        "",
        task,
        "",
        "<details><summary>Step 1 — UI Component Context</summary>",
        "",
        "```",
        step1,
        "```",
        "",
        "</details>",
        "",
        "<details><summary>DOM Diff</summary>",
        "",
        "```",
        dom_diff,
        "```",
        "",
        "</details>",
        "",
        "| Before | After |",
        "|:---:|:---:|",
        f"| ![Before]({before}) | ![After]({after}) |",
        "",
        "**Rubric criteria**",
        "",
        *_criteria_table(ex.get("gt_criteria"), ex.get("pred_criteria")),
        "",
        f"**Ground truth comment:** {gt_comment}",
        "",
        f"**Model comment:** {comment}",
        "",
        "<details><summary>Full model response</summary>",
        "",
        "```",
        response,
        "```",
        "",
        "</details>",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python inspect_results.py <results.json> [dataset_path]")

    results_path = Path(sys.argv[1])
    if not results_path.exists():
        raise SystemExit(f"File not found: {results_path}")

    dataset = Path(sys.argv[2]) if len(sys.argv) > 2 else _DATASET

    data     = json.loads(results_path.read_text())
    examples = data.get("examples", [])
    metrics  = data.get("metrics", {})
    run_name = data.get("run_name", results_path.stem)
    model    = data.get("model") or data.get("backend", "")

    no_dom_diff = data.get("no_dom_diff", False)
    no_step1    = data.get("no_step1", False)
    ablation    = []
    if no_dom_diff:
        ablation.append("no DOM diff")
    if no_step1:
        ablation.append("no Step 1")
    ablation_str = f"  |  Ablation: {', '.join(ablation)}" if ablation else ""

    wrong   = [e for e in examples if e.get("ground_truth") != e.get("predicted")]
    correct = [e for e in examples if e.get("ground_truth") == e.get("predicted")
               and e.get("predicted") is not None]
    ordered = wrong + correct

    parts = [
        f"# Evaluator Results: {run_name}",
        "",
        f"**Model:** {model}  |  **Dataset:** {data.get('dataset', '?')}{ablation_str}",
        f"**Timestamp:** {data.get('timestamp', '?')}",
        "",
    ]

    if metrics:
        parts += [
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|---|---|",
            f"| Accuracy | {metrics.get('accuracy', 0):.1%} |",
            f"| Macro F1 | {metrics.get('macro_f1', 0):.4f} |",
            f"| Wrong / Total | {len(wrong)} / {len(examples)} |",
            "",
        ]
        pc = metrics.get("per_class", {})
        if pc:
            parts += [
                "| Class | Precision | Recall | F1 | Support |",
                "|---|---|---|---|---|",
            ]
            for v in ["PASS", "FAIL"]:
                if v in pc:
                    c = pc[v]
                    parts.append(
                        f"| {v} | {c['precision']:.3f} | {c['recall']:.3f}"
                        f" | {c['f1']:.3f} | {c['support']} |"
                    )
            parts.append("")

        cm = metrics.get("confusion_matrix", {})
        if cm:
            verdicts = ["PASS", "FAIL"]
            parts += [
                "**Confusion matrix** (rows = actual, cols = predicted)",
                "",
                "| | PASS | FAIL |",
                "|---|---|---|",
            ]
            for actual in verdicts:
                row = cm.get(actual, {})
                parts.append(
                    f"| **{actual}** | {row.get('PASS', 0)} | {row.get('FAIL', 0)} |"
                )
            parts.append("")

    parts += [
        "---",
        "",
        f"*{len(wrong)} wrong first, then {len(correct)} correct.*",
        "",
    ]

    for i, ex in enumerate(ordered, 1):
        is_wrong = ex.get("ground_truth") != ex.get("predicted")
        parts.append(_render_example(ex, i, is_wrong, dataset))

    print("\n".join(parts))


if __name__ == "__main__":
    main()
