"""
Pairwise comparison of two revision generator result files.

Uses Claude (AnthropicBackend) as judge to avoid same-model bias. By default,
all categories for a screen are judged in a single API call (--batch-size 0),
so the screenshot is sent only once per screen. Use --batch-size N to split
categories into chunks of N per call instead.

A/B slot assignment is randomized once per batch so the judge never knows which
model is which. Results are stored per (screen, category) regardless of batch size.

Usage:
    python Testing/RevisionGenerator/compare.py Results/gemini.json Results/finetuned-v1.json
    python Testing/RevisionGenerator/compare.py Results/gemini.json Results/finetuned-v1.json \\
        --judge-model claude-opus-4-7 --batch-size 3

Output is saved to:
    Testing/RevisionGenerator/Results/<run_a>_vs_<run_b>.json
"""

import argparse
import json
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))

from backends import AnthropicBackend

_RAW_DATASET = _ROOT / "Datasets" / "RawDataset"
_TAXONOMY    = _ROOT / "Taxonomy" / "RevisionTaxonomy" / "Results" / "taxonomy.json"
_RESULTS_DIR = Path(__file__).parent / "Results"

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_JUDGE_PROMPT = """\
You are evaluating two AI models that generate UI revision tasks for mobile app screens.

You are given a screenshot of a mobile UI and {n_cats} revision {cat_word}.
For EACH category, evaluate which model's tasks (A or B) are better, \
judging each category INDEPENDENTLY.

EVALUATION DIMENSIONS:
1. RELEVANCE: How well each task fits the given revision category.
2. SPECIFICITY: How precisely tasks identify UI components and describe their \
current state (location, appearance, label).
3. ACTIONABILITY: How clearly a developer could implement each task — \
unambiguous, concrete change descriptions.
4. DIVERSITY: Whether the tasks in a set cover meaningfully different aspects \
of the UI rather than repeating the same idea.

For EACH category, output one block using EXACTLY this format — no extra text \
between blocks:

[CATEGORY: <category name>]
PREFERENCE: A / B / TIE
REASONING: <2-3 sentences citing specific strengths or weaknesses of each set>
SCORES:
- Relevance: A=N/5 B=N/5
- Specificity: A=N/5 B=N/5
- Actionability: A=N/5 B=N/5
- Diversity: A=N/5 B=N/5

Replace each N with an integer 0-5. Output one block per category in the order \
listed below.

---

{category_blocks}\
"""

_CATEGORY_BLOCK = """\
### {idx}. {category_name}
{category_description}

Model A Tasks:
{tasks_a}

Model B Tasks:
{tasks_b}

"""

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_CAT_HEADER_RE  = re.compile(r"\[CATEGORY:\s*([^\]]+)\]", re.IGNORECASE)
_PREFERENCE_RE  = re.compile(r"PREFERENCE\s*:\s*(A|B|TIE)", re.IGNORECASE)
_SCORE_RE       = re.compile(
    r"-\s*(Relevance|Specificity|Actionability|Diversity)\s*:\s*"
    r"A=(\d)/5\s+B=(\d)/5",
    re.IGNORECASE,
)


def _parse_single_block(text: str) -> tuple[str | None, dict]:
    pref_m = _PREFERENCE_RE.search(text)
    preference = pref_m.group(1).upper() if pref_m else None

    scores: dict[str, dict] = {}
    for m in _SCORE_RE.finditer(text):
        dim = m.group(1).capitalize()
        scores[dim] = {"a": int(m.group(2)), "b": int(m.group(3))}

    return preference, scores


def _parse_batched_response(response: str) -> dict[str, tuple[str | None, dict]]:
    """Return {normalized_cat_name: (preference, scores)} from a batched response."""
    parts = _CAT_HEADER_RE.split(response)
    # parts = [pre-text, cat1, block1, cat2, block2, ...]
    results: dict[str, tuple[str | None, dict]] = {}
    for i in range(1, len(parts), 2):
        cat_name = parts[i].strip()
        block    = parts[i + 1] if i + 1 < len(parts) else ""
        results[cat_name] = _parse_single_block(block)
    return results


