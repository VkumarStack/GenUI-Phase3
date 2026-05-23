"""
Build Vertex AI SFT training JSONL for the evaluator model.

Each training example pairs:
  Input  — revision task + UI Component Context (Step 1) + DOM diff
            + Before/After screenshots (GCS URIs)
  Output — rubric verdict in the structured format used at inference time
           (5 criteria PASS/PARTIAL PASS/FAIL + binary OVERALL + COMMENT)

Ground truth is read from RubricEvaluation.json in each example folder.
GCS URIs are resolved from the shared manifest produced by FineTuning/upload_assets.py.

Running:
    python FineTuning/Evaluator/build_dataset.py
    python FineTuning/Evaluator/build_dataset.py \\
        --dataset Datasets/EvaluatorModelDataset/Train \\
        --manifest FineTuning/manifest.json \\
        --output FineTuning/Evaluator/train.jsonl

    # Ablation variants (match the ablation run used for evaluation)
    python FineTuning/Evaluator/build_dataset.py --no-dom-diff
    python FineTuning/Evaluator/build_dataset.py --no-step1
"""

import argparse
import json
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
_DATASET = _ROOT / "Datasets" / "EvaluatorModelDataset" / "Train"
_MANIFEST = _ROOT / "FineTuning" / "manifest.json"
_OUTPUT = Path(__file__).parent / "train.jsonl"

_CRITERIA = [
    ("requirementFulfillment", "REQUIREMENT FULFILLMENT"),
    ("consistencyOriginal",    "CONSISTENCY"),
    ("visualUsability",        "VISUAL & USABILITY"),
    ("minimality",             "MINIMALITY"),
    ("noRegressions",          "NO REGRESSIONS"),
]

_VERDICT_MAP = {
    "pass":    "PASS",
    "fail":    "FAIL",
    "partial": "PARTIAL PASS",
    "na":      "N/A",
}

_DOM_DIFF_HEADER = (
    "DOM DIFF SECTIONS:\n"
    "The DOM diff contains up to three sections:\n"
    "1. CSS Rule Changes — declarations that changed inside <style> blocks. Shows intent but "
    "not whether a rule took effect (it may be overridden by a more specific rule).\n"
    "2. Computed Style Changes (browser-rendered) — the final resolved CSS value for each "
    "directly-targeted element. This is the authoritative signal for whether a style change "
    "actually applied.\n"
    "3. DOM Structure Changes — structural additions, removals, or attribute changes "
    "(including inline style= attributes) shown as a unified diff.\n\n"
)

