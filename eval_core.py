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


def build_prompt(task: str, before_code: str = None, after_code: str = None, diff: str = None) -> str:
    """Build the evaluation prompt.

    Pass before_code + after_code for full-code mode, or diff for diff mode.
    Exactly one of the two modes must be supplied.
    """
    if diff is not None:
        code_section = f"--- Code Diff (unified diff of Before → After) ---\n{diff}"
        code_description = "2. A screenshot of the UI after the revision\n3. A unified diff of the code changes made in the revision"
    else:
        code_section = f"--- Before Code ---\n{before_code}\n\n--- After Code ---\n{after_code}"
        code_description = "2. The full code of the UI before the revision\n3. A screenshot of the UI after the revision\n4. The full code of the UI after the revision"

    return f"""You are evaluating a UI revision.

Revision task: {task}

You are provided:
1. A screenshot of the UI before the revision
{code_description}

Did the revision correctly implement the task based on the UI output and code?

Respond with PASS or FAIL on the first line, followed by a brief explanation.

{code_section}
"""


def parse_verdict(response_text: str) -> str:
    first_line = response_text.splitlines()[0].upper()
    if "PASS" in first_line:
        return "PASS"
    if "FAIL" in first_line:
        return "FAIL"
    return "UNKNOWN"


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
