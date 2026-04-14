"""
Evaluation logic: example loading, prompt building, and the single-step
evaluation pipeline. Backends are passed in as dependencies — this module
does not import any specific model provider.

The prompt mirrors the format used in FineTuning/build_dataset.py so that
evaluation is consistent with the fine-tuning training data.
"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backends import Backend

# Mirrors SYSTEM_INSTRUCTION in FineTuning/build_dataset.py.
SYSTEM_INSTRUCTION = (
    "You are evaluating whether a UI revision task was correctly implemented. "
    "You will be given the revision task description, the code diff, and before/after screenshots. "
    "Determine whether the task was successfully accomplished in the rendered UI.\n\n"

    "EVALUATION CRITERIA:\n"
    "1. The screenshots are the primary basis for your verdict. "
    "If the code change looks correct but the expected result is not visible in the after screenshot, the verdict is FAIL. "
    "Use the code diff only as conditioning — it tells you where and what to look for in the screenshots, "
    "not whether the task passed.\n"
    "2. If the after screenshot contains major visual changes unrelated to the task, the verdict is FAIL, "
    "even if the task itself was implemented correctly. "
    "Minor incidental differences such as slight spacing or subtle formatting shifts are acceptable.\n\n"

    "OUTPUT FORMAT:\n"
    "Respond with exactly the following structure:\n"
    "PASS or FAIL\n\n"
    "Code Reasoning: <one to two sentences describing what the diff shows and whether it targets the right elements>\n\n"
    "Image Reasoning: <one to two sentences describing what is visually different between the screenshots "
    "and whether the change satisfies the task>\n\n"

    "Example of a passing response:\n"
    "PASS\n\n"
    "Code Reasoning: The label elements have been updated to include a red asterisk (text-red-500), "
    "which directly addresses the task.\n\n"
    "Image Reasoning: In the after screenshot, a red asterisk is visible next to each input label. "
    "No other elements changed between the two screenshots.\n\n"

    "Example of a failing response:\n"
    "FAIL\n\n"
    "Code Reasoning: The diff changes the footer text color class from dark:text-slate-800 to dark:text-white, "
    "which is the correct element.\n\n"
    "Image Reasoning: The footer text color appears identical in both screenshots; "
    "the expected white text is not visible in the after screenshot."
)


def load_example(example_dir: Path) -> dict:
    """Load all inputs for one example. Images are kept as paths so backends
    can read them as bytes when needed."""
    after_dir = example_dir / "After"
    diff_path = after_dir / "diff.txt"
    return {
        "name":         example_dir.name,
        "task":         (example_dir / "Task.txt").read_text().strip(),
        "before_image": example_dir / "Before" / "screenshot.png",
        "after_image":  after_dir / "screenshot.png",
        "diff":         diff_path.read_text().strip() if diff_path.exists() else "",
    }


def _evaluation_prompt(task: str, diff: str) -> str:
    """Single-step prompt: system instruction + task + diff.
    Images are passed separately by the backend.
    Mirrors the user turn structure in FineTuning/build_dataset.py.
    """
    return (
        f"{SYSTEM_INSTRUCTION}\n\n"
        f"Revision task: {task}\n\n"
        f"Code diff (unified diff of Before → After):\n{diff}"
    )


def parse_verdict(response_text: str) -> str:
    """Scan all lines and return the last PASS/FAIL found."""
    verdict = "UNKNOWN"
    for line in response_text.splitlines():
        upper = line.strip().upper()
        if upper == "PASS":
            verdict = "PASS"
        elif upper == "FAIL":
            verdict = "FAIL"
    return verdict


def evaluate(example_dir: Path, backend: "Backend") -> dict:
    """Run single-step evaluation for one example.

    Sends the system instruction, task, diff, and before/after screenshots
    in a single model call. Matches the prompt format used during fine-tuning.
    """
    ex = load_example(example_dir)
    prompt = _evaluation_prompt(ex["task"], ex["diff"])
    images = [ex["before_image"].read_bytes(), ex["after_image"].read_bytes()]
    response_text = backend.generate(prompt, images=images)

    return {
        "name":     ex["name"],
        "task":     ex["task"],
        "verdict":  parse_verdict(response_text),
        "response": response_text,
    }
