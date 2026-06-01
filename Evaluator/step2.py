"""
Step 2 of the two-step evaluation pipeline.

Inputs per example:
  - Task.txt                      — the original revision task
  - step1_spec.txt                — code analysis from Step 1 (default)
  - Before/screenshot.png         — original interface
  - After/screenshot.png          — revised interface

Produces a structured rubric verdict (5 criteria + overall PASS/FAIL + comment).

Output: Evaluator/step2_results.json

Running:
    python Evaluator/step2.py

    # Run against the full EvaluatorModelDataset
    python Evaluator/step2.py --dataset Datasets/EvaluatorModelDataset

    # Run on a single example
    python Evaluator/step2.py --example Datasets/EvaluatorModelDataset/Participant_2_CaseStudy-1.1-CLAUDE

    # Ablation: skip Step 1 — pass the raw HTML diff directly instead
    python Evaluator/step2.py --no-step1

    # Resume a partially completed run
    python Evaluator/step2.py --resume
"""

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
from backends import Backend, get_backend
from html_diff import html_diff as compute_html_diff

_DATASET              = _ROOT / "Datasets" / "EvaluatorModelDataset"
_PROMPT_FILE          = Path(__file__).parent / "step2_prompt.txt"
_PROMPT_FILE_NO_STEP1 = Path(__file__).parent / "step2_prompt_no_step1.txt"
_OUTPUT_FILE          = Path(__file__).parent / "step2_results.json"
_DEFAULT_BACKEND = "gemini"
_DEFAULT_MODEL   = "gemini-3.1-pro-preview"

# Patterns for parsing structured rubric output
_CRITERION_PATTERN = re.compile(
    r"^(REQUIREMENT FULFILLMENT|CONSISTENCY|VISUAL\s*&\s*USABILITY|MINIMALITY|NO REGRESSIONS)"
    r"\s*:\s*(PASS|PARTIAL PASS|FAIL)",
    re.IGNORECASE | re.MULTILINE,
)
_OVERALL_PATTERN = re.compile(r"^OVERALL\s*:\s*(PASS|FAIL)", re.IGNORECASE | re.MULTILINE)
_COMMENT_PATTERN = re.compile(r"^COMMENT\s*:\s*(.+)", re.IGNORECASE | re.DOTALL | re.MULTILINE)


def _resolve_paths(folder: Path) -> tuple[Path, Path, Path]:
    """Return (task_file, before_screenshot, after_screenshot)."""
    return (
        folder / "Task.txt",
        folder / "Before" / "screenshot.png",
        folder / "After"  / "screenshot.png",
    )


def _get_step1_analysis(folder: Path) -> str:
    spec_file = folder / "step1_spec.txt"
    if spec_file.exists():
        return spec_file.read_text(encoding="utf-8").strip()
    return "(Step 1 code analysis unavailable — run fill_step1.py)"


def _get_html_diff(folder: Path) -> str:
    cached = folder / "html_diff.txt"
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    before = folder / "Before" / "index.html"
    after  = folder / "After"  / "index.html"
    if before.exists() and after.exists():
        return compute_html_diff(before, after)
    return "(HTML diff unavailable — index.html files not found)"


def _parse_response(response: str) -> dict:
    """Extract rubric criteria, overall verdict, and comment from the model response."""
    criteria_map = {
        "REQUIREMENT FULFILLMENT": "requirementFulfillment",
        "CONSISTENCY":             "consistency",
        "VISUAL & USABILITY":      "visualUsability",
        "VISUAL&USABILITY":        "visualUsability",
        "MINIMALITY":              "minimality",
        "NO REGRESSIONS":          "noRegressions",
    }

    criteria: dict[str, str] = {}
    for m in _CRITERION_PATTERN.finditer(response):
        raw_key = re.sub(r"\s+", " ", m.group(1).strip().upper())
        field   = criteria_map.get(raw_key) or criteria_map.get(raw_key.replace(" ", ""))
        if field:
            criteria[field] = m.group(2).upper()

    overall_match = _OVERALL_PATTERN.search(response)
    overall = overall_match.group(1).upper() if overall_match else None

    comment = ""
    comment_match = _COMMENT_PATTERN.search(response)
    if comment_match:
        comment = comment_match.group(1).strip().split("\n\n")[0].strip()

    return {"criteria": criteria, "overall": overall, "comment": comment}