_SYSTEM_INSTRUCTION = (
    "You are a UI/UX evaluator assessing whether an AI-generated revision to a mobile app "
    "interface successfully accomplished the requested task.\n\n"

    "EVALUATION NOTES:\n\n"

    "**On component context (if provided above):**\n"
    "The UI Component Context section — if present — identifies which elements to look at in "
    "the screenshots. It is a visual navigation aid only. Do not treat anything in it as an "
    "additional requirement. If it describes specific implementation details not stated in the "
    "revision task itself, ignore those details when scoring. The revision task is the sole "
    "source of what was required.\n\n"

    "**On flexible task language:**\n"
    "When the task uses \"or,\" \"e.g.,\" \"such as,\" or \"for example,\" it is offering "
    "options or examples — not prescribing one specific approach. Evaluate against the stated "
    "intent, not against one particular example. A different but equally valid implementation "
    "that achieves the same goal should pass.\n\n"

    "**On partial implementations:**\n"
    "If the core intent of the task was accomplished and only secondary details are missing, "
    "lean toward an overall PASS rather than FAIL. This applies to missing minor details, not "
    "to unrequested changes that broke the design.\n\n"

    "**On subtle visual changes:**\n"
    "If the screenshots appear unchanged for a task involving text corrections, minor color "
    "tweaks, or small CSS adjustments, check the DOM diff carefully before concluding no "
    "change was made — small changes are often invisible at screenshot resolution.\n\n"

    "**On regressions — actively check for these:**\n"
    "Before scoring No Regressions, explicitly look for:\n"
    "- New empty or blank areas where content used to be or where the layout now looks unbalanced\n"
    "- Elements visually clipped or cut off at the screen edge\n"
    "- Overlapping elements that obstruct each other\n"
    "- Unrequested changes to elements not mentioned in the task (moved, restyled, or removed)\n"
    "- Content changes (text altered, removed, or added beyond the task scope)\n\n"
    "Note: do not penalize for implicit layout side-effects not requested in the task "
    "(e.g. automatic reflow after an element is removed) — only penalize if the result is "
    "visually broken or clearly worse.\n\n"

    "RUBRIC:\n\n"

    "**A. Requirement Fulfillment** *(most important criterion)*\n"
    "Did the revision successfully perform the requested UI change? Consider whether the "
    "specific task was addressed, the correct element(s) were modified, and all parts of the "
    "instruction were followed.\n\n"

    "**B. Consistency with Original UI**\n"
    "Does the revision preserve the original screen's layout, structure, and visual design "
    "language? Unrelated sections should remain intact.\n\n"

    "**C. Visual & Usability Quality**\n"
    "Does the revision improve clarity, visual hierarchy, readability, accessibility, or "
    "overall usability — not just technically apply the change?\n\n"

    "**D. Minimality of Changes**\n"
    "Does the revision avoid unnecessary or unrelated modifications beyond what was requested?\n\n"

    "**E. No New Regressions**\n"
    "Does the revision avoid introducing new layout, visual, content, or interaction problems "
    "elsewhere in the interface?\n\n"

    "OVERALL VERDICT GUIDANCE:\n"
    "The overall verdict is binary — PASS or FAIL only (no PARTIAL PASS at this level).\n"
    "- Requirement Fulfillment is the most critical criterion. A FAIL on the core task "
    "typically results in an overall FAIL.\n"
    "- A PARTIAL PASS on Requirement Fulfillment that accomplished the primary intent often "
    "still warrants an overall PASS — use judgment on whether what was missing was central "
    "to the designer's goal or a secondary detail.\n"
    "- A critical regression (e.g. an entire UI section removed, a significant new visual "
    "problem) can override an otherwise passing score.\n"
    "- The overall verdict should reflect whether the revision was a net positive toward the "
    "designer's intent — not a mechanical average of criterion scores.\n\n"

    "OUTPUT FORMAT:\n"
    "REQUIREMENT FULFILLMENT: PASS / PARTIAL PASS / FAIL\n"
    "CONSISTENCY: PASS / PARTIAL PASS / FAIL\n"
    "VISUAL & USABILITY: PASS / PARTIAL PASS / FAIL\n"
    "MINIMALITY: PASS / PARTIAL PASS / FAIL\n"
    "NO REGRESSIONS: PASS / PARTIAL PASS / FAIL\n\n"
    "OVERALL: PASS / FAIL\n\n"
    "COMMENT: <1–3 sentences on the key reason for the overall verdict.>"
)


def _format_model_response(rubric: dict) -> str:
    criteria = rubric.get("criteria", {})
    lines = []
    for key, label in _CRITERIA:
        raw = criteria.get(key, "").lower()
        verdict = _VERDICT_MAP.get(raw, raw.upper())
        lines.append(f"{label}: {verdict}")
    lines.append("")
    overall = rubric.get("overallEvaluation", "").upper()
    lines.append(f"OVERALL: {overall}")
    lines.append("")
    comment = rubric.get("overallComment", "").strip()
    lines.append(f"COMMENT: {comment}")
    return "\n".join(lines)


