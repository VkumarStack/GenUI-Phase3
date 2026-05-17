"""
Build Vertex AI SFT training JSONL for the evaluator model.

Each training example pairs:
  Input  — revision task + Step 1 spec + DOM diff + Before/After screenshots
  Output — the expert verdict + pass/fail reasons (from label.txt)

The system instruction encodes the evaluation framework (verdict criteria,
evaluation dimensions) but uses a simplified output format that matches the
label structure (PASS/PARTIAL/FAIL + Pass/Fail Reasons) rather than the richer
inference-time format. The goal is to align the model with designer terminology
and evaluation rationale, not to teach a specific output schema.

Reads GCS URIs from the shared manifest produced by FineTuning/upload_assets.py.
Resolves the source RawDataset folder for each example via meta.json.

Running:
    python FineTuning/Evaluator/build_dataset.py
    python FineTuning/Evaluator/build_dataset.py \\
        --dataset Datasets/EvaluatorModelDataset/Train \\
        --manifest FineTuning/manifest.json \\
        --output FineTuning/Evaluator/train.jsonl
"""

import argparse
import json
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
_DATASET = _ROOT / "Datasets" / "EvaluatorModelDataset" / "Train"
_MANIFEST = _ROOT / "FineTuning" / "manifest.json"
_OUTPUT = Path(__file__).parent / "train.jsonl"

# Static system instruction: evaluation framework + simplified output format.
# The output format matches the label.txt structure from the expert study so
# there is no mismatch between the prompt's instructions and the supervision signal.
# The richer structured format (Image Reasoning, DOM Reasoning, Pass/Fail Notes)
# is reserved for the inference prompt in Evaluator/step2_prompt.txt.
_SYSTEM_INSTRUCTION = (
    "You are a UI/UX evaluator assessing whether an AI-generated revision to a "
    "mobile app interface successfully accomplished the requested task.\n\n"

    "You are given:\n"
    "- The original revision task\n"
    "- A grounded expected-change specification describing what the revised "
    "interface should look like\n"
    "- A DOM diff showing the structural and CSS changes made between Before and After\n"
    "- The Before screenshot (original interface)\n"
    "- The After screenshot (revised interface)\n\n"

    "VERDICT OPTIONS:\n"
    "- PASS: The revision successfully accomplishes the task. Minor imperfections "
    "are acceptable — note them, but do not let nitpicks reduce the verdict.\n"
    "- PARTIAL: The revision meaningfully but incompletely executes the task, or "
    "executes it with noticeable issues that affect quality without being outright wrong.\n"
    "- FAIL: The revision fails to accomplish the task, makes no meaningful change, "
    "or introduces problems that undermine it. A partial attempt that fundamentally "
    "misses the goal is a FAIL, not a PARTIAL.\n\n"

    "EVALUATION PRIORITY:\n"
    "Base your verdict primarily on what is visible in the Before and After "
    "screenshots. The DOM diff is a supporting reference — use it to locate and "
    "understand what changed, but if the screenshots and the DOM diff conflict, "
    "trust the screenshots.\n\n"

    "EVALUATION DIMENSIONS:\n"
    "Assess the revision against all five dimensions below.\n\n"

    "Success dimensions (what the revision should demonstrate):\n"
    "1. Faithful Execution — Did the revision accurately and completely implement "
    "all explicit instructions? Were all instances and components covered?\n"
    "2. Design Improvement — Where the task requires or implies design judgment, "
    "did the revision make a sound visual decision?\n"
    "3. Contextual Preservation — Did the revision leave unrelated elements "
    "untouched? Does the after interface remain consistent with the design system "
    "of the before interface?\n\n"

    "Failure signals (issues that lower the verdict):\n"
    "4. Instruction Following Failure — Did the revision miss components, apply "
    "the change incorrectly, or misread the task scope?\n"
    "5. Negative Design Impact — Did the revision introduce any new visual, "
    "usability, or functional problems — even while attempting to follow the task?\n\n"

    "OUTPUT FORMAT:\n"
    "Respond with PASS, PARTIAL, or FAIL on the first line. Then include "
    "Pass Reasons and/or Fail Reasons (as applicable) explaining your verdict "
    "in terms of the evaluation dimensions above."
)


def load_example(example_dir: Path, manifest: dict) -> dict | None:
    """Load one example. Returns None if any required file is missing."""
    name = example_dir.name

    meta_path  = example_dir / "meta.json"
    task_path  = example_dir / "task.txt"
    label_path = example_dir / "label.txt"
    spec_path  = example_dir / "step1_spec.txt"
    diff_path  = example_dir / "dom_diff.txt"

    for p in [meta_path, task_path, label_path]:
        if not p.exists():
            print(f"  [SKIP] {name}: missing {p.name}")
            return None

    meta = json.loads(meta_path.read_text())
    source = meta.get("source")
    if not source:
        print(f"  [SKIP] {name}: meta.json missing 'source'")
        return None

    if source not in manifest:
        print(f"  [SKIP] {name}: source '{source}' not in manifest — run upload_assets.py")
        return None

    uris = manifest[source]
    if "before" not in uris or "after" not in uris:
        print(f"  [SKIP] {name}: manifest missing before/after URIs for {source}")
        return None

    spec = spec_path.read_text().strip() if spec_path.exists() else "(not available)"
    diff = diff_path.read_text().strip() if diff_path.exists() else "(not available)"

    # Silently skip examples where step1 was not computed
    if spec.startswith("(not computed"):
        print(f"  [SKIP] {name}: step1_spec.txt not computed — run fill_step1.py")
        return None

    return {
        "name":       name,
        "task":       task_path.read_text().strip(),
        "label":      label_path.read_text().strip(),
        "spec":       spec,
        "diff":       diff,
        "before_uri": uris["before"],
        "after_uri":  uris["after"],
    }


def build_training_example(ex: dict) -> dict:
    """Format one example in the Vertex AI SFT GenerateContent format."""
    user_parts = [
        {
            "text": (
                f"Revision task:\n{ex['task']}\n\n"
                f"Expected-change specification:\n{ex['spec']}\n\n"
                f"DOM diff (supporting context):\n{ex['diff']}\n\n"
                "Assess the Before and After screenshots and provide your verdict."
            )
        },
        {"text": "Before screenshot:"},
        {"fileData": {"fileUri": ex["before_uri"], "mimeType": "image/png"}},
        {"text": "After screenshot:"},
        {"fileData": {"fileUri": ex["after_uri"], "mimeType": "image/png"}},
    ]
    return {
        "systemInstruction": {"parts": [{"text": _SYSTEM_INSTRUCTION}]},
        "contents": [
            {"role": "user",  "parts": user_parts},
            {"role": "model", "parts": [{"text": ex["label"]}]},
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
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    example_dirs = sorted(d for d in Path(args.dataset).iterdir() if d.is_dir())

    records = []
    for example_dir in example_dirs:
        ex = load_example(example_dir, manifest)
        if ex is None:
            continue
        records.append(build_training_example(ex))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")

    print(f"\nWrote {len(records)} training example(s) to {output_path}")


if __name__ == "__main__":
    main()
