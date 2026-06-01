"""
Run the auto-evaluator pipeline on CodeGenerationExperiment outputs.

Two modes:

  1. From a run results file (recommended):
     Pass --run CodeGeneration/Results/{run_name}.json to evaluate every
     (screen, model) pair from that dataset build run.  Per-model accuracy
     is computed and saved to CodeGeneration/Results/eval_{run_name}.json.

  2. Standalone (legacy): randomly samples one model per screen from
     Datasets/CodeGenerationExperiment/ (no per-model accuracy report).

For each example, files are copied to Datasets/CodeGenEvalSample/ and the
html_diff → step1 → step2 pipeline is run in place.  Already-evaluated
examples are skipped unless --force is passed.

Output folder structure per example:
    {screen_id}_{model_key}/
        Task.txt, category.txt
        Before/index.html, Before/screenshot.png
        After/index.html, After/screenshot.png
        html_diff.txt
        step1_spec.txt
        eval_result.json

Usage:
    # Evaluate a specific build run (all models for those screens)
    python CodeGeneration/build_eval_sample.py --run CodeGeneration/Results/run_0_10screens.json

    # Force re-evaluation
    python CodeGeneration/build_eval_sample.py --run ... --force

    # Standalone random sample (legacy)
    python CodeGeneration/build_eval_sample.py --seed 42
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
sys.path.insert(0, str(_ROOT / "Evaluator"))
sys.path.insert(0, str(Path(__file__).parent))

from backends import get_backend
from html_diff import html_diff as compute_html_diff
from step1 import run_one as step1_run_one
from step2 import _run_one as step2_run_one
from build_dataset import MODELS as _MODEL_REGISTRY

_SOURCE      = _ROOT / "Datasets" / "CodeGenerationExperiment"
_OUTPUT      = _ROOT / "Datasets" / "CodeGenEvalSample"
_RESULTS_DIR = Path(__file__).parent / "Results"
_EVAL_MODEL  = "gemini-3.1-pro-preview"


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

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


def _evaluate_one(screen_id: str, model_key: str, backend, force: bool) -> dict:
    """Evaluate one (screen, model) pair. Returns the eval_result dict."""
    screen_dir  = _SOURCE / screen_id
    dest        = _OUTPUT / f"{screen_id}_{model_key}"
    result_file = dest / "eval_result.json"

    # Check if generation failed (no usable After HTML)
    gen_failed = (screen_dir / model_key / "generation_failed.json").exists()
    after_html  = screen_dir / model_key / "index.html"
    after_shot  = screen_dir / model_key / "screenshot.png"
    if gen_failed or not after_html.exists() or not after_shot.exists():
        return {"screen_id": screen_id, "model_key": model_key,
                "overall": "FAIL", "criteria": {}, "comment": "Generation failed — no valid output.",
                "error": "generation_failed", "eval_model": None}

    if result_file.exists() and not force:
        return json.loads(result_file.read_text(encoding="utf-8"))

    _copy_screen(screen_dir, model_key, dest)

    # html_diff
    diff_cache = dest / "html_diff.txt"
    if not diff_cache.exists() or force:
        bh = dest / "Before" / "index.html"
        ah = dest / "After"  / "index.html"
        diff_cache.write_text(
            compute_html_diff(bh, ah) if bh.exists() and ah.exists()
            else "(HTML diff unavailable)",
            encoding="utf-8",
        )

    # Step 1
    spec_file = dest / "step1_spec.txt"
    if not spec_file.exists() or force:
        s1 = step1_run_one(dest, backend)
        if "error" in s1:
            raise RuntimeError(f"step1: {s1['error']}")
        spec_file.write_text(s1["code_analysis"], encoding="utf-8")

    # Step 2
    s2 = step2_run_one(dest, backend)
    record = {
        "screen_id":  screen_id,
        "model_key":  model_key,
        "overall":    s2.get("overall"),
        "criteria":   s2.get("criteria"),
        "comment":    s2.get("comment"),
        "response":   s2.get("response"),
        "error":      s2.get("error"),
        "eval_model": getattr(backend, "model", None),
    }
    result_file.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


# ---------------------------------------------------------------------------
# Accuracy helpers
# ---------------------------------------------------------------------------

def _compute_accuracy(examples: list[dict]) -> dict:
    """Compute per-model pass counts and accuracy from a list of eval records."""
    from collections import defaultdict
    stats: dict[str, dict] = defaultdict(lambda: {"pass": 0, "fail": 0, "error": 0})
    for ex in examples:
        mk = ex.get("model_key", "unknown")
        v  = (ex.get("overall") or "").upper()
        if v == "PASS":
            stats[mk]["pass"] += 1
        elif v == "FAIL":
            stats[mk]["fail"] += 1
        else:
            stats[mk]["error"] += 1

    result = {}
    for mk, s in stats.items():
        total = s["pass"] + s["fail"] + s["error"]
        scored = s["pass"] + s["fail"]
        result[mk] = {
            "pass":     s["pass"],
            "fail":     s["fail"],
            "error":    s["error"],
            "total":    total,
            "accuracy": round(s["pass"] / scored, 4) if scored else None,
        }
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate CodeGenerationExperiment outputs with the auto-evaluator."
    )
    parser.add_argument("--run", metavar="PATH",
                        help="Path to a run results JSON from build_dataset.py. "
                             "Evaluates all (screen, model) pairs in that run and "
                             "saves per-model accuracy to CodeGeneration/Results/.")
    parser.add_argument("--seed", type=int, default=42,
                        help="Seed for legacy standalone mode (ignored when --run is used).")
    parser.add_argument("--backend", default="gemini",
                        choices=["gemini", "vertexai", "anthropic", "openai"])
    parser.add_argument("--model", default=None,
                        help="Override evaluator model (default for gemini: gemini-3.1-pro-preview).")
    parser.add_argument("--force", action="store_true",
                        help="Re-evaluate even if eval_result.json already exists.")
    parser.add_argument("--output", default=str(_OUTPUT), metavar="PATH",
                        help=f"Output dataset directory (default: {_OUTPUT}).")
    args = parser.parse_args()

    eval_model = args.model or (_EVAL_MODEL if args.backend == "gemini" else None)
    backend    = get_backend(args.backend, eval_model)
    output     = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    print(f"Output:   {output}")
    print(f"Evaluator: {args.backend} | {getattr(backend, 'model', '—')}")
    print()

    # ------------------------------------------------------------------
    # Mode 1: evaluate all models for all screens in a build run
    # ------------------------------------------------------------------
    if args.run:
        run_meta = json.loads(Path(args.run).read_text(encoding="utf-8"))
        run_name = run_meta["run_name"]
        sampled  = run_meta["sampled"]      # [{screen_id, category, task}]
        models   = run_meta["models"]       # model keys used in the build

        n_total = len(sampled) * len(models)
        print(f"Run:      {run_name}")
        print(f"Screens:  {len(sampled)}  ×  Models: {len(models)}  =  {n_total} pairs")
        print()

        examples: list[dict] = []
        done = skipped = errors = 0
        idx  = 0

        for entry in sampled:
            sid = entry["screen_id"]
            for model_key in models:
                idx += 1
                dest = output / f"{sid}_{model_key}"
                already = (dest / "eval_result.json").exists()
                label   = f"  [{idx:>4}/{n_total}] {sid} / {model_key}"

                if already and not args.force:
                    print(f"{label}  skip")
                    examples.append(json.loads((dest / "eval_result.json").read_text()))
                    skipped += 1
                    continue

                print(f"{label} ... ", end="", flush=True)
                try:
                    rec = _evaluate_one(sid, model_key, backend, args.force)
                    verdict = rec.get("overall") or rec.get("error") or "?"
                    print(verdict)
                    examples.append(rec)
                    if rec.get("error") == "generation_failed":
                        errors += 1
                    else:
                        done += 1
                except Exception as e:
                    print(f"ERROR: {e}")
                    examples.append({"screen_id": sid, "model_key": model_key,
                                     "error": str(e), "overall": None})
                    errors += 1

        per_model = _compute_accuracy(examples)

        # Print summary
        print(f"\n{'─'*55}")
        print(f"  {'Model':<30}  {'Acc':>6}  {'Pass':>5}  {'Fail':>5}")
        print(f"  {'─'*30}  {'─'*6}  {'─'*5}  {'─'*5}")
        for mk in models:
            s = per_model.get(mk, {})
            acc = f"{s.get('accuracy', 0):.1%}" if s.get("accuracy") is not None else "  n/a"
            print(f"  {mk:<30}  {acc:>6}  {s.get('pass',0):>5}  {s.get('fail',0):>5}")
        print()

        # Save eval results
        _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        eval_name = f"eval_{run_name}"
        eval_file = _RESULTS_DIR / f"{eval_name}.json"
        eval_file.write_text(json.dumps({
            "eval_name":   eval_name,
            "source_run":  run_name,
            "eval_model":  getattr(backend, "model", args.backend),
            "n_screens":   len(sampled),
            "n_models":    len(models),
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "per_model":   per_model,
            "examples":    [
                {k: v for k, v in ex.items() if k != "response"}
                for ex in examples
            ],
        }, indent=2), encoding="utf-8")
        print(f"Eval results saved to {eval_file.relative_to(_ROOT)}")
        print(f"Done.  Evaluated: {done}  Skipped: {skipped}  Errors/Failed: {errors}")
        return

    # ------------------------------------------------------------------
    # Mode 2: legacy standalone — 1 random model per screen
    # ------------------------------------------------------------------
    import random
    rng         = random.Random(args.seed)
    model_keys  = list(_MODEL_REGISTRY)
    screen_dirs = sorted(d for d in _SOURCE.iterdir() if d.is_dir())

    print(f"Screens:  {len(screen_dirs)}  (standalone mode, 1 model/screen)")
    print()

    done = errors = skipped = 0
    n = len(screen_dirs)

    for i, screen_dir in enumerate(screen_dirs, 1):
        available = [m for m in model_keys
                     if (screen_dir / m / "index.html").exists()
                     and (screen_dir / m / "screenshot.png").exists()]
        if not available:
            print(f"  [{i:>3}/{n}] {screen_dir.name}  SKIP — no model outputs")
            errors += 1
            continue

        model_key = rng.choice(available)
        dest      = output / f"{screen_dir.name}_{model_key}"

        if (dest / "eval_result.json").exists() and not args.force:
            print(f"  [{i:>3}/{n}] {screen_dir.name}_{model_key}  skip")
            skipped += 1
            continue

        print(f"  [{i:>3}/{n}] {screen_dir.name} → {model_key} ... ", end="", flush=True)
        try:
            rec = _evaluate_one(screen_dir.name, model_key, backend, args.force)
            print(rec.get("overall") or "ERROR")
            done += 1
        except Exception as e:
            print(f"ERROR: {e}")
            errors += 1

    print(f"\nDone.  Evaluated: {done}  Skipped: {skipped}  Errors: {errors}")
    print(f"Dataset: {output}")


if __name__ == "__main__":
    main()
