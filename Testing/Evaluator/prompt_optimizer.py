"""
Automated prompt optimizer for the Step 2 evaluator.

For each target wrong example, an optimizer LLM sees the current prompt,
the full example input (task, DOM diff, Step 1 spec, before/after screenshots),
the evaluator's wrong output, and the correct answer. It proposes a minimal
change to the prompt and the script re-runs the evaluator to verify the fix.
Up to --max-tries attempts are made per example.

All suggestions (successful or not) are written to a markdown file for human
review. The actual prompt file is never modified.

Usage:
    python Testing/Evaluator/prompt_optimizer.py \\
        --results Testing/Evaluator/Results/finetuned-v2-no-style-computed-changes.json \\
        --skip 1,3,4,5,6,7,11,18,19,20,26,27,28,29,30 \\
        --max-tries 3 \\
        --eval-backend vertexai \\
        --optimizer-backend anthropic \\
        --output Testing/Evaluator/Results/prompt_suggestions.md

    # Use gemini as optimizer (vision-capable, faster)
    python Testing/Evaluator/prompt_optimizer.py \\
        --results Testing/Evaluator/Results/finetuned-v2-no-style-computed-changes.json \\
        --skip 1,3,4,5,6,7,11,18,19,20,26,27,28,29,30 \\
        --optimizer-backend gemini
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
sys.path.insert(0, str(_ROOT / "Evaluator"))

from backends import get_backend
from step2 import (
    _DOM_DIFF_HEADER, _PROMPT_FILE, _get_dom_diff, _get_step1_spec,
    _parse_response, _resolve_paths,
)

_RESULTS_DIR = Path(__file__).parent / "Results"

# ---------------------------------------------------------------------------
# Optimizer system / meta-prompt
# ---------------------------------------------------------------------------

_OPTIMIZER_PROMPT = """\
You are a prompt engineer improving an AI-based UI evaluator.

The evaluator assesses whether an AI-generated revision to a mobile app interface \
successfully accomplished a requested task. It receives:
  - A revision task description
  - A DOM diff (CSS Rule Changes + DOM Structure Changes)
  - Optionally, a UI component context (Step 1 visual attention guide)
  - Before and After screenshots of the UI

It outputs a rubric verdict with 5 criteria (PASS / PARTIAL PASS / FAIL each) \
and a binary OVERALL (PASS / FAIL).

A wrong example is shown below. Your job: suggest a minimal, targeted change to \
the evaluator prompt that would help it produce the correct OVERALL verdict on this \
example, without breaking correct evaluations in general.

Rules for the change:
- Address a specific gap or ambiguity in the current prompt instructions
- Changes should be generalizable — they should fix a class of mistakes, not just \
this one case
- Do not make the rubric uniformly more lenient or more strict
- Keep the change minimal — do not rewrite large sections unnecessarily
- The format placeholders {{dom_diff_block}}, {{step1_block}}, and {{task}} MUST be \
preserved exactly in the modified prompt

---

CURRENT EVALUATOR PROMPT:
{current_prompt}

---

EXAMPLE INPUT:
Revision task: {task}

DOM Diff:
{dom_diff}

UI Component Context (Step 1):
{step1}

EVALUATOR'S WRONG RESPONSE:
{wrong_response}

CORRECT ANSWER:
OVERALL should be: {ground_truth}
The evaluator predicted: {predicted}

Criteria comparison (gt → predicted):
{criteria_comparison}
{prev_attempts}
---

Now output your suggestion in exactly this format:

REASONING:
[Why did the evaluator get this wrong? Which specific instruction is missing, \
misleading, or absent?]

PROPOSED_CHANGE:
[Plain-English description of the change — which section to modify and what to add/replace]

MODIFIED_PROMPT:
[Full text of the modified prompt with your change applied]\
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_eval_prompt(prompt_template: str, folder: Path,
                       no_dom_diff: bool = False,
                       no_step1: bool = False) -> tuple[str, list[bytes]]:
    """Build the evaluator prompt and return (prompt_text, images)."""
    task_file, before, after = _resolve_paths(folder)
    task = task_file.read_text().strip()

    if no_dom_diff:
        dom_diff_block = ""
    else:
        dom_diff_text = _get_dom_diff(folder)
        dom_diff_block = _DOM_DIFF_HEADER + dom_diff_text + "\n\n---\n\n"

    if no_step1:
        step1_block = ""
    else:
        step1_text = _get_step1_spec(folder)
        step1_block = (
            "UI Component Context (visual navigation aid — not additional requirements):\n"
            + step1_text + "\n\n---\n\n"
        )

    try:
        prompt = prompt_template.format(
            task=task,
            dom_diff_block=dom_diff_block,
            step1_block=step1_block,
        )
    except KeyError as e:
        raise ValueError(f"Modified prompt has unexpected placeholder {e} — "
                         "must keep {{dom_diff_block}}, {{step1_block}}, {{task}}")

    return prompt, [before.read_bytes(), after.read_bytes()]


