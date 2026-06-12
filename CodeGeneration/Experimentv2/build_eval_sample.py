"""
Run the auto-evaluator pipeline on CodeGenerationExperimentv2 outputs.

v2 variant of CodeGeneration/build_eval_sample.py. Reads a run results file from
the v2 build_dataset and evaluates every (screen, model) pair, writing the eval
sample dataset to Datasets/CodeGenEvalSamplev2/ and a per-model accuracy report
to CodeGeneration/Experimentv2/Results/eval_{run_name}.json.

For each example, files are copied to Datasets/CodeGenEvalSamplev2/ and the
html_diff -> step1 -> step2 pipeline is run in place. Already-evaluated examples
are skipped unless --force is passed.

Output folder structure per example:
    {screen_id}_{model_key}/
        Task.txt, category.txt
        Before/index.html, Before/screenshot.png
        After/index.html, After/screenshot.png
        html_diff.txt
        step1_spec.txt
        eval_result.json

Usage:
    python CodeGeneration/Experimentv2/build_eval_sample.py \\
        --run CodeGeneration/Experimentv2/Results/run_0_10screens.json
    python CodeGeneration/Experimentv2/build_eval_sample.py --run ... --force
"""

import argparse
import json
import shutil
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
sys.path.insert(0, str(_ROOT / "Evaluator"))

from backends import get_backend
from html_diff import html_diff as compute_html_diff
from step1 import run_one as step1_run_one
from step2 import _run_one as step2_run_one

_SOURCE      = _ROOT / "Datasets" / "CodeGenerationExperimentv2"
_OUTPUT      = _ROOT / "Datasets" / "CodeGenEvalSamplev2"
_RESULTS_DIR = Path(__file__).parent / "Results"
_EVAL_MODEL  = "gemini-3.1-pro-preview"
_DEFAULT_WORKERS = 8


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


def _evaluate_one(screen_id: str, model_key: str, backend, force: bool,
                  output_dir: Path) -> dict:
    """Evaluate one (screen, model) pair. Returns the eval_result dict."""
    screen_dir  = _SOURCE / screen_id
    dest        = output_dir / f"{screen_id}_{model_key}"
    result_file = dest / "eval_result.json"

    # A rendered screenshot only exists when generation produced valid HTML, so
    # its presence (not a possibly-stale generation_failed.json from an earlier
    # run) is the source of truth for whether there is something to evaluate.
    after_html = screen_dir / model_key / "index.html"
    after_shot = screen_dir / model_key / "screenshot.png"
    if not after_html.exists() or not after_shot.exists():
        return {"screen_id": screen_id, "model_key": model_key,
                "overall": "FAIL", "criteria": {},
                "comment": "Generation failed — no valid output.",
                "error": "generation_failed", "eval_model": None}

    if result_file.exists() and not force:
        return json.loads(result_file.read_text(encoding="utf-8"))

    _copy_screen(screen_dir, model_key, dest)

    diff_cache = dest / "html_diff.txt"
    if not diff_cache.exists() or force:
        bh = dest / "Before" / "index.html"
        ah = dest / "After"  / "index.html"
        diff_cache.write_text(
            compute_html_diff(bh, ah) if bh.exists() and ah.exists()
            else "(HTML diff unavailable)",
            encoding="utf-8",
        )

    spec_file = dest / "step1_spec.txt"
    if not spec_file.exists() or force:
        s1 = step1_run_one(dest, backend)
        if "error" in s1:
            raise RuntimeError(f"step1: {s1['error']}")
        spec_file.write_text(s1["code_analysis"], encoding="utf-8")

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


def _eval_job(screen_id: str, model_key: str, backend, force: bool,
              output_dir: Path) -> dict:
    """Thread worker: evaluate one pair, converting exceptions into error records."""
    try:
        return _evaluate_one(screen_id, model_key, backend, force, output_dir)
    except Exception as e:
        return {"screen_id": screen_id, "model_key": model_key,
                "error": str(e), "overall": None}


