"""
Build the CodeGenerationExperiment dataset.

For each of the 100 MUD_GenreUI screens, one revision task is sampled (same
seed as sample_tasks.py) and three models are asked to implement it.  Results
land in Datasets/CodeGenerationExperiment/:

    {screen_id}/
        Task.txt                — sampled revision task
        category.txt            — revision category
        Before/
            index.html          — original HTML
            screenshot.png      — rendered screenshot
        claude-haiku-4-5/
            index.html
            screenshot.png
        gemini-2.5-flash/
            index.html
            screenshot.png
        gpt-4.1-mini/
            index.html
            screenshot.png

Re-running is safe: already-completed model folders are skipped unless
--force is passed.

Usage:
    # Full run (all 3 models, all 100 screens)
    python CodeGeneration/build_dataset.py

    # One model only (useful for parallelism across terminals)
    python CodeGeneration/build_dataset.py --models claude-haiku-4-5

    # Resume after an interruption
    python CodeGeneration/build_dataset.py --resume

    # Different task sample
    python CodeGeneration/build_dataset.py --seed 42

    # Overwrite existing outputs
    python CodeGeneration/build_dataset.py --force
"""

import argparse
import csv
import json
import random
import sys
import warnings
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
sys.path.insert(0, str(Path(__file__).parent))

from backends import get_backend
from generate_core import generate_ui_change

_DATASET_SRC = _ROOT / "Datasets" / "MUD_GenreUI"
_DATASET_OUT = _ROOT / "Datasets" / "CodeGenerationExperiment"
_VIEWPORT = {"width": 375, "height": 812}
_DEFAULT_SEED = 0

MODELS = {
    "claude-haiku-4-5":  ("anthropic", "claude-haiku-4-5-20251001"),
    "gemini-2.5-flash":  ("gemini",    "gemini-2.5-flash"),
    "gpt-4.1-mini":      ("openai",    "gpt-4.1-mini"),
}


# ---------------------------------------------------------------------------
# Task sampling (mirrors sample_tasks.py)
# ---------------------------------------------------------------------------

def _load_screens() -> list[dict]:
    revisions = json.loads((_DATASET_SRC / "revisions.json").read_text())
    with (_DATASET_SRC / "results_final_100.csv").open() as f:
        metadata = {row["id"]: row for row in csv.DictReader(f)}

    screens = []
    for sid in sorted(revisions.keys(), key=int):
        rev  = revisions[sid]
        meta = metadata.get(sid, {})
        screens.append({
            "id":         sid,
            "html_path":  _DATASET_SRC / meta.get("html_path", f"html/{sid}.html"),
            "categories": rev.get("applicable_categories", []),
            "tasks":      rev.get("tasks", {}),
        })
    return screens


def _sample_task(screen: dict, rng: random.Random) -> tuple[str, str]:
    category = rng.choice(screen["categories"])
    task     = rng.choice(screen["tasks"][category])
    return category, task


# ---------------------------------------------------------------------------
# Screenshot rendering
# ---------------------------------------------------------------------------

def _render_screenshot(html_path: Path, out_path: Path, page) -> None:
    page.goto(html_path.resolve().as_uri())
    page.screenshot(path=str(out_path))


# ---------------------------------------------------------------------------
# Per-screen build
# ---------------------------------------------------------------------------

def _build_screen(screen: dict, category: str, task: str,
                  model_keys: list[str], force: bool, page) -> None:
    sid        = screen["id"]
    screen_dir = _DATASET_OUT / sid
    screen_dir.mkdir(parents=True, exist_ok=True)

    # --- Task files ---------------------------------------------------------
    (screen_dir / "Task.txt").write_text(task, encoding="utf-8")
    (screen_dir / "category.txt").write_text(category, encoding="utf-8")

    # --- Before -------------------------------------------------------------
    before_dir = screen_dir / "Before"
    before_dir.mkdir(exist_ok=True)
    before_html_src  = screen["html_path"]
    before_html_dest = before_dir / "index.html"
    before_shot      = before_dir / "screenshot.png"

    before_code = before_html_src.read_text(encoding="utf-8")
    before_html_dest.write_text(before_code, encoding="utf-8")

    if force or not before_shot.exists():
        _render_screenshot(before_html_dest, before_shot, page)

    # --- Model outputs ------------------------------------------------------
    for model_key in model_keys:
        model_dir = screen_dir / model_key
        out_html  = model_dir / "index.html"
        out_shot  = model_dir / "screenshot.png"

        if not force and out_html.exists() and out_shot.exists():
            print(f"    {model_key}: skip (already done)")
            continue

        model_dir.mkdir(exist_ok=True)
        backend_name, model_id = MODELS[model_key]
        backend = get_backend(backend_name, model_id)

        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                after_code = generate_ui_change(task, before_code, backend)
            for w in caught:
                print(f"    [{model_key}] warn: {w.message}")
        except Exception as e:
            print(f"    {model_key}: ERROR — {e}")
            (model_dir / "error.txt").write_text(str(e), encoding="utf-8")
            continue

        out_html.write_text(after_code, encoding="utf-8")
        _render_screenshot(out_html, out_shot, page)
        print(f"    {model_key}: done")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the CodeGenerationExperiment dataset."
    )
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED,
                        help=f"Random seed for task sampling (default: {_DEFAULT_SEED}).")
    parser.add_argument("--models", nargs="+", choices=list(MODELS),
                        default=list(MODELS),
                        help="Which models to run (default: all three).")
    parser.add_argument("--resume", action="store_true",
                        help="Alias for the default skip-if-exists behaviour (no-op, kept for clarity).")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing outputs.")
    parser.add_argument("--screens", nargs="+", metavar="ID",
                        help="Process only specific screen IDs (default: all 100).")
    args = parser.parse_args()

    rng     = random.Random(args.seed)
    screens = _load_screens()

    if args.screens:
        wanted  = set(args.screens)
        screens = [s for s in screens if s["id"] in wanted]
        if not screens:
            sys.exit(f"None of the requested screen IDs found: {args.screens}")

    samples = [(s, *_sample_task(s, rng)) for s in screens]

    _DATASET_OUT.mkdir(parents=True, exist_ok=True)
    print(f"Output:  {_DATASET_OUT.relative_to(_ROOT)}")
    print(f"Models:  {', '.join(args.models)}")
    print(f"Screens: {len(samples)}")
    print()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page    = browser.new_page(viewport=_VIEWPORT)

        for i, (screen, category, task) in enumerate(samples, 1):
            print(f"[{i:>3}/{len(samples)}] Screen {screen['id']}  ({category})")
            _build_screen(screen, category, task, args.models, args.force, page)

        browser.close()

    print(f"\nDone — dataset at {_DATASET_OUT.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
