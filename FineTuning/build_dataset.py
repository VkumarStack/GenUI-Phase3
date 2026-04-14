"""
Construct Vertex AI SFT training examples from evaluation examples.

Each training example pairs:
  Input  — task description + code diff + before/after screenshots (as GCS URIs)
  Output — the expected model response from Output.txt (Pass/Fail + justification)

Reads GCS URIs from the manifest produced by upload_assets.py.
Outputs a JSONL file where each line is one training example in the
Vertex AI Gemini supervised fine-tuning format.

Reference:
    https://cloud.google.com/vertex-ai/generative-ai/docs/models/gemini-supervised-tuning-prepare

Usage:
    python FineTuning/build_dataset.py \\
        --dir Examples/CaseStudyExamples \\
        --manifest FineTuning/manifest.json \\
        --output FineTuning/train.jsonl

    python FineTuning/build_dataset.py \\
        --example Examples/CaseStudyExamples/task-8-gemini \\
        --manifest FineTuning/manifest.json \\
        --output FineTuning/train.jsonl
"""

import argparse
import json
from pathlib import Path

# System instruction sent with every training example.
# Mirrors the intent of the evaluation pipeline: given a UI revision task,
# the code diff, and before/after screenshots, output PASS or FAIL with justification.
SYSTEM_INSTRUCTION = (
    "You are evaluating whether a UI revision task was correctly implemented. "
    "You will be given the revision task description, the code diff, and before/after screenshots. "
    "Determine whether the task was successfully accomplished in the rendered UI.\n\n"

    "EVALUATION CRITERIA:\n"
    "1. The screenshots are the primary basis for your verdict. "
    "If the code change looks correct but the expected result is not visible in the after screenshot, the verdict is FAIL. "
    "Use the code diff only as conditioning — it tells you where and what to look for in the screenshots, "
    "not whether the task passed.\n"
    "2. If the after screenshot contains major visual changes unrelated to the task, the verdict is FAIL, "
    "even if the task itself was implemented correctly. "
    "Minor incidental differences such as slight spacing or subtle formatting shifts are acceptable.\n\n"

    "OUTPUT FORMAT:\n"
    "Respond with exactly the following structure:\n"
    "PASS or FAIL\n\n"
    "Code Reasoning: <one to two sentences describing what the diff shows and whether it targets the right elements>\n\n"
    "Image Reasoning: <one to two sentences describing what is visually different between the screenshots "
    "and whether the change satisfies the task>\n\n"

    "Example of a passing response:\n"
    "PASS\n\n"
    "Code Reasoning: The label elements have been updated to include a red asterisk (text-red-500), "
    "which directly addresses the task.\n\n"
    "Image Reasoning: In the after screenshot, a red asterisk is visible next to each input label. "
    "No other elements changed between the two screenshots.\n\n"

    "Example of a failing response:\n"
    "FAIL\n\n"
    "Code Reasoning: The diff changes the footer text color class from dark:text-slate-800 to dark:text-white, "
    "which is the correct element.\n\n"
    "Image Reasoning: The footer text color appears identical in both screenshots; "
    "the expected white text is not visible in the after screenshot."
)


def build_user_parts(task: str, diff: str, before_uri: str, after_uri: str) -> list:
    """Build the multimodal user parts list in native Gemini GenerateContent format."""
    return [
        # Images first — Gemini attends better when images precede the text prompt.
        {"text": "Before screenshot:"},
        {"fileData": {"fileUri": before_uri, "mimeType": "image/png"}},
        {"text": "After screenshot:"},
        {"fileData": {"fileUri": after_uri, "mimeType": "image/png"}},
        {
            "text": (
                f"Revision task: {task}\n\n"
                f"Code diff (unified diff of Before → After):\n{diff}"
            )
        },
    ]


def load_example(example_dir: Path, manifest: dict) -> dict | None:
    """Load one example, returning None if any required file is missing."""
    name = example_dir.name

    task_path   = example_dir / "Task.txt"
    diff_path   = example_dir / "After" / "diff.txt"
    output_path = example_dir / "Output.txt"

    missing = [p for p in [task_path, diff_path, output_path] if not p.exists()]
    if missing:
        print(f"  [SKIP] {name}: missing {[str(p) for p in missing]}")
        return None

    if name not in manifest:
        print(f"  [SKIP] {name}: not in manifest (run upload_assets.py first)")
        return None

    uris = manifest[name]
    if "before" not in uris or "after" not in uris:
        print(f"  [SKIP] {name}: manifest missing before/after URIs")
        return None

    return {
        "name":       name,
        "task":       task_path.read_text().strip(),
        "diff":       diff_path.read_text().strip(),
        "output":     output_path.read_text().strip(),
        "before_uri": uris["before"],
        "after_uri":  uris["after"],
    }


def build_training_example(ex: dict) -> dict:
    """Format one example in the native Vertex AI GenerateContent (contents) format."""
    user_parts = build_user_parts(
        ex["task"], ex["diff"], ex["before_uri"], ex["after_uri"]
    )
    return {
        "systemInstruction": {
            "parts": [{"text": SYSTEM_INSTRUCTION}]
        },
        "contents": [
            {"role": "user",  "parts": user_parts},
            {"role": "model", "parts": [{"text": ex["output"]}]},
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Build Vertex AI SFT training JSONL.")

    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--example", metavar="PATH", help="Path to a single example directory.")
    target.add_argument("--dir",     metavar="PATH", help="Path to a directory of examples.")

    parser.add_argument("--manifest", default="FineTuning/manifest.json",
                        help="Path to the GCS URI manifest from upload_assets.py.")
    parser.add_argument("--output", default="FineTuning/train.jsonl",
                        help="Output JSONL path (default: FineTuning/train.jsonl).")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())

    if args.example:
        example_dirs = [Path(args.example)]
    else:
        example_dirs = sorted(d for d in Path(args.dir).iterdir() if d.is_dir())

    records = []
    for example_dir in example_dirs:
        print(f"Example: {example_dir.name}")
        ex = load_example(example_dir, manifest)
        if ex is None:
            continue
        records.append(build_training_example(ex))

        print(f"  Added training pair.")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")

    print(f"\nWrote {len(records)} training example(s) to {output_path}")


if __name__ == "__main__":
    main()
