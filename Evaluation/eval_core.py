"""
Evaluation logic: example loading, prompt building, and the two-step
evaluation pipeline. Backends are passed in as dependencies — this module
does not import any specific model provider.
"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backends import Backend

CODE_EXTENSIONS = {".html", ".css", ".js"}


def load_code(variant_dir: Path) -> str:
    """Concatenate all code files in a Before/ or After/ directory."""
    parts = []
    for f in sorted(variant_dir.iterdir()):
        if f.suffix in CODE_EXTENSIONS:
            parts.append(f"--- {f.name} ---\n{f.read_text()}")
    return "\n\n".join(parts)


def load_example(example_dir: Path) -> dict:
    """Load all inputs for one example. Images are kept as paths so backends
    can read them as bytes when needed."""
    before_dir = example_dir / "Before"
    after_dir  = example_dir / "After"
    diff_path  = after_dir / "diff.txt"
    return {
        "name":         example_dir.name,
        "task":         (example_dir / "Task.txt").read_text().strip(),
        "before_image": before_dir / "screenshot.png",
        "after_image":  after_dir  / "screenshot.png",
        "before_code":  load_code(before_dir),
        "after_code":   load_code(after_dir),
        "diff":         diff_path.read_text() if diff_path.exists() else None,
    }


def _code_analysis_prompt(task: str, before_code: str = None, after_code: str = None, diff: str = None) -> str:
    """Step 1: code-only prompt. No images. Produces a concrete visual expectation."""
    code_section = (
        f"--- Code Diff (unified diff of Before → After) ---\n{diff}"
        if diff is not None
        else f"--- Before Code ---\n{before_code}\n\n--- After Code ---\n{after_code}"
    )
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


def _visual_verification_prompt(task: str, expectation: str) -> str:
    """Step 2: visual prompt conditioned on the Step 1 expectation.

    The verdict is always whether the TASK was accomplished in the rendered UI —
    not whether the code-level expectation was accurate. This prevents a false PASS
    when Step 1 correctly predicts 'no change due to a bug' and Step 2 confirms it.
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
    """Scan all lines and return the last PASS/FAIL found."""
    verdict = "UNKNOWN"
    for line in response_text.splitlines():
        upper = line.upper().strip()
        if "PASS" in upper:
            verdict = "PASS"
        elif "FAIL" in upper:
            verdict = "FAIL"
    return verdict


def evaluate(example_dir: Path, backend: "Backend", use_diff: bool = False) -> dict:
    """Run the two-step evaluation pipeline for one example.

    Step 1 — code analysis (text-only): the backend reasons about the code change
    and produces a concrete visual expectation.
    Step 2 — visual verification (text + images): the expectation is used to direct
    the model's attention to the right element, avoiding open-ended comparison failure.
    """
    ex = load_example(example_dir)

    # Step 1: no images — pure code reasoning.
    code_prompt = _code_analysis_prompt(
        ex["task"],
        diff=ex["diff"] if use_diff else None,
        before_code=None if use_diff else ex["before_code"],
        after_code=None if use_diff else ex["after_code"],
    )
    expectation = backend.generate(code_prompt)

    # Step 2: images + expectation for targeted visual lookup.
    visual_prompt = _visual_verification_prompt(ex["task"], expectation)
    images = [ex["before_image"].read_bytes(), ex["after_image"].read_bytes()]
    response_text = backend.generate(visual_prompt, images=images)

    return {
        "name":    ex["name"],
        "task":    ex["task"],
        "verdict": parse_verdict(response_text),
        "response": (
            f"[Step 1 - Code Analysis]\n{expectation}\n\n"
            f"[Step 2 - Visual Verification]\n{response_text}"
        ),
    }
