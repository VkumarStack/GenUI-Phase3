"""
Compare the auto-evaluator against human rubric judgments on the ValidationData
screens graded during the iteration-3 validation study.

For each (screen, model) a participant graded, this runs the two-stage auto-
evaluator (cached under Datasets/ValidationData/{screen}/{model}/) and compares
its verdict to the human's on:
  - the binary OVERALL pass/fail, and
  - three rubric criteria: Requirement Fulfillment, Consistency, No Regressions.

The validated model outputs map to three model folders:
    claude -> claude-haiku-4-5,  gemini -> gemini-2.5-flash,  openai -> gpt-4.1-mini

By default only participant p_a3c3baaa-... is processed; pass --participants to
score others (or several at once).

Usage:
    python Validation/validate.py
    python Validation/validate.py --participants p_a3c3baaa-... p_fd383f2e-...
    python Validation/validate.py --force --workers 8
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
sys.path.insert(0, str(Path(__file__).parent))

from backends import get_backend
from auto_evaluator import evaluate_screen

_CSV          = Path(__file__).parent / "iteration3_case_evaluations_rows.csv"
_RESULTS_DIR  = Path(__file__).parent / "Results"
_DATA         = _ROOT / "Datasets" / "ValidationData"
_DEFAULT_PARTICIPANTS = ["p_a3c3baaa-b148-4fe7-8f9a-ad5f178ebb68"]
_EVAL_MODEL   = "gemini-3.1-pro-preview"
_DEFAULT_WORKERS = 8

# Validation provider id -> ValidationData model folder.
_PROVIDER_MODEL = {
    "claude": "claude-haiku-4-5",
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4.1-mini",
}

# (human criteria key, auto-evaluator criteria key, display label).
_CRITERIA = [
    ("requirementFulfillment", "requirementFulfillment", "Req. Fulfillment"),
    ("consistencyOriginal",    "consistency",            "Consistency"),
    ("noRegressions",          "noRegressions",          "No Regressions"),
]


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _norm(v: str | None) -> str:
    """Normalize a rubric value to PASS / PARTIAL / FAIL."""
    s = (v or "").strip().lower()
    if "partial" in s:
        return "PARTIAL"
    if "pass" in s:
        return "PASS"
    if "fail" in s:
        return "FAIL"
    return s.upper()


def _norm_overall(v: str | None) -> str:
    """Normalize an overall verdict to PASS / FAIL."""
    s = (v or "").strip().lower()
    if "pass" in s:
        return "PASS"
    if "fail" in s:
        return "FAIL"
    return s.upper()


# ---------------------------------------------------------------------------
# CSV -> grading rows
# ---------------------------------------------------------------------------

def _load_gradings(csv_path: Path, participants: set[str]) -> list[dict]:
    """Return one entry per (participant, screen, provider) human grading."""
    gradings = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["participant_id"] not in participants:
                continue
            sid    = row["screen_id"]
            prompt = (row["prompt_text"] or "").strip()
            task_file = _DATA / sid / "Task.txt"
            task_disk = task_file.read_text(encoding="utf-8").strip() if task_file.exists() else ""
            task_mismatch = task_disk != prompt

            rubrics = json.loads(row["provider_rubrics"])
            for provider, rub in rubrics.items():
                model_key = _PROVIDER_MODEL.get(provider)
                if model_key is None:
                    continue
                human_crit = {
                    auto_key: _norm(rub.get("criteria", {}).get(human_key))
                    for human_key, auto_key, _ in _CRITERIA
                }
                gradings.append({
                    "participant":   row["participant_id"],
                    "screen_id":     sid,
                    "provider":      provider,
                    "model_key":     model_key,
                    "task_mismatch": task_mismatch,
                    "human_overall": _norm_overall(rub.get("overallEvaluation")),
                    "human_criteria": human_crit,
                })
    return gradings


# ---------------------------------------------------------------------------
# Alignment metrics
# ---------------------------------------------------------------------------

def _agreement(pairs: list[tuple[str, str]]) -> dict:
    """Given (human, auto) pairs, return agreement count/total/pct."""
    total = len(pairs)
    agree = sum(1 for h, a in pairs if h == a)
    return {"agree": agree, "total": total,
            "pct": round(agree / total, 4) if total else None}


def _confusion(pairs: list[tuple[str, str]], labels: list[str]) -> dict:
    conf = {h: {a: 0 for a in labels} for h in labels}
    for h, a in pairs:
        if h in conf and a in conf[h]:
            conf[h][a] += 1
    return conf


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Compare the auto-evaluator to human rubric judgments (iteration-3 validation)."
    )
    parser.add_argument("--participants", nargs="+", default=_DEFAULT_PARTICIPANTS,
                        help="Participant id(s) to score (default: the primary participant).")
    parser.add_argument("--csv", default=str(_CSV), metavar="PATH",
                        help=f"Validation CSV (default: {_CSV.name}).")
    parser.add_argument("--eval-backend", default="gemini",
                        choices=["gemini", "vertexai", "anthropic", "openai"])
    parser.add_argument("--eval-model", default=None,
                        help=f"Auto-evaluator model (default for gemini: {_EVAL_MODEL}).")
    parser.add_argument("--workers", type=int, default=_DEFAULT_WORKERS,
                        help=f"Parallel auto-eval workers (default: {_DEFAULT_WORKERS}).")
    parser.add_argument("--force", action="store_true",
                        help="Recompute cached auto-evaluations.")
    parser.add_argument("--out", default=None, metavar="PATH",
                        help="Output JSON path (default: Results/validation_<participants>.json).")
    args = parser.parse_args()

    eval_model = args.eval_model or (_EVAL_MODEL if args.eval_backend == "gemini" else None)
    backend    = get_backend(args.eval_backend, eval_model)

    gradings = _load_gradings(Path(args.csv), set(args.participants))
    if not gradings:
        raise SystemExit(f"No gradings found for participants: {args.participants}")

    n_total    = len(gradings)
    n_mismatch = sum(1 for g in gradings if g["task_mismatch"])
    print(f"Participants:  {', '.join(args.participants)}")
    print(f"Evaluator:     {args.eval_backend} | {getattr(backend, 'model', '—')}")
    print(f"Gradings:      {n_total}  ({len(set(g['screen_id'] for g in gradings))} screens, "
          f"{n_mismatch} excluded for task mismatch)")
    print(f"Workers:       {args.workers}")
    print()

    # Run auto-eval for every (screen, model) in parallel; cache keyed per pair.
    pairs   = sorted({(g["screen_id"], g["model_key"]) for g in gradings})
    autos: dict[tuple, dict] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        fut_map = {ex.submit(evaluate_screen, sid, mk, backend, args.force): (sid, mk)
                   for sid, mk in pairs}
        for fut in as_completed(fut_map):
            sid, mk = fut_map[fut]
            autos[(sid, mk)] = fut.result()
            done += 1
            r = autos[(sid, mk)]
            verdict = r.get("error") or r.get("overall") or "?"
            print(f"  [{done:>3}/{len(pairs)}] {sid} / {mk}: {verdict}", flush=True)

    # Build comparison records.
    records   = []
    errors    = 0
    for g in gradings:
        auto = autos[(g["screen_id"], g["model_key"])]
        if "error" in auto:
            errors += 1
            records.append({**g, "auto_error": auto["error"]})
            continue
        auto_crit = {
            auto_key: _norm((auto.get("criteria") or {}).get(auto_key))
            for _, auto_key, _ in _CRITERIA
        }
        records.append({
            **g,
            "auto_overall":  _norm_overall(auto.get("overall")),
            "auto_criteria": auto_crit,
            "auto_comment":  auto.get("comment"),
        })

    # Aggregate over scorable records (valid task, no auto error).
    scorable = [r for r in records if not r.get("task_mismatch") and "auto_error" not in r]

    overall_pairs = [(r["human_overall"], r["auto_overall"]) for r in scorable]
    overall_agree = _agreement(overall_pairs)
    overall_conf  = _confusion(overall_pairs, ["PASS", "FAIL"])

    crit_metrics = {}
    for _, auto_key, label in _CRITERIA:
        cp = [(r["human_criteria"][auto_key], r["auto_criteria"][auto_key]) for r in scorable]
        crit_metrics[auto_key] = {
            "label":     label,
            "agreement": _agreement(cp),
            "confusion": _confusion(cp, ["PASS", "PARTIAL", "FAIL"]),
        }

    # ------------------------------------------------------------------ report
    def _pct(a):
        return f"{a['pct']:.1%}" if a["pct"] is not None else "n/a"

    print(f"\n{'='*60}")
    print(f"Scored: {len(scorable)} (screen, model) pairs "
          f"[excluded: {n_mismatch} task-mismatch, {errors} auto-error]")
    print(f"\n  OVERALL pass/fail agreement: {_pct(overall_agree)} "
          f"({overall_agree['agree']}/{overall_agree['total']})")
    print("    confusion (rows=human, cols=auto):")
    print(f"      {'':6}{'PASS':>6}{'FAIL':>6}")
    for h in ("PASS", "FAIL"):
        print(f"      {h:<6}{overall_conf[h]['PASS']:>6}{overall_conf[h]['FAIL']:>6}")

    print("\n  CRITERIA agreement (3-way PASS/PARTIAL/FAIL):")
    for _, auto_key, label in _CRITERIA:
        m = crit_metrics[auto_key]
        print(f"    {label:<18} {_pct(m['agreement'])}  "
              f"({m['agreement']['agree']}/{m['agreement']['total']})")

    # Overall disagreements
    dis = [r for r in scorable if r["human_overall"] != r["auto_overall"]]
    if dis:
        print(f"\n  Overall disagreements ({len(dis)}):")
        for r in dis:
            print(f"    {r['screen_id']:>7} / {r['model_key']:<18} "
                  f"human={r['human_overall']}  auto={r['auto_overall']}")

    if n_mismatch:
        print(f"\n  Excluded (task in CSV differs from ValidationData Task.txt):")
        for r in records:
            if r.get("task_mismatch"):
                print(f"    {r['screen_id']} / {r['model_key']}")

    # ------------------------------------------------------------------ save
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = "_".join(p.split("_")[1][:8] for p in args.participants) if args.participants else "all"
    out_path = Path(args.out) if args.out else _RESULTS_DIR / f"validation_{tag}.json"
    out_path.write_text(json.dumps({
        "participants":  args.participants,
        "eval_model":    getattr(backend, "model", args.eval_backend),
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        "n_scored":      len(scorable),
        "n_task_mismatch": n_mismatch,
        "n_auto_error":  errors,
        "overall":       {"agreement": overall_agree, "confusion": overall_conf},
        "criteria":      crit_metrics,
        "records":       [{k: v for k, v in r.items() if k != "auto_comment"} for r in records],
    }, indent=2), encoding="utf-8")
    print(f"\nSaved to {out_path.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
