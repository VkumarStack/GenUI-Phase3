"""
Two-stage evaluation pipeline.

Stage 1: Given the task and Before screenshot, the model generates a visually
         descriptive checklist of what it expects to change.

Stage 2: Given the task, Before/After screenshots, code diff, and the Stage 1
         checklist, the model verifies each checklist item visually and renders
         a PASS/FAIL verdict.

Backends are passed in as dependencies — this module does not import any
specific model provider.
"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backends import Backend

from eval_core import load_example, parse_verdict

# ---------------------------------------------------------------------------
# Stage 1
# ---------------------------------------------------------------------------

_STAGE1_SYSTEM = (
    "You are a UI expert preparing a visual checklist for a review task. "
    "You will be given a UI revision task description and a 'Before' screenshot of the UI. "
    "Your job is to produce a numbered checklist of the specific visual changes you expect "
    "to see in the 'After' screenshot based solely on the task description.\n\n"
    "GUIDELINES:\n"
    "1. Each item must be a concrete, visually descriptive expectation — reference specific "
    "UI components by their appearance and position (e.g. 'the blue Submit button in the "
    "bottom-right corner', 'the header text that currently reads Sign In'). "
    "Avoid vague language like 'the element should change'.\n"
    "2. Focus only on what the task explicitly asks for. Do not invent requirements that "
    "are not implied by the task.\n"
    "3. Be as specific as possible about color, size, position, text, or any other visual "
    "property relevant to the task so that the checklist can be used for precise visual "
    "inspection in the next review stage.\n\n"
    "OUTPUT FORMAT:\n"
    "Return only the numbered checklist. No preamble, no summary — just the list items.\n\n"
    "Example:\n"
    "1. The password input field (currently below the email field) should now display a "
    "show/hide toggle icon on its right edge.\n"
    "2. The toggle icon should be an eye or eye-slash symbol in a muted gray color."
)


def _stage1_prompt(task: str) -> str:
    return f"{_STAGE1_SYSTEM}\n\nRevision task: {task}"


# ---------------------------------------------------------------------------
# Stage 2
# ---------------------------------------------------------------------------

_STAGE2_SYSTEM = (
    "You are evaluating whether a UI revision task was correctly implemented. "
    "You will be given the revision task, a visual checklist of expected changes, "
    "the code diff, and Before/After screenshots.\n\n"
    "EVALUATION APPROACH:\n"
    "1. Work through every item in the checklist and verify it visually using the "
    "Before and After screenshots. Visual inspection of the screenshots is the most "
    "important part of your evaluation — it is the ground truth.\n"
    "2. The code diff is provided only as guidance to help you locate what changed. "
    "Do NOT pass a task based on the diff alone; if the expected result is not visible "
    "in the After screenshot the verdict is FAIL.\n"
    "3. The final checklist item reminds you to check for unintended major changes. "
    "Apply reasonable strictness: minor incidental differences such as slight spacing "
    "or subtle formatting shifts are acceptable and should not cause a FAIL.\n"
    "4. Every checklist item must be satisfied for the verdict to be PASS.\n\n"
    "OUTPUT FORMAT:\n"
    "Respond with exactly the following structure:\n"
    "PASS or FAIL\n\n"
    "Code Reasoning: <one to two sentences on what the diff shows and whether it "
    "targets the right elements>\n\n"
    "Image Reasoning: <one to two sentences on what is visually different between "
    "the screenshots and whether the changes satisfy every checklist item>\n\n"
    "Example of a passing response:\n"
    "PASS\n\n"
    "Code Reasoning: The label elements have been updated to include a red asterisk "
    "(text-red-500), which directly addresses the task.\n\n"
    "Image Reasoning: In the after screenshot, a red asterisk is visible next to each "
    "input label. All checklist items are satisfied and no other elements changed.\n\n"
    "Example of a failing response:\n"
    "FAIL\n\n"
    "Code Reasoning: The diff changes the footer text color class from dark:text-slate-800 "
    "to dark:text-white, which is the correct element.\n\n"
    "Image Reasoning: The footer text color appears identical in both screenshots; "
    "the expected white text is not visible in the after screenshot."
)

_NO_MAJOR_CHANGES_ITEM = (
    "There are no other MAJOR visual differences in the After screenshot beyond "
    "those listed above. (Minor incidental differences such as slight spacing or "
    "subtle formatting shifts are acceptable — apply reasonable strictness.)"
)


def _stage2_prompt(task: str, diff: str, checklist: str) -> str:
    numbered_items = [l for l in checklist.strip().splitlines() if l.strip()]
    next_number = len(numbered_items) + 1
    full_checklist = checklist.strip() + f"\n{next_number}. {_NO_MAJOR_CHANGES_ITEM}"
    return (
        f"{_STAGE2_SYSTEM}\n\n"
        f"Revision task: {task}\n\n"
        f"Visual checklist of expected changes:\n{full_checklist}\n\n"
        f"Code diff (unified diff of Before → After):\n{diff}"
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def evaluate_two_stage(example_dir: Path, backend: "Backend") -> dict:
    """Run the two-stage evaluation for one example.

    Stage 1: Before screenshot + task → visual checklist.
    Stage 2: Before + After screenshots + diff + checklist → verdict.
    """
    ex = load_example(example_dir)

    # Stage 1 — checklist generation (Before screenshot only).
    stage1_prompt = _stage1_prompt(ex["task"])
    before_bytes = ex["before_image"].read_bytes()
    checklist = backend.generate(stage1_prompt, images=[before_bytes])

    # Stage 2 — verdict (Before + After screenshots + diff + checklist).
    stage2_prompt = _stage2_prompt(ex["task"], ex["diff"], checklist)
    after_bytes = ex["after_image"].read_bytes()
    response_text = backend.generate(stage2_prompt, images=[before_bytes, after_bytes])

    return {
        "name":      ex["name"],
        "task":      ex["task"],
        "checklist": checklist,
        "verdict":   parse_verdict(response_text),
        "response":  response_text,
    }
