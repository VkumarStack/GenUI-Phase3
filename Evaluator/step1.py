"""
Step 1 of the two-step evaluation pipeline: code analysis.

Given the revision task, the Before screenshot (for visual conditioning),
the full Before HTML, and the HTML diff (Before → After), produces a
structured code analysis report identifying task-relevant changes, unrelated
changes, completeness gaps, and visual verification notes for Step 2.

The prompt lives in step1_prompt.txt.

Because Step 1 only depends on the task + Before state (identical across all
model variants of the same case study), deduplication is applied by
fill_step1.py: the model is called once per unique case study and the result
is written to step1_spec.txt in all variant folders.

Running standalone (single example, for testing):
    python Evaluator/step1.py --example Datasets/EvaluatorModelDataset/Participant_2_CaseStudy-1.1-CLAUDE
    python Evaluator/step1.py --example ... --backend gemini --model gemini-2.5-pro
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
from backends import Backend, get_backend
from html_diff import html_diff as compute_html_diff

_PROMPT_FILE   = Path(__file__).parent / "step1_prompt.txt"
_DEFAULT_MODEL = "gemini-3.1-pro-preview"


def _get_html_diff(folder: Path) -> str:
    cached = folder / "html_diff.txt"
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    before = folder / "Before" / "index.html"
    after  = folder / "After"  / "index.html"
    if before.exists() and after.exists():
        return compute_html_diff(before, after)
    return "(HTML diff unavailable — index.html files not found)"


def run_one(folder: Path, backend: "Backend") -> dict:
    """Generate a Step 1 code analysis for one example folder."""
    task_file  = folder / "Task.txt"
    before_img = folder / "Before" / "screenshot.png"
    before_html_file = folder / "Before" / "index.html"

    if not task_file.exists():
        return {"error": f"Task.txt not found in {folder.name}"}
    if not before_img.exists():
        return {"error": f"Before/screenshot.png not found in {folder.name}"}
    if not before_html_file.exists():
        return {"error": f"Before/index.html not found in {folder.name}"}

    task       = task_file.read_text(encoding="utf-8").strip()
    before_html = before_html_file.read_text(encoding="utf-8")
    diff_text  = _get_html_diff(folder)

    prompt = _PROMPT_FILE.read_text().format(
        task=task,
        before_html=before_html,
        html_diff=diff_text,
    )

    response = backend.generate(prompt, images=[before_img.read_bytes()])

    return {
        "task":               task,
        "representative_folder": folder.name,
        "code_analysis":      response,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Step 1: generate a code analysis for a single example (for testing)."
    )
    parser.add_argument("--example", metavar="PATH", required=True,
                        help="Path to example folder.")
    parser.add_argument("--backend", default="gemini",
                        choices=["gemini", "vertexai", "anthropic", "openai"],
                        help="Model backend (default: gemini).")
    parser.add_argument("--model", default=None,
                        help="Override model/endpoint (optional).")
    args = parser.parse_args()

    model   = args.model or (_DEFAULT_MODEL if args.backend == "gemini" else None)
    backend = get_backend(args.backend, model)
    result  = run_one(Path(args.example), backend)
    if "error" in result:
        raise SystemExit(f"ERROR: {result['error']}")
    print(result["code_analysis"])


if __name__ == "__main__":
    main()
