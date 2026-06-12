"""
Build the CodeGenerationExperiment dataset.

For a randomly sampled set of MUD_GenreUI screens, one revision task is picked
per screen and each configured model is asked to implement it via search-replace
code generation.  Results land in Datasets/CodeGenerationExperiment/:

    {screen_id}/
        Task.txt
        category.txt
        Before/
            index.html
            screenshot.png
        {model_key}/
            index.html
            screenshot.png      (absent if generation failed entirely)
            generation_failed.json  (present only when all retries failed)

Run metadata is saved to CodeGeneration/Results/{run_name}.json so that
build_eval_sample.py can pick up exactly the same screens.

Failed search-replace cases (all retries exhausted) are saved to
CodeGeneration/Results/invalid_{run_name}/ for manual inspection.

Usage:
    # Default: 10 random screens, all models
    python CodeGeneration/build_dataset.py

    # Custom screen count and seed
    python CodeGeneration/build_dataset.py --screens 20 --seed 42

    # One or more models only
    python CodeGeneration/build_dataset.py --models claude-haiku-4-5 gpt-4.1-mini

    # Override the output run name
    python CodeGeneration/build_dataset.py --run-name my_run

    # Overwrite existing outputs
    python CodeGeneration/build_dataset.py --force
"""

import argparse
import csv
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
sys.path.insert(0, str(Path(__file__).parent))

from backends import get_backend
from generate_core import generate_with_result

_DATASET_SRC = _ROOT / "Datasets" / "MUD_GenreUI"
_DATASET_OUT = _ROOT / "Datasets" / "CodeGenerationExperiment"
_RESULTS_DIR = Path(__file__).parent / "Results"
_VIEWPORT    = {"width": 375, "height": 812}
_DEFAULT_SEED    = 0
_DEFAULT_SCREENS = 10
_MAX_RETRIES     = 3

# ---------------------------------------------------------------------------
# Model registry
# Each entry: model_key -> (backend_name, model_id, supports_vision)
# ---------------------------------------------------------------------------

MODELS: dict[str, tuple[str, str, bool]] = {
    # Small models
    "claude-haiku-4-5":    ("anthropic",   "claude-haiku-4-5-20251001",                          True),
    "gemini-2.5-flash":    ("gemini",      "gemini-2.5-flash",                                   True),
    "gpt-4.1-mini":        ("openai",      "gpt-4.1-mini",                                       True),
    "deepseek-v3":         ("deepseek",    "deepseek-chat",                                      False),
    "qwen3.5-9b":          ("together",    "Qwen/Qwen3.5-9B",                                True),
    # Large models
    "claude-sonnet-4-5":   ("anthropic",   "claude-sonnet-4-5",                                  True),
    "gemini-2.5-pro":      ("gemini",      "gemini-2.5-pro",                                     True),
    "gpt-4.1":             ("openai",      "gpt-4.1",                                            True),
    "llama-3.3-70b":       ("together",    "meta-llama/Llama-3.3-70B-Instruct-Turbo",            False),
    "qwen3.5-397b":        ("together",    "Qwen/Qwen3.5-397B-A17B",                         True),
}

_ALL_MODEL_KEYS = list(MODELS)


# ---------------------------------------------------------------------------
# Task sampling
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
            "screenshot": _DATASET_SRC / f"screenshots/{sid}.png",
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

