"""
Build the CodeGenerationExperimentv2 dataset (full-HTML generation).

This is the v2 variant of CodeGeneration/build_dataset.py. Instead of search-
and-replace edits, each model outputs the COMPLETE updated HTML document; if the
output does not parse as a complete HTML file, the call is retried (up to three
times).

Tasks are drawn from the existing Datasets/CodeGenerationExperiment/ dataset:
each screen folder there supplies a fixed Task.txt, category.txt, and
Before/index.html. The v1 model implementation subfolders (claude-haiku-4-5,
gemini-2.5-flash, gpt-4.1-mini) are ignored — only the task and before state are
reused, so v1 and v2 run on identical tasks. The model registry is reused from
the v1 build_dataset module.

Outputs land in Datasets/CodeGenerationExperimentv2/:

    {screen_id}/
        Task.txt
        category.txt
        Before/
            index.html
            screenshot.png
        {model_key}/
            index.html                 (best attempt; present even when invalid)
            screenshot.png             (only when a valid document was produced)
            generation_failed.json     (only when all retries failed)

Run metadata is saved to CodeGeneration/Experimentv2/Results/{run_name}.json.
Invalid HTML cases (all retries exhausted) are saved to
CodeGeneration/Experimentv2/Results/invalid_{run_name}/ for inspection.

Usage:
    python CodeGeneration/Experimentv2/build_dataset.py
    python CodeGeneration/Experimentv2/build_dataset.py --screens 20 --seed 42
    python CodeGeneration/Experimentv2/build_dataset.py --models claude-haiku-4-5 gpt-4.1-mini
    python CodeGeneration/Experimentv2/build_dataset.py --screen-ids 12356 --models llama-3.3-70b --force
"""

import argparse
import importlib.util
import json
import random
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

_ROOT    = Path(__file__).parent.parent.parent
_CODEGEN = Path(__file__).parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
sys.path.insert(0, str(_CODEGEN))
sys.path.insert(0, str(Path(__file__).parent))

from backends import get_backend
from generate_full import generate_full_html
from generate_core import generate_with_result  # v1 search-and-replace generation

# Load the v1 build_dataset under a unique module name to reuse its model
# registry. Loading by explicit file path avoids the name collision with this
# v2 file (both are named build_dataset.py).
_v1_spec = importlib.util.spec_from_file_location(
    "codegen_v1_build_dataset", _CODEGEN / "build_dataset.py"
)
_v1 = importlib.util.module_from_spec(_v1_spec)
_v1_spec.loader.exec_module(_v1)
MODELS = _v1.MODELS

_SOURCE_EXP  = _ROOT / "Datasets" / "CodeGenerationExperiment"
_DATASET_OUT = _ROOT / "Datasets" / "CodeGenerationExperimentv2"
_RESULTS_DIR = Path(__file__).parent / "Results"
_VIEWPORT    = {"width": 375, "height": 812}
_DEFAULT_SEED    = 0
_DEFAULT_SCREENS = 10
_MAX_RETRIES     = 3
_DEFAULT_WORKERS = 8

_ALL_MODEL_KEYS = list(MODELS)


# ---------------------------------------------------------------------------
# Task source: existing CodeGenerationExperiment screens (fixed tasks)
# ---------------------------------------------------------------------------

def _load_experiment_screens() -> list[dict]:
    """Load screens (with their fixed task) from Datasets/CodeGenerationExperiment/.

    Each screen contributes its Task.txt, category.txt, and Before/index.html.
    The v1 model implementation subfolders are ignored. Sorted by numeric id.
    """
    screens = []
    for d in sorted(_SOURCE_EXP.iterdir(),
                    key=lambda p: int(p.name) if p.name.isdigit() else p.name):
        if not d.is_dir():
            continue
        task_file   = d / "Task.txt"
        before_html = d / "Before" / "index.html"
        if not task_file.exists() or not before_html.exists():
            continue
        cat_file = d / "category.txt"
        screens.append({
            "id":         d.name,
            "html_path":  before_html,
            "screenshot": d / "Before" / "screenshot.png",
            "task":       task_file.read_text(encoding="utf-8").strip(),
            "category":   cat_file.read_text(encoding="utf-8").strip() if cat_file.exists() else "",
        })
    return screens


# ---------------------------------------------------------------------------
# Screenshot rendering
# ---------------------------------------------------------------------------

