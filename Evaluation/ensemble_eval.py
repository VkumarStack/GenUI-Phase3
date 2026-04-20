"""
Ensemble evaluation: multiple worker models each run the standard eval_core
evaluation, then an aggregator model reviews all worker responses alongside
the original inputs to make a final decision.

The aggregator is explicitly instructed that a majority vote should NOT
mechanically drive the verdict — some models miss certain visual details.
"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backends import Backend

AGGREGATOR_SYSTEM_INSTRUCTION = (
    "You are a senior evaluator reviewing whether a UI revision task was correctly implemented. "
    "You have been provided the revision task description, the code diff, before/after screenshots, "
    "and the reasoning from a set of worker models that each independently evaluated the same example.\n\n"

    "YOUR ROLE:\n"
    "Use the worker models' reasoning as a guide for *what to look for* in the screenshots — "
    "their Code Reasoning tells you which elements the diff targets; their Image Reasoning tells you "
    "what each model observed visually. Treat their reasoning as a set of expert opinions, not as votes.\n\n"

    "CRITICAL WARNINGS:\n"
    "1. A majority of workers voting PASS does NOT mean the verdict is PASS. "
    "Some models consistently miss subtle visual differences, color changes, or layout shifts. "
    "If even one worker raises a credible concern about the after screenshot, investigate it carefully.\n"
    "2. A majority of workers voting FAIL does NOT mean the verdict is FAIL. "
    "Some models over-flag minor incidental differences that are acceptable. "
    "Use the screenshots as your primary evidence.\n"
    "3. The screenshots are your ground truth. Worker verdicts are advisory only.\n\n"

    "EVALUATION CRITERIA:\n"
    "1. The screenshots are the primary basis for your verdict. "
    "If the code change looks correct but the expected result is not visible in the after screenshot, the verdict is FAIL.\n"
    "2. If the after screenshot contains major visual changes unrelated to the task, the verdict is FAIL, "
    "even if the task itself was implemented correctly. "
    "Minor incidental differences such as slight spacing or subtle formatting shifts are acceptable.\n\n"

    "OUTPUT FORMAT:\n"
    "Respond with exactly the following structure:\n"
    "PASS or FAIL\n\n"
    "Worker Summary: <one to two sentences summarizing what the workers agreed and disagreed on, "
    "and whether any raised concerns worth flagging>\n\n"
    "Code Reasoning: <one to two sentences describing what the diff shows and whether it targets the right elements>\n\n"
    "Image Reasoning: <one to two sentences describing what is visually different between the screenshots "
    "and whether the change satisfies the task>\n\n"

    "Example of a passing response:\n"
    "PASS\n\n"
    "Worker Summary: Three of four workers agreed this was a PASS. One worker flagged a color difference "
    "but appeared to mistake the before screenshot for the after.\n\n"
    "Code Reasoning: The label elements have been updated to include a red asterisk (text-red-500), "
    "which directly addresses the task.\n\n"
    "Image Reasoning: In the after screenshot, a red asterisk is visible next to each input label. "
    "No other elements changed between the two screenshots.\n\n"

    "Example of a failing response:\n"
    "FAIL\n\n"
    "Worker Summary: Workers were split 2-2. Workers that voted PASS did not mention observing the "
    "expected color change in the after screenshot.\n\n"
    "Code Reasoning: The diff changes the footer text color class from dark:text-slate-800 to dark:text-white, "
    "which is the correct element.\n\n"
    "Image Reasoning: The footer text color appears identical in both screenshots; "
    "the expected white text is not visible in the after screenshot."
)


def _worker_summary_block(worker_results: list[dict]) -> str:
    lines = []
    for i, w in enumerate(worker_results, 1):
        lines.append(f"--- Worker {i} ({w['worker_label']}) ---")
        lines.append(f"Verdict: {w['verdict']}")
        lines.append(w["response"])
        lines.append("")
    return "\n".join(lines)


def _aggregator_prompt(task: str, diff: str, worker_results: list[dict]) -> str:
    worker_block = _worker_summary_block(worker_results)
    return (
        f"{AGGREGATOR_SYSTEM_INSTRUCTION}\n\n"
        f"Revision task: {task}\n\n"
        f"Code diff (unified diff of Before → After):\n{diff}\n\n"
        f"Worker model evaluations:\n{worker_block}"
    )


def ensemble_evaluate(example_dir: Path, worker_backends: list[tuple[str, "Backend"]], aggregator_backend: "Backend") -> dict:
    """Run ensemble evaluation for one example.

    worker_backends: list of (label, Backend) pairs — each runs the standard eval.
    aggregator_backend: Backend that makes the final decision.
    """
    from eval_core import load_example, _evaluation_prompt, parse_verdict

    ex = load_example(example_dir)
    images = [ex["before_image"].read_bytes(), ex["after_image"].read_bytes()]
    worker_prompt = _evaluation_prompt(ex["task"], ex["diff"])

    worker_results = []
    for label, backend in worker_backends:
        try:
            response_text = backend.generate(worker_prompt, images=images)
        except Exception as e:
            response_text = f"ERROR: {e}"
        worker_results.append({
            "worker_label": label,
            "verdict":      parse_verdict(response_text),
            "response":     response_text,
        })

    agg_prompt = _aggregator_prompt(ex["task"], ex["diff"], worker_results)
    aggregator_response = aggregator_backend.generate(agg_prompt, images=images)

    return {
        "name":               ex["name"],
        "task":               ex["task"],
        "verdict":            parse_verdict(aggregator_response),
        "aggregator_response": aggregator_response,
        "worker_results":     worker_results,
    }