def _best_match(parsed_name: str, candidates: list[str]) -> str | None:
    """Case-insensitive prefix match for category names from LLM output."""
    low = parsed_name.lower()
    for c in candidates:
        if c.lower() == low or c.lower().startswith(low) or low.startswith(c.lower()):
            return c
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_taxonomy_map() -> dict[str, dict]:
    cats = json.loads(_TAXONOMY.read_text())["categories"]
    return {c["name"]: c for c in cats}


def _format_tasks(tasks: list[str]) -> str:
    return "\n".join(f"{i}. {t}" for i, t in enumerate(tasks, 1))


def _build_batch_prompt(
    batch: list[dict],  # each: {cat_name, cat_desc, tasks_a, tasks_b}
) -> str:
    blocks = ""
    for idx, item in enumerate(batch, 1):
        blocks += _CATEGORY_BLOCK.format(
            idx=idx,
            category_name=item["cat_name"],
            category_description=item["cat_desc"],
            tasks_a=_format_tasks(item["tasks_a"]),
            tasks_b=_format_tasks(item["tasks_b"]),
        )
    n = len(batch)
    return _JUDGE_PROMPT.format(
        n_cats=n,
        cat_word="category" if n == 1 else "categories",
        category_blocks=blocks,
    )


def _compute_summary(comparisons: list[dict], run_a: str, run_b: str) -> dict:
    totals = {run_a: 0, run_b: 0, "tie": 0, "error": 0}
    per_category: dict[str, dict] = {}

    # Accumulate scores per run: {run_name: {dimension: [values]}}
    score_accum: dict[str, dict[str, list[float]]] = {run_a: {}, run_b: {}}

    for c in comparisons:
        cat = c["category"]
        if cat not in per_category:
            per_category[cat] = {run_a: 0, run_b: 0, "tie": 0}

        winner = c.get("winner")
        if winner == run_a:
            totals[run_a] += 1
            per_category[cat][run_a] += 1
        elif winner == run_b:
            totals[run_b] += 1
            per_category[cat][run_b] += 1
        elif winner == "TIE":
            totals["tie"] += 1
            per_category[cat]["tie"] += 1
        else:
            totals["error"] += 1

        # Map slot letters back to run names using per-comparison slot assignments
        slot_a_run = c.get("slot_a_run", run_a)
        slot_b_run = c.get("slot_b_run", run_b)
        slot_map = {"a": slot_a_run, "b": slot_b_run}

        for dim, vals in c.get("scores", {}).items():
            for slot, run_name in slot_map.items():
                if run_name in score_accum and slot in vals:
                    score_accum[run_name].setdefault(dim, []).append(vals[slot])

    # Average scores per run per dimension
    dims = ["Relevance", "Specificity", "Actionability", "Diversity"]
    avg_scores: dict[str, dict[str, float]] = {}
    for run_name, dim_lists in score_accum.items():
        avg_scores[run_name] = {}
        dim_avgs = []
        for dim in dims:
            vals = dim_lists.get(dim, [])
            avg = round(sum(vals) / len(vals), 3) if vals else None
            avg_scores[run_name][dim] = avg
            if avg is not None:
                dim_avgs.append(avg)
        avg_scores[run_name]["overall"] = (
            round(sum(dim_avgs) / len(dim_avgs), 3) if dim_avgs else None
        )

    return {"totals": totals, "per_category": per_category, "avg_scores": avg_scores}


def _save(output_path: Path, run_a: str, run_b: str, judge_model: str,
          comparisons: list[dict]) -> None:
    summary = _compute_summary(comparisons, run_a, run_b)
    output_path.write_text(json.dumps({
        "run_a":       run_a,
        "run_b":       run_b,
        "judge_model": judge_model,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "summary":     summary,
        "comparisons": comparisons,
    }, indent=2))


