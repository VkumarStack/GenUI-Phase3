"""
Step 2 of the two-step evaluation pipeline.

Inputs per example:
  - Task.txt                      — the original revision task
  - step1_spec.txt (optional)     — expected-change spec from Step 1
  - Before/screenshot.png         — original interface
  - After/screenshot.png          — revised interface
  - dom_diff.txt (optional)       — pre-computed DOM diff; computed on the fly if absent

Produces a structured rubric verdict (5 criteria + overall PASS/FAIL + comment).

Output: Evaluator/step2_results.json

Running:
    python Evaluator/step2.py

    # Run against the full EvaluatorModelDataset
    python Evaluator/step2.py --dataset Datasets/EvaluatorModelDataset

    # Ablation: omit DOM diff or Step 1 spec
    python Evaluator/step2.py --no-dom-diff
    python Evaluator/step2.py --no-step1
    python Evaluator/step2.py --no-dom-diff --no-step1

    # Run on a single example
    python Evaluator/step2.py --example Datasets/EvaluatorModelDataset/Participant_2_CaseStudy-1.1-CLAUDE

    # Resume a partially completed run
    python Evaluator/step2.py --resume

    # Use the fine-tuned evaluator model on Vertex AI
    python Evaluator/step2.py --backend vertexai
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

from dom_diff import dom_diff as compute_dom_diff

_DATASET = _ROOT / "Datasets" / "EvaluatorModelDataset"
_PROMPT_FILE = Path(__file__).parent / "step2_prompt.txt"
_OUTPUT_FILE = Path(__file__).parent / "step2_results.json"
_DEFAULT_BACKEND = "gemini"

# Patterns for parsing structured rubric output
_CRITERION_PATTERN = re.compile(
    r"^(REQUIREMENT FULFILLMENT|CONSISTENCY|VISUAL\s*&\s*USABILITY|MINIMALITY|NO REGRESSIONS)"
    r"\s*:\s*(PASS|PARTIAL PASS|FAIL)",
    re.IGNORECASE | re.MULTILINE,
)
_OVERALL_PATTERN = re.compile(r"^OVERALL\s*:\s*(PASS|FAIL)", re.IGNORECASE | re.MULTILINE)
_COMMENT_PATTERN = re.compile(r"^COMMENT\s*:\s*(.+)", re.IGNORECASE | re.DOTALL | re.MULTILINE)

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


def _resolve_paths(folder: Path) -> tuple[Path, Path, Path]:
    """Return (task_file, before_screenshot, after_screenshot)."""
    return (
        folder / "Task.txt",
        folder / "Before" / "screenshot.png",
        folder / "After" / "screenshot.png",
    )


def _get_dom_diff(folder: Path) -> str:
    cached = folder / "dom_diff.txt"
    if cached.exists():
        return cached.read_text()
    before_html = folder / "Before" / "index.html"
    after_html  = folder / "After"  / "index.html"
    if before_html.exists() and after_html.exists():
        return compute_dom_diff(before_html, after_html)
    return "(DOM diff unavailable — HTML files not found)"


def _get_step1_spec(folder: Path) -> str:
    spec_file = folder / "step1_spec.txt"
    if spec_file.exists():
        return spec_file.read_text().strip()
    return "(Step 1 spec unavailable — run fill_step1.py)"


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
        comment = comment_match.group(1).strip()
        # Trim if the model added extra lines after the comment
        comment = comment.split("\n\n")[0].strip()

    return {"criteria": criteria, "overall": overall, "comment": comment}


def _run_one(folder: Path, backend: Backend,
             no_dom_diff: bool = False, no_step1: bool = False) -> dict:
    task_file, before, after = _resolve_paths(folder)

    if not task_file.exists():
        return {"error": "Task.txt not found"}
    if not before.exists() or not after.exists():
        return {"error": "Missing before or after screenshot"}

    task = task_file.read_text().strip()

    # Build optional blocks
    if no_dom_diff:
        dom_diff_block = ""
    else:
        dom_diff_text  = _get_dom_diff(folder)
        dom_diff_block = _DOM_DIFF_HEADER + dom_diff_text + "\n\n---\n\n"

    if no_step1:
        step1_block = ""
    else:
        step1_text  = _get_step1_spec(folder)
        step1_block = f"UI Component Context (visual navigation aid — not additional requirements):\n{step1_text}\n\n---\n\n"

    prompt = _PROMPT_FILE.read_text().format(
        task=task,
        dom_diff_block=dom_diff_block,
        step1_block=step1_block,
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
        description="Step 2: produce rubric verdict from screenshots + optional DOM diff / Step 1 spec."
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
    parser.add_argument("--no-dom-diff", action="store_true",
                        help="Omit DOM diff from the prompt (ablation).")
    parser.add_argument("--no-step1", action="store_true",
                        help="Omit Step 1 spec from the prompt (ablation).")
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

    backend = get_backend(args.backend, args.model,
                          endpoint_env_var="VERTEXAI_EVALUATOR_ENDPOINT_ID")
    print(f"Backend:     {args.backend} | Model: {backend.model if hasattr(backend, 'model') else '—'}")
    print(f"DOM diff:    {'off' if args.no_dom_diff else 'on'}")
    print(f"Step 1 spec: {'off' if args.no_step1 else 'on'}")
    print(f"Examples:    {len(folders)}")

    results = dict(existing)
    n = len(folders)

    for i, folder in enumerate(folders, start=1):
        if args.resume and folder.name in existing:
            continue
        print(f"  [{i}/{n}] {folder.name} ... ", end="", flush=True)
        try:
            result = _run_one(folder, backend,
                              no_dom_diff=args.no_dom_diff,
                              no_step1=args.no_step1)
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