def _build_screen(
    screen: dict, category: str, task: str,
    model_keys: list[str], force: bool, page,
) -> tuple[list[dict], list[dict]]:
    """Build one screen for all requested models.

    Returns (output_records, invalid_records).
    output_records: one entry per model with status + last_response (always).
    invalid_records: subset of output_records where status != OK, for separate saving.
    """
    sid        = screen["id"]
    screen_dir = _DATASET_OUT / sid
    screen_dir.mkdir(parents=True, exist_ok=True)

    (screen_dir / "Task.txt").write_text(task, encoding="utf-8")
    (screen_dir / "category.txt").write_text(category, encoding="utf-8")

    # Before -------------------------------------------------------------------
    before_dir  = screen_dir / "Before"
    before_dir.mkdir(exist_ok=True)
    before_html_dest = before_dir / "index.html"
    before_shot      = before_dir / "screenshot.png"
    before_code = screen["html_path"].read_text(encoding="utf-8")
    before_html_dest.write_text(before_code, encoding="utf-8")
    if force or not before_shot.exists():
        _render_screenshot(before_html_dest, before_shot, page)

    # Load before screenshot bytes for vision models
    before_img_bytes: bytes | None = None
    if before_shot.exists():
        before_img_bytes = before_shot.read_bytes()

    output_records:  list[dict] = []
    invalid_records: list[dict] = []

    # Model outputs ------------------------------------------------------------
    for model_key in model_keys:
        model_dir = screen_dir / model_key
        out_html  = model_dir / "index.html"
        out_shot  = model_dir / "screenshot.png"

        if not force and out_html.exists() and out_shot.exists():
            print(f"    {model_key}: skip")
            output_records.append({
                "screen_id": sid, "model_key": model_key,
                "status": "SKIP", "n_attempts": 0, "last_response": None,
            })
            continue

        model_dir.mkdir(exist_ok=True)
        backend_name, model_id, supports_vision = MODELS[model_key]
        backend = get_backend(backend_name, model_id)
        screenshot_input = before_img_bytes if supports_vision else None

        try:
            result = generate_with_result(
                task, before_code, backend,
                screenshot_bytes=screenshot_input,
                max_retries=_MAX_RETRIES,
            )
        except Exception as e:
            print(f"    {model_key}: ERROR — {e}")
            (model_dir / "error.txt").write_text(str(e), encoding="utf-8")
            rec = {
                "screen_id": sid, "model_key": model_key,
                "status": "ERROR", "n_attempts": 0,
                "last_response": str(e),
            }
            output_records.append(rec)
            invalid_records.append({**rec, "task": task, "attempts": []})
            continue

        if not result["success"] and not result["used_fallback"]:
            status = "INVALID"
        elif result["used_fallback"]:
            status = "FALLBACK"
        else:
            status = "OK"

        last_response = result["attempts"][-1]["response"] if result["attempts"] else ""

        out_html.write_text(result["html"], encoding="utf-8")
        if status in ("OK", "FALLBACK"):
            _render_screenshot(out_html, out_shot, page)
            # Remove any stale sentinel left by a previous failed run.
            stale = model_dir / "generation_failed.json"
            if stale.exists():
                stale.unlink()

        rec = {
            "screen_id":     sid,
            "model_key":     model_key,
            "status":        status,
            "n_attempts":    result["n_attempts"],
            "last_response": last_response,
        }
        output_records.append(rec)

        if status != "OK":
            (model_dir / "generation_failed.json").write_text(
                json.dumps({"status": status, "n_attempts": result["n_attempts"]}, indent=2),
                encoding="utf-8",
            )
            invalid_records.append({
                **rec,
                "task": task,
                "attempts": [
                    {k: v for k, v in a.items() if k != "response"}
                    for a in result["attempts"]
                ],
                "before_html": before_code,
            })
            print(f"    {model_key}: {status} ({result['n_attempts']} attempt(s))")
        else:
            print(f"    {model_key}: OK")

    return output_records, invalid_records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the CodeGenerationExperiment dataset."
    )
    parser.add_argument("--screens", type=int, default=_DEFAULT_SCREENS,
                        help=f"Number of MUD screens to sample (default: {_DEFAULT_SCREENS}).")
    parser.add_argument("--screen-ids", nargs="+", metavar="ID",
                        help="Process only these specific screen IDs (skips random sampling).")
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED,
                        help=f"Random seed for screen + task sampling (default: {_DEFAULT_SEED}).")
    parser.add_argument("--models", nargs="+", choices=_ALL_MODEL_KEYS,
                        default=_ALL_MODEL_KEYS,
                        help="Models to run (default: all).")
    parser.add_argument("--run-name", default=None,
                        help="Output run name (default: run_{seed}_{screens}screens).")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing outputs.")
    args = parser.parse_args()

    rng     = random.Random(args.seed)
    screens = _load_screens()

    if args.screen_ids:
        wanted  = set(args.screen_ids)
        screens = [s for s in screens if s["id"] in wanted]
        if not screens:
            sys.exit(f"None of the requested screen IDs found: {args.screen_ids}")
        sampled = screens
    else:
        sampled = rng.sample(screens, min(args.screens, len(screens)))

    samples = [(s, *_sample_task(s, rng)) for s in sampled]

    run_name = args.run_name or f"run_{args.seed}_{args.screens}screens"
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    invalid_dir = _RESULTS_DIR / f"invalid_{run_name}"

    _DATASET_OUT.mkdir(parents=True, exist_ok=True)
    print(f"Output:   {_DATASET_OUT.relative_to(_ROOT)}")
    print(f"Run:      {run_name}")
    print(f"Models:   {', '.join(args.models)}")
    print(f"Screens:  {len(samples)}")
    print()

    all_outputs: list[dict] = []
    all_invalid: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page    = browser.new_page(viewport=_VIEWPORT)

        for i, (screen, category, task) in enumerate(samples, 1):
            print(f"[{i:>3}/{len(samples)}] Screen {screen['id']}  ({category})")
            outputs, invalid = _build_screen(
                screen, category, task, args.models, args.force, page,
            )
            all_outputs.extend(outputs)
            all_invalid.extend(invalid)

        browser.close()

    # Save invalid records
    if all_invalid:
        invalid_dir.mkdir(parents=True, exist_ok=True)
        for rec in all_invalid:
            fname = f"{rec['screen_id']}_{rec['model_key']}.json"
            (invalid_dir / fname).write_text(json.dumps(rec, indent=2), encoding="utf-8")
        print(f"\n{len(all_invalid)} invalid/fallback case(s) saved to {invalid_dir.relative_to(_ROOT)}")

    # Save run metadata — includes per-model outputs with raw responses
    run_meta = {
        "run_name":  run_name,
        "seed":      args.seed,
        "n_screens": len(samples),
        "models":    args.models,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sampled": [
            {"screen_id": s["id"], "category": cat, "task": task}
            for s, cat, task in samples
        ],
        "outputs": all_outputs,
    }
    run_file = _RESULTS_DIR / f"{run_name}.json"
    run_file.write_text(json.dumps(run_meta, indent=2), encoding="utf-8")
    print(f"Run metadata saved to {run_file.relative_to(_ROOT)}")
    print(f"\nDone — dataset at {_DATASET_OUT.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