def _run_with_template(folder: Path, backend, prompt_template: str,
                       no_dom_diff: bool = False,
                       no_step1: bool = False) -> dict:
    prompt, images = _build_eval_prompt(prompt_template, folder, no_dom_diff, no_step1)
    response = backend.generate(prompt, images=images)
    parsed = _parse_response(response)
    return {"overall": parsed["overall"], "criteria": parsed["criteria"],
            "comment": parsed["comment"], "response": response}


def _criteria_comparison(gt_criteria: dict, pred_criteria: dict) -> str:
    labels = {
        "requirementFulfillment": "Requirement Fulfillment",
        "consistency":            "Consistency",
        "visualUsability":        "Visual & Usability",
        "minimality":             "Minimality",
        "noRegressions":          "No Regressions",
    }
    lines = []
    all_keys = set(gt_criteria) | set(pred_criteria)
    for k in ["requirementFulfillment", "consistency", "visualUsability",
              "minimality", "noRegressions"]:
        if k not in all_keys:
            continue
        gt_v  = gt_criteria.get(k, "?")
        pred_v = pred_criteria.get(k, "?")
        match = "" if gt_v == pred_v else " ← MISMATCH"
        lines.append(f"  {labels.get(k, k)}: {gt_v} → {pred_v}{match}")
    return "\n".join(lines) if lines else "  (criteria not available)"


def _parse_optimizer_response(response: str) -> dict:
    reasoning_m = re.search(
        r"REASONING:\s*\n(.*?)(?=\nPROPOSED_CHANGE:|\Z)", response, re.DOTALL)
    change_m = re.search(
        r"PROPOSED_CHANGE:\s*\n(.*?)(?=\nMODIFIED_PROMPT:|\Z)", response, re.DOTALL)
    prompt_m = re.search(r"MODIFIED_PROMPT:\s*\n(.*?)$", response, re.DOTALL)

    return {
        "reasoning":       reasoning_m.group(1).strip() if reasoning_m else "",
        "proposed_change": change_m.group(1).strip()    if change_m   else "",
        "modified_prompt": prompt_m.group(1).strip()    if prompt_m   else "",
        "raw":             response,
    }


# ---------------------------------------------------------------------------
# Optimizer loop for one example
# ---------------------------------------------------------------------------