def load_example(example_dir: Path, manifest: dict,
                 no_dom_diff: bool, no_step1: bool) -> dict | None:
    """Load one example. Returns None if any required file is missing."""
    name = example_dir.name

    task_path   = example_dir / "Task.txt"
    rubric_path = example_dir / "RubricEvaluation.json"

    for p in [task_path, rubric_path]:
        if not p.exists():
            print(f"  [SKIP] {name}: missing {p.name}")
            return None

    if name not in manifest:
        print(f"  [SKIP] {name}: not in manifest — run upload_assets.py")
        return None

    uris = manifest[name]
    if "before" not in uris or "after" not in uris:
        print(f"  [SKIP] {name}: manifest missing before/after URIs")
        return None

    rubric = json.loads(rubric_path.read_text())

    spec = ""
    if not no_step1:
        spec_path = example_dir / "step1_spec.txt"
        if spec_path.exists():
            spec = spec_path.read_text().strip()
        if not spec or spec.startswith("(not computed") or spec.startswith("(Step 1"):
            print(f"  [SKIP] {name}: step1_spec.txt missing or not populated")
            return None

    diff = ""
    if not no_dom_diff:
        diff_path = example_dir / "dom_diff.txt"
        if diff_path.exists():
            diff = diff_path.read_text().strip()

    return {
        "name":       name,
        "task":       task_path.read_text().strip(),
        "rubric":     rubric,
        "spec":       spec,
        "diff":       diff,
        "before_uri": uris["before"],
        "after_uri":  uris["after"],
    }


def build_training_example(ex: dict, no_dom_diff: bool, no_step1: bool) -> dict:
    """Format one example in the Vertex AI SFT GenerateContent format."""
    dom_diff_block = ""
    if not no_dom_diff and ex["diff"]:
        dom_diff_block = _DOM_DIFF_HEADER + ex["diff"] + "\n\n---\n\n"

    step1_block = ""
    if not no_step1 and ex["spec"]:
        step1_block = (
            "UI Component Context (visual navigation aid — not additional requirements):\n"
            + ex["spec"] + "\n\n---\n\n"
        )

    user_text = (
        f"{dom_diff_block}{step1_block}"
        f"Revision task:\n{ex['task']}\n\n"
        "---\n\n"
        "Assess the Before and After screenshots against the task and output your evaluation "
        "using the format specified in the system instruction."
    )

    user_parts = [
        {"text": user_text},
        {"text": "Before screenshot:"},
        {"fileData": {"fileUri": ex["before_uri"], "mimeType": "image/png"}},
        {"text": "After screenshot:"},
        {"fileData": {"fileUri": ex["after_uri"], "mimeType": "image/png"}},
    ]

    model_response = _format_model_response(ex["rubric"])

    return {
        "systemInstruction": {"parts": [{"text": _SYSTEM_INSTRUCTION}]},
        "contents": [
            {"role": "user",  "parts": user_parts},
            {"role": "model", "parts": [{"text": model_response}]},
        ],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Build Vertex AI SFT JSONL for the evaluator model."
    )
    parser.add_argument("--dataset",  default=str(_DATASET),  metavar="PATH",
                        help=f"EvaluatorModelDataset/Train directory (default: {_DATASET}).")
    parser.add_argument("--manifest", default=str(_MANIFEST), metavar="PATH",
                        help=f"GCS URI manifest from upload_assets.py (default: {_MANIFEST}).")
    parser.add_argument("--output",   default=str(_OUTPUT),   metavar="PATH",
                        help=f"Output JSONL path (default: {_OUTPUT}).")
    parser.add_argument("--no-dom-diff", action="store_true",
                        help="Omit DOM diff from training examples (ablation).")
    parser.add_argument("--no-step1", action="store_true",
                        help="Omit Step 1 spec from training examples (ablation).")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    dataset  = Path(args.dataset)
    example_dirs = sorted(d for d in dataset.iterdir() if d.is_dir())

    print(f"Dataset:   {dataset}  ({len(example_dirs)} folders)")
    print(f"DOM diff:  {'off' if args.no_dom_diff else 'on'}")
    print(f"Step 1:    {'off' if args.no_step1 else 'on'}")

    records = []
    for example_dir in example_dirs:
        ex = load_example(example_dir, manifest,
                          no_dom_diff=args.no_dom_diff, no_step1=args.no_step1)
        if ex is None:
            continue
        records.append(build_training_example(ex, args.no_dom_diff, args.no_step1))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")

    print(f"\nWrote {len(records)} training example(s) to {output_path}")


if __name__ == "__main__":
    main()