def _compute_accuracy(examples: list[dict]) -> dict:
    """Per-model pass counts and accuracy from a list of eval records."""
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
        total  = s["pass"] + s["fail"] + s["error"]
        scored = s["pass"] + s["fail"]
        result[mk] = {
            "pass":     s["pass"],
            "fail":     s["fail"],
            "error":    s["error"],
            "total":    total,
            "accuracy": round(s["pass"] / scored, 4) if scored else None,
        }
    return result


# Rubric criteria reported in the final report (visualUsability and minimality
# are intentionally excluded). (json_key, display_label).
_REPORT_CRITERIA = [
    ("requirementFulfillment", "Req. Fulfillment"),
    ("consistency",            "Consistency"),
    ("noRegressions",          "No Regressions"),
]
_RUBRIC_LEVELS = ["PASS", "PARTIAL PASS", "FAIL"]


def _compute_criteria(examples: list[dict]) -> dict:
    """Per-model PASS/PARTIAL/FAIL split for each reported rubric criterion.

    Examples that errored out of the evaluator (overall is None) are skipped.
    Generation failures (no rubric, overall=FAIL) count as FAIL on every
    criterion, matching how the overall accuracy treats them.
    """
    counts: dict[str, dict] = defaultdict(
        lambda: {key: {lvl: 0 for lvl in _RUBRIC_LEVELS} for key, _ in _REPORT_CRITERIA}
    )
    for ex in examples:
        if ex.get("overall") is None:        # evaluator exception — not scorable
            continue
        mk   = ex.get("model_key", "unknown")
        crit = ex.get("criteria") or {}
        for key, _ in _REPORT_CRITERIA:
            v = (crit.get(key) or "FAIL").upper()
            if v not in _RUBRIC_LEVELS:
                v = "FAIL"
            counts[mk][key][v] += 1

    result: dict[str, dict] = {}
    for mk, crits in counts.items():
        result[mk] = {}
        for key, _ in _REPORT_CRITERIA:
            c     = crits[key]
            total = sum(c.values())
            result[mk][key] = {
                "pass":        c["PASS"],
                "partial":     c["PARTIAL PASS"],
                "fail":        c["FAIL"],
                "total":       total,
                "pass_pct":    round(c["PASS"] / total, 4)         if total else None,
                "partial_pct": round(c["PARTIAL PASS"] / total, 4) if total else None,
                "fail_pct":    round(c["FAIL"] / total, 4)         if total else None,
            }
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate CodeGenerationExperimentv2 outputs with the auto-evaluator."
    )
    parser.add_argument("--run", required=True, metavar="PATH",
                        help="Path to a run results JSON from Experimentv2/build_dataset.py.")
    parser.add_argument("--backend", default="gemini",
                        choices=["gemini", "vertexai", "anthropic", "openai"])
    parser.add_argument("--model", default=None,
                        help="Override evaluator model (default for gemini: gemini-3.1-pro-preview).")
    parser.add_argument("--force", action="store_true",
                        help="Re-evaluate even if eval_result.json already exists.")
    parser.add_argument("--workers", type=int, default=_DEFAULT_WORKERS,
                        help=f"Parallel evaluation workers (default: {_DEFAULT_WORKERS}; "
                             f"use 1 for sequential).")
    parser.add_argument("--output", default=str(_OUTPUT), metavar="PATH",
                        help=f"Output dataset directory (default: {_OUTPUT}).")
    args = parser.parse_args()

    eval_model = args.model or (_EVAL_MODEL if args.backend == "gemini" else None)
    backend    = get_backend(args.backend, eval_model)
    output     = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    run_meta = json.loads(Path(args.run).read_text(encoding="utf-8"))
    run_name = run_meta["run_name"]
    sampled  = run_meta["sampled"]
    models   = run_meta["models"]

    n_total = len(sampled) * len(models)
    print(f"Output:    {output}")
    print(f"Evaluator: {args.backend} | {getattr(backend, 'model', '—')}")
    print(f"Run:       {run_name}")
    print(f"Screens:   {len(sampled)}  ×  Models: {len(models)}  =  {n_total} pairs")
    print(f"Workers:   {args.workers}")
    print()

    # Split into cached (skip) vs jobs to run; the auto-evaluator calls are
    # network-bound, so run them across a thread pool.
    jobs    = [(entry["screen_id"], mk) for entry in sampled for mk in models]
    results: dict[tuple, dict] = {}
    to_run: list[tuple] = []
    for sid, mk in jobs:
        cached = output / f"{sid}_{mk}" / "eval_result.json"
        if cached.exists() and not args.force:
            results[(sid, mk)] = json.loads(cached.read_text())
        else:
            to_run.append((sid, mk))

    skipped = len(jobs) - len(to_run)
    print(f"Cached: {skipped}   To evaluate: {len(to_run)}")

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        fut_map = {
            ex.submit(_eval_job, sid, mk, backend, args.force, output): (sid, mk)
            for sid, mk in to_run
        }
        for fut in as_completed(fut_map):
            sid, mk = fut_map[fut]
            rec = fut.result()
            results[(sid, mk)] = rec
            done += 1
            verdict = rec.get("overall") or rec.get("error") or "?"
            print(f"  [{done:>4}/{len(to_run)}] {sid} / {mk}: {verdict}", flush=True)

    # Reassemble in deterministic (screen, model) order.
    examples       = [results[(entry["screen_id"], mk)] for entry in sampled for mk in models]
    errors         = sum(1 for r in examples if r.get("error"))
    per_model      = _compute_accuracy(examples)
    per_model_crit = _compute_criteria(examples)

    # Overall PASS/FAIL accuracy per model
    print(f"\n{'─'*55}")
    print("  OVERALL")
    print(f"  {'Model':<30}  {'Acc':>6}  {'Pass':>5}  {'Fail':>5}")
    print(f"  {'─'*30}  {'─'*6}  {'─'*5}  {'─'*5}")
    for mk in models:
        s = per_model.get(mk, {})
        acc = f"{s.get('accuracy', 0):.1%}" if s.get("accuracy") is not None else "  n/a"
        print(f"  {mk:<30}  {acc:>6}  {s.get('pass',0):>5}  {s.get('fail',0):>5}")

    # Per-criterion PASS / PARTIAL / FAIL split per model
    def _pct(x):
        return f"{x:.1%}" if x is not None else "  n/a"

    for key, label in _REPORT_CRITERIA:
        print(f"\n  {label.upper()}  (PASS / PARTIAL / FAIL)")
        print(f"  {'Model':<30}  {'PASS':>7}  {'PART':>7}  {'FAIL':>7}")
        print(f"  {'─'*30}  {'─'*7}  {'─'*7}  {'─'*7}")
        for mk in models:
            c = per_model_crit.get(mk, {}).get(key, {})
            print(f"  {mk:<30}  {_pct(c.get('pass_pct')):>7}  "
                  f"{_pct(c.get('partial_pct')):>7}  {_pct(c.get('fail_pct')):>7}")
    print()

    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    eval_name = f"eval_{run_name}"
    eval_file = _RESULTS_DIR / f"{eval_name}.json"
    eval_file.write_text(json.dumps({
        "eval_name":         eval_name,
        "source_run":        run_name,
        "mode":              run_meta.get("mode", "full_html"),
        "eval_model":        getattr(backend, "model", args.backend),
        "n_screens":         len(sampled),
        "n_models":          len(models),
        "timestamp":         datetime.now(timezone.utc).isoformat(),
        "per_model":         per_model,
        "per_model_criteria": per_model_crit,
        "reported_criteria": [k for k, _ in _REPORT_CRITERIA],
        "examples":   [
            {k: v for k, v in ex.items() if k != "response"}
            for ex in examples
        ],
    }, indent=2), encoding="utf-8")
    print(f"Eval results saved to {eval_file.relative_to(_ROOT)}")
    print(f"Done.  Evaluated: {len(to_run)}  Cached: {skipped}  Errors/Failed: {errors}")


if __name__ == "__main__":
    main()