def _optimize_example(example: dict, folder: Path, backend_eval, backend_opt,
                       current_template: str, max_tries: int,
                       no_dom_diff: bool, no_step1: bool) -> dict:
    """Run the optimizer loop for a single wrong example. Returns a result dict."""
    task_file, before, after = _resolve_paths(folder)
    task     = task_file.read_text().strip()
    dom_diff = _get_dom_diff(folder) if not no_dom_diff else "(omitted)"
    step1    = _get_step1_spec(folder) if not no_step1 else "(omitted)"

    ground_truth  = example["ground_truth"]
    predicted     = example.get("predicted", "?")
    wrong_response = example.get("response") or example.get("comment") or "(not available)"
    gt_criteria   = example.get("gt_criteria") or {}
    pred_criteria = example.get("pred_criteria") or {}
    criteria_cmp  = _criteria_comparison(gt_criteria, pred_criteria)

    working_template = current_template
    prev_attempts: list[dict] = []
    attempts: list[dict] = []

    for attempt_num in range(1, max_tries + 1):
        print(f"       attempt {attempt_num}/{max_tries}: optimizer... ", end="", flush=True)

        prev_section = ""
        if prev_attempts:
            prev_section = "\n\nPREVIOUS ATTEMPTS (all failed — try a different approach):\n"
            for i, pa in enumerate(prev_attempts, 1):
                prev_section += (
                    f"\nAttempt {i} proposed: {pa['proposed_change']}\n"
                    f"Result: evaluator still said {pa['result']}\n"
                )

        opt_prompt = _OPTIMIZER_PROMPT.format(
            current_prompt=working_template,
            task=task,
            dom_diff=dom_diff,
            step1=step1,
            wrong_response=wrong_response[:3000],  # cap to avoid huge context
            ground_truth=ground_truth,
            predicted=predicted,
            criteria_comparison=criteria_cmp,
            prev_attempts=prev_section,
        )

        try:
            opt_response = backend_opt.generate(
                opt_prompt,
                images=[before.read_bytes(), after.read_bytes()],
                max_tokens=8192,
            )
        except Exception as e:
            print(f"optimizer error: {e}")
            break

        parsed = _parse_optimizer_response(opt_response)

        if not parsed["modified_prompt"]:
            print("no MODIFIED_PROMPT found in response")
            attempts.append({
                "attempt":         attempt_num,
                "reasoning":       parsed["reasoning"],
                "proposed_change": parsed["proposed_change"],
                "new_verdict":     None,
                "success":         False,
                "error":           "no MODIFIED_PROMPT in optimizer response",
            })
            break

        modified_template = parsed["modified_prompt"]

        print("verifying... ", end="", flush=True)
        try:
            result = _run_with_template(
                folder, backend_eval, modified_template, no_dom_diff, no_step1)
            new_verdict = result.get("overall")
        except ValueError as e:
            print(f"bad template: {e}")
            attempts.append({
                "attempt":         attempt_num,
                "reasoning":       parsed["reasoning"],
                "proposed_change": parsed["proposed_change"],
                "modified_prompt": modified_template,
                "new_verdict":     None,
                "success":         False,
                "error":           str(e),
            })
            break
        except Exception as e:
            print(f"eval error: {e}")
            attempts.append({
                "attempt":         attempt_num,
                "reasoning":       parsed["reasoning"],
                "proposed_change": parsed["proposed_change"],
                "modified_prompt": modified_template,
                "new_verdict":     None,
                "success":         False,
                "error":           str(e),
            })
            continue

        success = new_verdict == ground_truth
        match   = "✓" if success else "✗"
        print(f"{new_verdict} {match}")

        attempts.append({
            "attempt":         attempt_num,
            "reasoning":       parsed["reasoning"],
            "proposed_change": parsed["proposed_change"],
            "modified_prompt": modified_template,
            "new_verdict":     new_verdict,
            "success":         success,
            "error":           None,
        })

        if success:
            break

        prev_attempts.append({
            "proposed_change": parsed["proposed_change"],
            "result":          new_verdict or "no verdict",
        })
        working_template = modified_template  # continue improving from here

    final_success = any(a["success"] for a in attempts)
    best = next((a for a in reversed(attempts) if a["success"]), attempts[-1] if attempts else {})

    return {
        "folder":           example["folder"],
        "ground_truth":     ground_truth,
        "original_verdict": predicted,
        "success":          final_success,
        "attempts":         attempts,
        "best":             best,
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _write_suggestions(results: list[dict], output_path: Path,
                        source_results: Path, args) -> None:
    n_success = sum(1 for r in results if r["success"])

    lines = [
        "# Prompt Optimizer Suggestions",
        "",
        f"Source results: `{source_results}`  ",
        f"Eval backend: `{args.eval_backend}`  ",
        f"Optimizer backend: `{args.optimizer_backend}`  ",
        f"Max tries per example: {args.max_tries}  ",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"**{n_success} / {len(results)} examples fixed by a prompt change**",
        "",
        "---",
        "",
    ]

    for group_success in [True, False]:
        group = [r for r in results if r["success"] == group_success]
        if not group:
            continue
        header = "Fixed ✓" if group_success else "Not Fixed ✗"
        lines += [f"## {header} ({len(group)} examples)", ""]

        for r in group:
            best = r["best"]
            lines += [
                f"### {r['folder']}",
                "",
                f"- Ground truth: **{r['ground_truth']}**",
                f"- Original verdict: {r['original_verdict']}",
                f"- Best new verdict: {best.get('new_verdict', '—')} "
                f"(attempt {best.get('attempt', '—')})",
                "",
            ]

            if best.get("reasoning"):
                lines += ["**Reasoning:**", best["reasoning"], ""]

            if best.get("proposed_change"):
                lines += ["**Proposed change:**", best["proposed_change"], ""]

            if best.get("modified_prompt"):
                lines += [
                    "<details>",
                    "<summary>Modified prompt (full text)</summary>",
                    "",
                    "```",
                    best["modified_prompt"],
                    "```",
                    "",
                    "</details>",
                    "",
                ]

            if len(r["attempts"]) > 1:
                lines += ["<details>", "<summary>All attempts</summary>", ""]
                for a in r["attempts"]:
                    mark = "✓" if a["success"] else "✗"
                    lines.append(f"**Attempt {a['attempt']} {mark}** — "
                                 f"verdict: {a.get('new_verdict') or a.get('error', '?')}")
                    if a.get("proposed_change"):
                        lines += [a["proposed_change"], ""]
                lines += ["</details>", ""]

            lines += ["---", ""]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Optimize the step2 evaluator prompt on specific wrong examples."
    )
    parser.add_argument("--results", required=True, metavar="RESULTS_JSON",
                        help="Results JSON from a previous evaluator run.")
    parser.add_argument("--skip", default="", metavar="INDICES",
                        help="Comma-separated 1-based indices of wrong examples to skip "
                             "(e.g. '1,3,4' skips the 1st, 3rd, 4th wrong example).")
    parser.add_argument("--max-tries", type=int, default=3,
                        help="Max optimizer attempts per example (default: 3).")
    parser.add_argument("--eval-backend", default="vertexai",
                        choices=["gemini", "vertexai", "anthropic", "openai"],
                        help="Backend for re-running the evaluator (default: vertexai).")
    parser.add_argument("--eval-model", default=None,
                        help="Model override for the eval backend.")
    parser.add_argument("--optimizer-backend", default="anthropic",
                        choices=["gemini", "anthropic", "openai"],
                        help="Backend for the optimizer LLM (default: anthropic).")
    parser.add_argument("--optimizer-model", default=None,
                        help="Model override for the optimizer (e.g. claude-opus-4-7).")
    parser.add_argument("--no-dom-diff", action="store_true",
                        help="Omit DOM diff (must match the original run's setting).")
    parser.add_argument("--no-step1", action="store_true",
                        help="Omit Step 1 spec (must match the original run's setting).")
    parser.add_argument("--output", default=None, metavar="PATH",
                        help="Output markdown file (default: Results/prompt_suggestions_<ts>.md).")
    args = parser.parse_args()

    results_path = Path(args.results).resolve()
    run_data     = json.loads(results_path.read_text())
    examples     = run_data.get("examples", [])

    wrong = [
        e for e in examples
        if e.get("ground_truth") and e.get("predicted")
        and e["ground_truth"] != e["predicted"]
    ]

    skip_indices: set[int] = set()
    if args.skip.strip():
        for s in args.skip.split(","):
            s = s.strip()
            if s.isdigit():
                skip_indices.add(int(s))

    targets = [(i + 1, e) for i, e in enumerate(wrong) if (i + 1) not in skip_indices]

    print(f"Wrong examples total: {len(wrong)}")
    print(f"Skipping:             {len(skip_indices)} (indices: {sorted(skip_indices)})")
    print(f"Targeting:            {len(targets)}")
    print()

    backend_eval = get_backend(args.eval_backend, args.eval_model,
                               endpoint_env_var="VERTEXAI_EVALUATOR_ENDPOINT_ID")
    backend_opt  = get_backend(args.optimizer_backend, args.optimizer_model)

    dataset_str  = run_data.get("dataset", "")
    dataset_path = Path(dataset_str) if dataset_str else None

    current_template = _PROMPT_FILE.read_text()

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = (
        Path(args.output).resolve() if args.output
        else _RESULTS_DIR / f"prompt_suggestions_{ts}.md"
    )

    all_results: list[dict] = []

    for list_idx, example in targets:
        folder_name = example["folder"]

        folder: Path | None = None
        if dataset_path and (dataset_path / folder_name).exists():
            folder = dataset_path / folder_name
        else:
            for candidate in [
                _ROOT / "Datasets" / "EvaluatorModelDataset" / folder_name,
                _ROOT / "Datasets" / "RawDataset" / folder_name,
            ]:
                if candidate.exists():
                    folder = candidate
                    break

        if folder is None:
            print(f"  [{list_idx}] {folder_name} — folder not found, skipping")
            continue

        gt = example["ground_truth"]
        print(f"  [{list_idx}] {folder_name}  (truth: {gt})")

        result = _optimize_example(
            example, folder, backend_eval, backend_opt,
            current_template, args.max_tries,
            args.no_dom_diff, args.no_step1,
        )
        result["list_idx"] = list_idx
        all_results.append(result)

        status = "FIXED ✓" if result["success"] else "not fixed"
        print(f"       → {status}")
        print()

        _write_suggestions(all_results, output_path, results_path, args)

    n_fixed = sum(1 for r in all_results if r["success"])
    print(f"Done: {n_fixed}/{len(all_results)} examples fixed.")
    print(f"Suggestions written to {output_path.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