def _run_one(folder: Path, backend: Backend, no_step1: bool = False) -> dict:
    task_file, before, after = _resolve_paths(folder)

    if not task_file.exists():
        return {"error": "Task.txt not found"}
    if not before.exists() or not after.exists():
        return {"error": "Missing before or after screenshot"}

    task = task_file.read_text(encoding="utf-8").strip()

    if no_step1:
        diff_text      = _get_html_diff(folder)
        html_diff_block = (
            f"HTML Diff (unified diff, Before → After — no pre-analysis provided):\n"
            f"{diff_text}\n\n---\n\n"
        )
        prompt = _PROMPT_FILE_NO_STEP1.read_text().format(
            task=task,
            html_diff_block=html_diff_block,
        )
    else:
        analysis_text        = _get_step1_analysis(folder)
        step1_analysis_block = (
            f"Code Analysis (from Step 1 — treat as supplementary context, not a verdict):\n"
            f"{analysis_text}\n\n---\n\n"
        )
        prompt = _PROMPT_FILE.read_text().format(
            task=task,
            step1_analysis_block=step1_analysis_block,
        )

    response = backend.generate(prompt, images=[before.read_bytes(), after.read_bytes()])
    parsed   = _parse_response(response)

    return {
        "task":     task,
        "overall":  parsed["overall"],
        "criteria": parsed["criteria"],
        "comment":  parsed["comment"],
        "response": response,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Step 2: produce rubric verdict from screenshots + Step 1 code analysis."
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--example", metavar="PATH",
                        help="Run on a single example folder (for testing).")
    target.add_argument("--dataset", default=str(_DATASET), metavar="PATH",
                        help=f"EvaluatorModelDataset directory (default: {_DATASET}).")

    parser.add_argument("--backend", default=_DEFAULT_BACKEND,
                        choices=["gemini", "vertexai", "anthropic", "openai"],
                        help=f"Model backend (default: {_DEFAULT_BACKEND}).")
    parser.add_argument("--model", default=None,
                        help="Override the model/endpoint (optional).")
    parser.add_argument("--no-step1", action="store_true",
                        help="Ablation: skip Step 1 code analysis and pass the raw HTML diff "
                             "directly to Step 2 instead.")
    parser.add_argument("--resume", action="store_true",
                        help="Skip examples already present in step2_results.json.")
    args = parser.parse_args()

    if args.example:
        folders = [Path(args.example)]
    else:
        folders = sorted(f for f in Path(args.dataset).iterdir() if f.is_dir())

    existing: dict = {}
    if args.resume and _OUTPUT_FILE.exists():
        existing = json.loads(_OUTPUT_FILE.read_text())
        print(f"Resuming: {len(existing)} done, {len(folders) - len(existing)} remaining")

    # Use _DEFAULT_MODEL as the gemini default when no --model override is given
    model   = args.model or (_DEFAULT_MODEL if args.backend == "gemini" else None)
    backend = get_backend(args.backend, model)
    print(f"Backend: {args.backend} | Model: {backend.model if hasattr(backend, 'model') else '—'}")
    print(f"Examples: {len(folders)}")

    results = dict(existing)
    n = len(folders)

    for i, folder in enumerate(folders, start=1):
        if args.resume and folder.name in existing:
            continue
        print(f"  [{i}/{n}] {folder.name} ... ", end="", flush=True)
        try:
            result = _run_one(folder, backend, no_step1=args.no_step1)
            if "error" in result:
                print(f"SKIP — {result['error']}")
            else:
                print(result["overall"])
            results[folder.name] = result
        except Exception as e:
            print(f"ERROR: {e}")
            results[folder.name] = {"error": str(e)}

        _OUTPUT_FILE.write_text(json.dumps(results, indent=2))

    print(f"\nDone. Results saved to {_OUTPUT_FILE.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
