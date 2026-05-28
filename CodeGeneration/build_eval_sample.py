"""
Sample one model per screen from CodeGenerationExperiment and run the full
evaluation pipeline (html_diff → step1 → step2) on each.

For each screen, one of the three model variants is picked at random (seeded).
Files are copied to Datasets/CodeGenEvalSample/{screen_id}_{model_key}/ and
the pipeline is run in place.

Output folder structure:
  {screen_id}_{model_key}/
    Task.txt, category.txt
    Before/index.html, Before/screenshot.png
    After/index.html, After/screenshot.png   ← from the model subfolder
    html_diff.txt
    step1_spec.txt
    eval_result.json

Running:
    python CodeGeneration/build_eval_sample.py
    python CodeGeneration/build_eval_sample.py --seed 42 --force
    python CodeGeneration/build_eval_sample.py --backend gemini --model gemini-3.1-pro-preview
"""

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
sys.path.insert(0, str(_ROOT / "Evaluator"))

from backends import get_backend
from html_diff import html_diff as compute_html_diff
from step1 import run_one as step1_run_one
from step2 import _run_one as step2_run_one

_SOURCE = _ROOT / "Datasets" / "CodeGenerationExperiment"
_OUTPUT = _ROOT / "Datasets" / "CodeGenEvalSample"
_MODELS = ["claude-haiku-4-5", "gemini-2.5-flash", "gpt-4.1-mini"]
_DEFAULT_MODEL = "gemini-3.1-pro-preview"


def _copy_screen(screen_dir: Path, model_key: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for fname in ("Task.txt", "category.txt"):
        src = screen_dir / fname
        if src.exists():
            shutil.copy2(src, dest / fname)

    before_dest = dest / "Before"
    before_dest.mkdir(exist_ok=True)
    for fname in ("index.html", "screenshot.png"):
        src = screen_dir / "Before" / fname
        if src.exists():
            shutil.copy2(src, before_dest / fname)

    after_dest = dest / "After"
    after_dest.mkdir(exist_ok=True)
    for fname in ("index.html", "screenshot.png"):
        src = screen_dir / model_key / fname
        if src.exists():
            shutil.copy2(src, after_dest / fname)


def main():
    parser = argparse.ArgumentParser(
        description="Build CodeGenEvalSample: sample 1 model per screen and run the evaluator."
    )
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for model selection (default: 42).")
    parser.add_argument("--backend", default="gemini",
                        choices=["gemini", "vertexai", "anthropic", "openai"])
    parser.add_argument("--model", default=None,
                        help="Override evaluator model (default for gemini: gemini-3.1-pro-preview).")
    parser.add_argument("--force", action="store_true",
                        help="Re-evaluate even if eval_result.json already exists.")
    parser.add_argument("--output", default=str(_OUTPUT), metavar="PATH",
                        help=f"Output dataset directory (default: {_OUTPUT}).")
    args = parser.parse_args()

    model   = args.model or (_DEFAULT_MODEL if args.backend == "gemini" else None)
    backend = get_backend(args.backend, model)
    output  = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    screen_dirs = sorted(d for d in _SOURCE.iterdir() if d.is_dir())

    print(f"Screens:  {len(screen_dirs)}")
    print(f"Output:   {output}")
    print(f"Backend:  {args.backend} | Model: {getattr(backend, 'model', '—')}")
    print()

    done = errors = skipped = 0
    n = len(screen_dirs)

    for i, screen_dir in enumerate(screen_dirs, 1):
        available = [m for m in _MODELS
                     if (screen_dir / m / "index.html").exists()
                     and (screen_dir / m / "screenshot.png").exists()]
        if not available:
            print(f"  [{i:>3}/{n}] {screen_dir.name}  SKIP — no model outputs")
            errors += 1
            continue

        model_key   = rng.choice(available)
        dest        = output / f"{screen_dir.name}_{model_key}"
        result_file = dest / "eval_result.json"

        if result_file.exists() and not args.force:
            print(f"  [{i:>3}/{n}] {screen_dir.name}_{model_key}  already done, skip")
            skipped += 1
            continue

        print(f"  [{i:>3}/{n}] {screen_dir.name} → {model_key} ... ", end="", flush=True)

        try:
            _copy_screen(screen_dir, model_key, dest)

            # Compute + cache html diff
            diff_cache = dest / "html_diff.txt"
            if not diff_cache.exists() or args.force:
                before_html = dest / "Before" / "index.html"
                after_html  = dest / "After"  / "index.html"
                if before_html.exists() and after_html.exists():
                    diff_text = compute_html_diff(before_html, after_html)
                else:
                    diff_text = "(HTML diff unavailable)"
                diff_cache.write_text(diff_text, encoding="utf-8")

            # Step 1: code analysis
            spec_file = dest / "step1_spec.txt"
            if not spec_file.exists() or args.force:
                s1 = step1_run_one(dest, backend)
                if "error" in s1:
                    raise RuntimeError(f"step1: {s1['error']}")
                spec_file.write_text(s1["code_analysis"], encoding="utf-8")

            # Step 2: rubric verdict
            s2 = step2_run_one(dest, backend)
            result_file.write_text(json.dumps({
                "screen_id":  screen_dir.name,
                "model_key":  model_key,
                "overall":    s2.get("overall"),
                "criteria":   s2.get("criteria"),
                "comment":    s2.get("comment"),
                "response":   s2.get("response"),
                "error":      s2.get("error"),
                "eval_model": getattr(backend, "model", args.backend),
            }, indent=2), encoding="utf-8")

            print(s2.get("overall") or "ERROR")
            done += 1

        except Exception as e:
            print(f"ERROR: {e}")
            errors += 1

    print(f"\nDone.  Evaluated: {done}  Skipped: {skipped}  Errors: {errors}")
    print(f"Dataset: {output}")


if __name__ == "__main__":
    main()