def _render_screenshot(html_path: Path, out_path: Path, page) -> None:
    page.goto(html_path.resolve().as_uri())
    page.screenshot(path=str(out_path))


# ---------------------------------------------------------------------------
# Per-screen build
# ---------------------------------------------------------------------------

# The build runs in three phases so that the network-bound generation can be
# parallelized while the (thread-unsafe) Playwright rendering stays sequential:
#   1. _prepare_screen  — write Before state, ensure the Before screenshot.
#   2. _generate_variant — call the model (thread-safe; run in a thread pool).
#   3. _finalize_variant — write HTML and render the After screenshot (Playwright).


def _prepare_screen(screen: dict, category: str, task: str, page, force: bool) -> dict:
    """Phase 1: write the Before state for one screen and load its screenshot bytes."""
    sid        = screen["id"]
    screen_dir = _DATASET_OUT / sid
    screen_dir.mkdir(parents=True, exist_ok=True)

    (screen_dir / "Task.txt").write_text(task, encoding="utf-8")
    (screen_dir / "category.txt").write_text(category, encoding="utf-8")

    before_dir = screen_dir / "Before"
    before_dir.mkdir(exist_ok=True)
    before_html_dest = before_dir / "index.html"
    before_shot      = before_dir / "screenshot.png"
    before_code = screen["html_path"].read_text(encoding="utf-8")
    before_html_dest.write_text(before_code, encoding="utf-8")

    if force or not before_shot.exists():
        src_shot = screen.get("screenshot")
        if src_shot and Path(src_shot).exists():
            shutil.copy2(src_shot, before_shot)       # reuse the existing v1 render
        else:
            _render_screenshot(before_html_dest, before_shot, page)

    before_img_bytes = before_shot.read_bytes() if before_shot.exists() else None
    return {
        "sid":              sid,
        "screen_dir":       screen_dir,
        "task":             task,
        "before_code":      before_code,
        "before_img_bytes": before_img_bytes,
    }


def _generate_variant(prep: dict, variant: tuple, force: bool,
                      use_search_replace: bool = False) -> dict:
    """Phase 2: generate one model variant's HTML (no Playwright; thread-safe).

    Uses full-HTML output by default; when use_search_replace is True, falls
    back to the v1 search-and-replace generation (useful on reruns to fill in
    invalid/error entries).
    """
    sid = prep["sid"]
    variant_key, backend_name, model_id, use_vision = variant
    model_dir = prep["screen_dir"] / variant_key
    out_html  = model_dir / "index.html"
    out_shot  = model_dir / "screenshot.png"

    base = {"screen_id": sid, "model_key": variant_key}

    if not force and out_html.exists() and out_shot.exists():
        return {**base, "status": "SKIP", "n_attempts": 0,
                "last_response": None, "_html": None, "_attempts": []}

    gen_fn = generate_with_result if use_search_replace else generate_full_html
    try:
        backend = get_backend(backend_name, model_id)
        screenshot_input = prep["before_img_bytes"] if use_vision else None
        result = gen_fn(
            prep["task"], prep["before_code"], backend,
            screenshot_bytes=screenshot_input,
            max_retries=_MAX_RETRIES,
        )
    except Exception as e:
        return {**base, "status": "ERROR", "n_attempts": 0,
                "last_response": str(e), "_html": None, "_attempts": []}

    # Both generators expose success/html/n_attempts/attempts; search-replace
    # additionally exposes used_fallback (a recovered full-HTML response).
    ok            = result["success"] or result.get("used_fallback", False)
    status        = "OK" if ok else "INVALID"
    last_response = result["attempts"][-1]["response"] if result["attempts"] else ""
    return {**base, "status": status, "n_attempts": result["n_attempts"],
            "last_response": last_response,
            "_html": result["html"], "_attempts": result["attempts"]}