def _print_summary(summary: dict, run_a: str, run_b: str) -> None:
    totals = summary.get("totals", {})
    total  = sum(totals.get(k, 0) for k in (run_a, run_b, "tie"))
    if total == 0:
        print("No scored comparisons.")
        return

    print(f"\n{'─'*55}")
    print(f"  {run_a:<22}  wins: {totals.get(run_a,0):>3}"
          f"  ({totals.get(run_a,0)/total:.0%})")
    print(f"  {run_b:<22}  wins: {totals.get(run_b,0):>3}"
          f"  ({totals.get(run_b,0)/total:.0%})")
    print(f"  {'TIE':<22}       {totals.get('tie',0):>3}"
          f"  ({totals.get('tie',0)/total:.0%})")
    if totals.get("error", 0):
        print(f"  {'ERROR':<22}       {totals['error']:>3}")
    print()

    avg = summary.get("avg_scores", {})
    if avg:
        dims = ["Relevance", "Specificity", "Actionability", "Diversity", "overall"]
        a10, b10 = run_a[:14], run_b[:14]
        print(f"  Average scores (out of 5):")
        print(f"  {'Dimension':<16}  {a10:>14}  {b10:>14}")
        print(f"  {'─'*16}  {'─'*14}  {'─'*14}")
        for dim in dims:
            va = avg.get(run_a, {}).get(dim)
            vb = avg.get(run_b, {}).get(dim)
            sa = f"{va:.3f}" if va is not None else "—"
            sb = f"{vb:.3f}" if vb is not None else "—"
            label = dim if dim != "overall" else "OVERALL"
            print(f"  {label:<16}  {sa:>14}  {sb:>14}")
        print()

    per_cat = summary.get("per_category", {})
    if per_cat:
        a10, b10 = run_a[:12], run_b[:12]
        print(f"  {'Category':<38}  {a10:>12}  {b10:>12}  {'TIE':>4}")
        print(f"  {'─'*38}  {'─'*12}  {'─'*12}  {'─'*4}")
        for cat, counts in sorted(per_cat.items()):
            print(f"  {cat:<38}  {counts.get(run_a,0):>12}"
                  f"  {counts.get(run_b,0):>12}  {counts.get('tie',0):>4}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Pairwise comparison of two revision generator result files."
    )
    parser.add_argument("run_a", metavar="RESULTS_A",
                        help="Path to first results JSON.")
    parser.add_argument("run_b", metavar="RESULTS_B",
                        help="Path to second results JSON.")
    parser.add_argument("--judge-model", default="claude-sonnet-4-6",
                        help="Anthropic model to use as judge (default: claude-sonnet-4-6).")
    parser.add_argument("--batch-size", type=int, default=0, metavar="N",
                        help="Categories per API call. 0 = all categories for a screen "
                             "in one call (default: 0).")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for A/B slot assignment (default: 42).")
    parser.add_argument("--resume", action="store_true",
                        help="Skip (screen, category) pairs already in the output file.")
    args = parser.parse_args()

    path_a = Path(args.run_a)
    path_b = Path(args.run_b)
    for p in (path_a, path_b):
        if not p.exists():
            raise SystemExit(f"Results file not found: {p}")

    data_a = json.loads(path_a.read_text())
    data_b = json.loads(path_b.read_text())

    run_name_a = data_a["run_name"]
    run_name_b = data_b["run_name"]
    screens_a  = data_a.get("screens", {})
    screens_b  = data_b.get("screens", {})

    common_screens = sorted(set(screens_a) & set(screens_b), key=lambda x: int(x))
    taxonomy_map   = _load_taxonomy_map()
    judge          = AnthropicBackend(args.judge_model)
    rng            = random.Random(args.seed)

    output_stem = f"{run_name_a}_vs_{run_name_b}"
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = _RESULTS_DIR / f"{output_stem}.json"

    # Load existing if resuming
    done_keys: set[tuple[str, str]] = set()
    comparisons: list[dict] = []
    if args.resume and output_path.exists():
        saved      = json.loads(output_path.read_text())
        comparisons = saved.get("comparisons", [])
        done_keys  = {(c["case_study"], c["category"]) for c in comparisons}
        print(f"Resuming: {len(done_keys)} (screen, category) pairs already done.")

    total_pairs = sum(
        len([c for c in screens_a.get(cs, {}).get("categories", {})
             if screens_b.get(cs, {}).get("categories", {}).get(c)])
        for cs in common_screens
    )
    effective_batch = args.batch_size if args.batch_size > 0 else "all"
    print(f"Judge:      {args.judge_model}")
    print(f"Run A:      {run_name_a}  ({len(screens_a)} screens)")
    print(f"Run B:      {run_name_b}  ({len(screens_b)} screens)")
    print(f"Common:     {len(common_screens)} screens, {total_pairs} pairs")
    print(f"Batch size: {effective_batch} categories per API call")
    print(f"Output:     {output_path.relative_to(_ROOT)}")
    print()

    for cs_num in common_screens:
        cats_a        = screens_a[cs_num].get("categories", {})
        cats_b        = screens_b[cs_num].get("categories", {})
        source_folder = screens_a[cs_num].get("source_folder", "")
        screenshot_p  = _RAW_DATASET / source_folder / "Before" / "screenshot.png"

        if not screenshot_p.exists():
            print(f"  CaseStudy-{cs_num} — screenshot missing, SKIP")
            continue

        # Categories present in both with valid (non-null) task lists
        pending_cats = [
            c for c in cats_a
            if cats_a.get(c) and cats_b.get(c)
            and (cs_num, c) not in done_keys
        ]

        if not pending_cats:
            print(f"  CaseStudy-{cs_num} — all done, skip")
            continue

        img_bytes = screenshot_p.read_bytes()

        # Determine the A/B flip for the entire screen (same slot for all batches)
        flip = rng.random() < 0.5
        slot_a_run = run_name_b if flip else run_name_a
        slot_b_run = run_name_a if flip else run_name_b

        # Split pending categories into batches
        batch_size   = args.batch_size if args.batch_size > 0 else len(pending_cats)
        cat_batches  = [
            pending_cats[i:i + batch_size]
            for i in range(0, len(pending_cats), batch_size)
        ]

        for batch_cats in cat_batches:
            batch_items = []
            for cat_name in batch_cats:
                raw_a = cats_a[cat_name]
                raw_b = cats_b[cat_name]
                cat_info = taxonomy_map.get(cat_name, {"description": ""})
                batch_items.append({
                    "cat_name": cat_name,
                    "cat_desc": cat_info.get("description", ""),
                    "tasks_a":  raw_b if flip else raw_a,
                    "tasks_b":  raw_a if flip else raw_b,
                })

            label = (f"CaseStudy-{cs_num} | "
                     + (batch_cats[0] if len(batch_cats) == 1
                        else f"{len(batch_cats)} categories"))
            print(f"  {label} ... ", end="", flush=True)

            prompt = _build_batch_prompt(batch_items)

            try:
                response = judge.generate(prompt, images=[img_bytes])
                parsed   = _parse_batched_response(response)

                # Match parsed category names back to the known names
                matched: dict[str, tuple[str | None, dict]] = {}
                for pname, result in parsed.items():
                    canon = _best_match(pname, batch_cats)
                    if canon:
                        matched[canon] = result

                results_summary = []
                for cat_name, item in zip(batch_cats, batch_items):
                    pref, scores = matched.get(cat_name, (None, {}))

                    if pref == "A":
                        winner = slot_a_run
                    elif pref == "B":
                        winner = slot_b_run
                    elif pref == "TIE":
                        winner = "TIE"
                    else:
                        winner = None

                    results_summary.append(f"{pref or '?'}→{(winner or 'err')[:6]}")
                    comparisons.append({
                        "case_study":    cs_num,
                        "source_folder": source_folder,
                        "category":      cat_name,
                        "slot_a_run":    slot_a_run,
                        "slot_b_run":    slot_b_run,
                        "preference":    pref,
                        "winner":        winner,
                        "scores":        scores,
                        "batch_response": response if len(batch_cats) > 1 else None,
                        "response":      response if len(batch_cats) == 1 else None,
                    })

                print("  ".join(results_summary))

            except Exception as e:
                print(f"ERROR: {e}")
                for cat_name in batch_cats:
                    comparisons.append({
                        "case_study":    cs_num,
                        "source_folder": source_folder,
                        "category":      cat_name,
                        "slot_a_run":    slot_a_run,
                        "slot_b_run":    slot_b_run,
                        "preference":    None,
                        "winner":        None,
                        "scores":        {},
                        "error":         str(e),
                    })

            _save(output_path, run_name_a, run_name_b, args.judge_model, comparisons)

    summary = _compute_summary(comparisons, run_name_a, run_name_b)
    _print_summary(summary, run_name_a, run_name_b)

    _save(output_path, run_name_a, run_name_b, args.judge_model, comparisons)
    print(f"Results saved to {output_path.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
