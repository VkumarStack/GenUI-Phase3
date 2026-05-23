"""
Sample N training examples from the EvaluatorModelDataset/Train split and
render them as markdown for manual inspection before fine-tuning.

Shows the full system instruction (once), then for each sampled example:
  - Before / After screenshots
  - Full user prompt (DOM diff block + Step 1 block + revision task)
  - Target model response (rubric verdict built from RubricEvaluation.json)

Usage:
    python FineTuning/Evaluator/inspect_dataset.py
    python FineTuning/Evaluator/inspect_dataset.py --n 5 --seed 7
    python FineTuning/Evaluator/inspect_dataset.py > review.md
"""

import argparse
import json
import random
import sys
from pathlib import Path

_ROOT    = Path(__file__).parent.parent.parent
_DATASET = _ROOT / "Datasets" / "EvaluatorModelDataset" / "Train"

# Import shared constants from build_dataset so the rendered prompt matches
# exactly what goes into the JSONL.
sys.path.insert(0, str(Path(__file__).parent))
from build_dataset import (
    _SYSTEM_INSTRUCTION,
    _DOM_DIFF_HEADER,
    _CRITERIA,
    _VERDICT_MAP,
    _format_model_response,
)


def _build_user_text(folder: Path, no_dom_diff: bool, no_step1: bool) -> str:
    task = (folder / "Task.txt").read_text().strip()

    dom_diff_block = ""
    if not no_dom_diff:
        diff_path = folder / "dom_diff.txt"
        if diff_path.exists():
            diff = diff_path.read_text().strip()
            if diff:
                dom_diff_block = _DOM_DIFF_HEADER + diff + "\n\n---\n\n"

    step1_block = ""
    if not no_step1:
        spec_path = folder / "step1_spec.txt"
        if spec_path.exists():
            spec = spec_path.read_text().strip()
            if spec and not spec.startswith("(Step 1") and not spec.startswith("(not computed"):
                step1_block = (
                    "UI Component Context (visual navigation aid — not additional requirements):\n"
                    + spec + "\n\n---\n\n"
                )

    return (
        f"{dom_diff_block}{step1_block}"
        f"Revision task:\n{task}\n\n"
        "---\n\n"
        "Assess the Before and After screenshots against the task and output your evaluation "
        "using the format specified in the system instruction."
    )


def _is_usable(folder: Path, no_step1: bool) -> bool:
    if not (folder / "Task.txt").exists():
        return False
    if not (folder / "RubricEvaluation.json").exists():
        return False
    if not (folder / "Before" / "screenshot.png").exists():
        return False
    if not (folder / "After" / "screenshot.png").exists():
        return False
    if not no_step1:
        spec_path = folder / "step1_spec.txt"
        if not spec_path.exists():
            return False
        spec = spec_path.read_text().strip()
        if not spec or spec.startswith("(Step 1") or spec.startswith("(not computed"):
            return False
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Render sampled EvaluatorModel training examples as markdown."
    )
    parser.add_argument("--n",       type=int, default=10, metavar="N",
                        help="Number of examples to sample (default: 10).")
    parser.add_argument("--seed",    type=int, default=42)
    parser.add_argument("--dataset", default=str(_DATASET), metavar="PATH",
                        help=f"Train directory (default: {_DATASET}).")
    parser.add_argument("--no-dom-diff", action="store_true",
                        help="Omit DOM diff (match ablation used for training).")
    parser.add_argument("--no-step1", action="store_true",
                        help="Omit Step 1 spec (match ablation used for training).")
    args = parser.parse_args()

    dataset = Path(args.dataset)
    all_folders = sorted(d for d in dataset.iterdir() if d.is_dir())
    usable = [f for f in all_folders if _is_usable(f, args.no_step1)]

    if not usable:
        raise SystemExit(f"No usable examples found in {dataset}")

    rng    = random.Random(args.seed)
    sample = rng.sample(usable, min(args.n, len(usable)))

    out = sys.stdout

    out.write("# Evaluator Model — Training Sample\n\n")
    out.write(f"**Dataset:** `{dataset.relative_to(_ROOT)}`  \n")
    out.write(f"**Usable examples:** {len(usable)} / {len(all_folders)}  |  ")
    out.write(f"**Sampled:** {len(sample)}  |  **Seed:** {args.seed}  \n")
    out.write(f"**DOM diff:** {'off' if args.no_dom_diff else 'on'}  |  ")
    out.write(f"**Step 1:** {'off' if args.no_step1 else 'on'}\n\n")

    out.write("---\n\n")
    out.write("## System Instruction *(same for all examples)*\n\n")
    out.write("```\n")
    out.write(_SYSTEM_INSTRUCTION)
    out.write("\n```\n\n")
    out.write("---\n\n")

    for i, folder in enumerate(sample, 1):
        rubric = json.loads((folder / "RubricEvaluation.json").read_text())
        overall = rubric.get("overallEvaluation", "?").upper()

        before_img = folder.resolve() / "Before" / "screenshot.png"
        after_img  = folder.resolve() / "After"  / "screenshot.png"
        before_rel = f"../../{before_img.relative_to(_ROOT)}"
        after_rel  = f"../../{after_img.relative_to(_ROOT)}"

        user_text     = _build_user_text(folder, args.no_dom_diff, args.no_step1)
        model_response = _format_model_response(rubric)

        out.write(f"## {i}. `{folder.name}` — {overall}\n\n")
        out.write(f"| Before | After |\n")
        out.write(f"|--------|-------|\n")
        out.write(f"| ![before]({before_rel}) | ![after]({after_rel}) |\n\n")
        out.write(f"**User prompt:**\n\n")
        out.write(f"```\n{user_text}\n```\n\n")
        out.write(f"**Target model response:**\n\n")
        out.write(f"```\n{model_response}\n```\n\n")
        out.write("---\n\n")


if __name__ == "__main__":
    main()