def _finalize_variant(prep: dict, variant: tuple, gen: dict, page) -> tuple[dict, dict | None]:
    """Phase 3: persist a generated variant and render its After screenshot.

    Returns (output_record, invalid_record_or_None).
    """
    sid         = prep["sid"]
    variant_key = variant[0]
    model_dir   = prep["screen_dir"] / variant_key
    status      = gen["status"]

    output_record = {
        "screen_id":     sid,
        "model_key":     variant_key,
        "status":        status,
        "n_attempts":    gen["n_attempts"],
        "last_response": gen["last_response"],
    }

    if status == "SKIP":
        return output_record, None

    model_dir.mkdir(exist_ok=True)
    out_html = model_dir / "index.html"
    out_shot = model_dir / "screenshot.png"

    # Clear stale failure indicators from any prior run so the folder reflects
    # only this run's outcome (otherwise a regenerated-OK variant keeps a stale
    # generation_failed.json and the auto-evaluator treats it as failed).
    for stale in ("generation_failed.json", "error.txt"):
        sp = model_dir / stale
        if sp.exists():
            sp.unlink()

    if status == "ERROR":
        (model_dir / "error.txt").write_text(gen["last_response"] or "", encoding="utf-8")
        if out_shot.exists():        # drop a stale screenshot from a prior OK run
            out_shot.unlink()
        return output_record, {**output_record, "task": prep["task"], "attempts": []}

    # OK or INVALID: always write the best HTML; render only when valid.
    out_html.write_text(gen["_html"] or "", encoding="utf-8")
    if status == "OK":
        _render_screenshot(out_html, out_shot, page)
        return output_record, None

    if out_shot.exists():            # INVALID: drop a stale screenshot from a prior OK run
        out_shot.unlink()
    (model_dir / "generation_failed.json").write_text(
        json.dumps({"status": status, "n_attempts": gen["n_attempts"]}, indent=2),
        encoding="utf-8",
    )
    invalid_record = {
        **output_record,
        "task": prep["task"],
        "attempts": [
            {k: v for k, v in a.items() if k != "response"}
            for a in gen["_attempts"]
        ],
        "before_html": prep["before_code"],
    }
    return output_record, invalid_record


# ---------------------------------------------------------------------------
# Model variant expansion (vision ablation)
# ---------------------------------------------------------------------------

