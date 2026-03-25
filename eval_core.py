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


def build_prompt(task: str, before_code: str, after_code: str) -> str:
    return f"""You are evaluating a UI revision.

Revision task: {task}

You are provided:
1. A screenshot of the UI before the revision
2. The code of the UI before the revision
3. A screenshot of the UI after the revision
4. The code of the UI after the revision

Did the revision correctly implement the task based on the UI output and code?

Respond with PASS or FAIL on the first line, followed by a brief explanation.

--- Before Code ---
{before_code}

--- After Code ---
{after_code}
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
    return {
        "name": example_dir.name,
        "task": task,
        "before_image": before_dir / "screenshot.png",
        "after_image": after_dir / "screenshot.png",
        "before_code": load_code(before_dir),
        "after_code": load_code(after_dir),
    }
