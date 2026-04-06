"""
Shared, backend-agnostic utilities for loading example data and building prompts.
"""

from pathlib import Path


def load_code(variant_dir: Path) -> str:
    """Concatenate all code files in a Before/ or After/ directory.
    Each file is labeled with its filename so the model knows what it's reading."""
    code_extensions = {".html", ".css", ".js"}
    parts = []
    for f in sorted(variant_dir.iterdir()):
        if f.suffix in code_extensions:
            parts.append(f"--- {f.name} ---\n{f.read_text()}")
    return "\n\n".join(parts)


def build_code_analysis_prompt(task: str, before_code: str = None, after_code: str = None, diff: str = None) -> str:
    """Step 1 prompt: reason about the code only, no images.

    Asks the model to determine whether the code change is a correct implementation
    of the task and to produce a concrete, visually observable expectation — e.g.
    'the footer text should be white' — that Step 2 can use for targeted visual lookup.
    """
    if diff is not None:
        code_section = f"--- Code Diff (unified diff of Before → After) ---\n{diff}"
    else:
        code_section = f"--- Before Code ---\n{before_code}\n\n--- After Code ---\n{after_code}"

    return f"""You are analyzing a UI code revision.

Revision task: {task}

{code_section}

Answer the following:
1. Does the code change correctly implement the task? Explain briefly.
2. If the implementation is correct, what specific and concrete visual change should
   be visible in the after screenshot? Name the exact element and property
   (e.g. "the footer text color should be white", "the submit button border-radius
   should appear pill-shaped / highly rounded").
   If the implementation is incorrect, describe what you would still expect to see
   visually (i.e. no change, or an unintended change).

Be precise — your answer will be used to direct a visual inspection of the screenshots.
"""


def build_visual_verification_prompt(task: str, expectation: str) -> str:
    """Step 2 prompt: visual verification conditioned on the Step 1 expectation.

    The expectation string from Step 1 is used to explicitly direct the model's
    attention to the right element and property, which is the key finding from
    testing: open-ended image comparison fails on subtle changes, but targeted
    lookup ("look at the footer text color") succeeds.

    Critically, the verdict is always whether the TASK was accomplished in the
    rendered UI — not whether the model's code-level expectation was accurate.
    This prevents a false PASS when Step 1 correctly predicts "no change due to
    a bug" and Step 2 confirms no change, which would otherwise appear as
    expectation-met but is actually a task failure.
    """
    return f"""You are verifying whether a UI revision was correctly implemented.

Revision task: {task}

A code analysis identified the following about the expected visual change.
Use this to direct your attention to the right element and property:
{expectation}

You are provided a before screenshot and an after screenshot.

1. Focus specifically on the element and property described above.
   Describe precisely what you see in that area in each screenshot.
2. Based solely on what is visible in the screenshots, was the revision task
   successfully accomplished in the rendered UI?

PASS means the task is visibly done in the after screenshot.
FAIL means it is not — regardless of whether the code attempted it.

Conclude with PASS or FAIL on its own line, followed by a one-sentence summary.
"""


def parse_verdict(response_text: str) -> str:
    # The scratchpad format puts PASS/FAIL near the end rather than the first line,
    # so scan all lines and return the verdict from the last line that contains one.
    verdict = "UNKNOWN"
    for line in response_text.splitlines():
        upper = line.upper().strip()
        if "PASS" in upper:
            verdict = "PASS"
        elif "FAIL" in upper:
            verdict = "FAIL"
    return verdict


def load_example(example_dir: Path) -> dict:
    """Load all inputs for one example. Returns paths and text; does not load images
    into memory so backends can handle image data in whatever format they need."""
    before_dir = example_dir / "Before"
    after_dir = example_dir / "After"
    task = (example_dir / "Task.txt").read_text().strip()

    diff_path = after_dir / "diff.txt"
    diff = diff_path.read_text() if diff_path.exists() else None

    return {
        "name": example_dir.name,
        "task": task,
        "before_image": before_dir / "screenshot.png",
        "after_image":  after_dir / "screenshot.png",
        "before_code": load_code(before_dir),
        "after_code":  load_code(after_dir),
        "diff": diff,
    }