def _expand_variants(model_keys: list[str], vision_ablation: bool) -> list[tuple]:
    """Expand base model keys into run variants.

    Each variant is (variant_key, backend_name, model_id, use_vision).

    For a vision-capable model, when vision_ablation is on, two variants are
    produced: the normal one (with the before screenshot) and a "{key}-novision"
    one (text only). Text-only models always produce a single variant.
    """
    variants: list[tuple] = []
    for mk in model_keys:
        backend_name, model_id, supports_vision = MODELS[mk]
        if supports_vision:
            variants.append((mk, backend_name, model_id, True))
            if vision_ablation:
                variants.append((f"{mk}-novision", backend_name, model_id, False))
        else:
            variants.append((mk, backend_name, model_id, False))
    return variants


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the CodeGenerationExperimentv2 dataset (full-HTML generation)."
    )
    parser.add_argument("--screens", type=int, default=_DEFAULT_SCREENS,
                        help=f"Number of screens to sample from CodeGenerationExperiment "
                             f"(default: {_DEFAULT_SCREENS}; use 0 or --all for every screen).")
    parser.add_argument("--all", action="store_true",
                        help="Process every screen in CodeGenerationExperiment.")
    parser.add_argument("--screen-ids", nargs="+", metavar="ID",
                        help="Process only these specific screen IDs (skips random sampling).")
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED,
                        help=f"Random seed for screen subset selection (default: {_DEFAULT_SEED}).")
    parser.add_argument("--models", nargs="+", choices=_ALL_MODEL_KEYS,
                        default=_ALL_MODEL_KEYS,
                        help="Models to run (default: all).")
    parser.add_argument("--no-vision-ablation", action="store_true",
                        help="Disable the vision ablation. By default, each vision-capable "
                             "model is run twice — with the before screenshot and as a "
                             "text-only '{model}-novision' variant.")
    parser.add_argument("--workers", type=int, default=_DEFAULT_WORKERS,
                        help=f"Parallel generation workers across providers "
                             f"(default: {_DEFAULT_WORKERS}; use 1 for sequential).")
    parser.add_argument("--search-replace", action="store_true",
                        help="Use v1 search-and-replace generation instead of full-HTML "
                             "output. Useful on a rerun (without --force) to fill in "
                             "invalid/error entries that full-HTML generation missed.")
    parser.add_argument("--run-name", default=None,
                        help="Output run name (default: run_{seed}_{screens}screens).")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing outputs.")
    args = parser.parse_args()

    rng     = random.Random(args.seed)
    screens = _load_experiment_screens()
    if not screens:
        sys.exit(f"No screens with Task.txt + Before/index.html found in {_SOURCE_EXP}")

    if args.screen_ids:
        wanted  = set(args.screen_ids)
        sampled = [s for s in screens if s["id"] in wanted]
        if not sampled:
            sys.exit(f"None of the requested screen IDs found: {args.screen_ids}")
    elif args.all or args.screens <= 0:
        sampled = screens
    else:
        sampled = rng.sample(screens, min(args.screens, len(screens)))

    # Each screen carries its fixed task/category from CodeGenerationExperiment.
    samples = [(s, s["category"], s["task"]) for s in sampled]

    # Expand models into run variants (vision ablation on by default).
    vision_ablation = not args.no_vision_ablation
    variants        = _expand_variants(args.models, vision_ablation)
    variant_keys    = [v[0] for v in variants]

    run_name = args.run_name or f"run_{args.seed}_{args.screens}screens"
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    invalid_dir = _RESULTS_DIR / f"invalid_{run_name}"

    _DATASET_OUT.mkdir(parents=True, exist_ok=True)
    print(f"Output:   {_DATASET_OUT.relative_to(_ROOT)}")
    print(f"Tasks:    {_SOURCE_EXP.relative_to(_ROOT)} (fixed tasks; v1 implementations ignored)")
    print(f"Run:      {run_name}")
    _mode = "search-and-replace" if args.search_replace else "full-HTML generation"
    print(f"Mode:     {_mode} (retry up to {_MAX_RETRIES}x on invalid output)")
    print(f"Vision ablation: {'on' if vision_ablation else 'off'}  "
          f"({len(variant_keys)} variants from {len(args.models)} models)")
    print(f"Variants: {', '.join(variant_keys)}")
    print(f"Screens:  {len(samples)}")
    print(f"Workers:  {args.workers}")
    print()

    all_outputs: list[dict] = []
    all_invalid: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page    = browser.new_page(viewport=_VIEWPORT)

        # Phase 1: prepare every screen's Before state (sequential; uses Playwright).
        print(f"Preparing {len(samples)} screen(s) ...")
        preps = [_prepare_screen(screen, category, task, page, args.force)
                 for screen, category, task in samples]

        # Phase 2: generate all (screen × variant) outputs in parallel (network-bound).
        jobs = [(prep, variant) for prep in preps for variant in variants]
        print(f"Generating {len(jobs)} outputs across {args.workers} worker(s) ...")
        gen_results: dict[tuple, dict] = {}
        done = 0
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            fut_map = {
                ex.submit(_generate_variant, prep, variant, args.force,
                          args.search_replace): (prep, variant)
                for prep, variant in jobs
            }
            for fut in as_completed(fut_map):
                gen = fut.result()
                gen_results[(gen["screen_id"], gen["model_key"])] = gen
                done += 1
                print(f"  [{done:>4}/{len(jobs)}] {gen['screen_id']} / {gen['model_key']}: "
                      f"{gen['status']}", flush=True)

        # Phase 3: persist HTML + render After screenshots (sequential; uses Playwright).
        print("Rendering screenshots ...")
        for prep in preps:
            for variant in variants:
                gen = gen_results[(prep["sid"], variant[0])]
                out_rec, inv_rec = _finalize_variant(prep, variant, gen, page)
                all_outputs.append(out_rec)
                if inv_rec is not None:
                    all_invalid.append(inv_rec)

        browser.close()

    # Save invalid records
    if all_invalid:
        invalid_dir.mkdir(parents=True, exist_ok=True)
        for rec in all_invalid:
            fname = f"{rec['screen_id']}_{rec['model_key']}.json"
            (invalid_dir / fname).write_text(json.dumps(rec, indent=2), encoding="utf-8")
        print(f"\n{len(all_invalid)} invalid case(s) saved to {invalid_dir.relative_to(_ROOT)}")

    # Save run metadata — includes per-variant outputs with raw responses.
    # "models" holds the variant keys (incl. any -novision) so downstream eval
    # and inspection iterate every variant; "base_models" keeps the originals.
    run_meta = {
        "run_name":        run_name,
        "mode":            "search_replace" if args.search_replace else "full_html",
        "seed":            args.seed,
        "n_screens":       len(samples),
        "models":          variant_keys,
        "base_models":     args.models,
        "vision_ablation": vision_ablation,
        "timestamp":       datetime.now(timezone.utc).isoformat(),
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
