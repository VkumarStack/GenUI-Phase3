"""
Prototype evaluator: given one revision example, asks Gemini 2.5 Pro whether
the revision task was correctly implemented.

Input per example:
  - Before screenshot + code
  - Revision task description
  - After screenshot + code

Output: PASS or FAIL with brief reasoning from the model.

Running:
    /Users/vivek/miniforge3/envs/GenUI/bin/python evaluate.py
"""

import os
import base64
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

EXAMPLES_DIR = Path(__file__).parent / "RevisionExamples"
MODEL = "gemini-2.5-pro"


def load_image_as_bytes(image_path: Path) -> bytes:
    return image_path.read_bytes()


def load_code(example_variant_dir: Path) -> str:
    """Concatenate all code files found in a Before/ or After/ directory.
    Each file is labeled with its filename so the model knows what it's reading."""
    code_extensions = {".html", ".css", ".js"}
    parts = []
    for f in sorted(example_variant_dir.iterdir()):
        if f.suffix in code_extensions:
            parts.append(f"--- {f.name} ---\n{f.read_text()}")
    return "\n\n".join(parts)


def evaluate_example(client: genai.Client, example_dir: Path) -> dict:
    """Run the evaluation for a single example directory and return the result."""

    task = (example_dir / "Task.txt").read_text().strip()

    before_dir = example_dir / "Before"
    after_dir = example_dir / "After"

    before_image = load_image_as_bytes(before_dir / "screenshot.png")
    after_image = load_image_as_bytes(after_dir / "screenshot.png")
    before_code = load_code(before_dir)
    after_code = load_code(after_dir)

    # Minimal prompt: provide all context and ask for a simple pass/fail judgment.
    # The model receives images and code for both states so it can reason over
    # both visual output and implementation simultaneously.
    prompt = f"""You are evaluating a UI revision.

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

    response = client.models.generate_content(
        model=MODEL,
        contents=[
            # Images are interleaved with the text so the model can associate
            # "before" and "after" labels with the correct screenshots.
            types.Part.from_text(text="Before screenshot:"),
            types.Part.from_bytes(data=before_image, mime_type="image/png"),
            types.Part.from_text(text="After screenshot:"),
            types.Part.from_bytes(data=after_image, mime_type="image/png"),
            types.Part.from_text(text=prompt),
        ],
    )

    response_text = response.text.strip()
    first_line = response_text.splitlines()[0].upper()
    verdict = "PASS" if "PASS" in first_line else "FAIL" if "FAIL" in first_line else "UNKNOWN"

    return {
        "example": example_dir.name,
        "task": task,
        "verdict": verdict,
        "response": response_text,
    }


def main():
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

    example_dirs = sorted(
        d for d in EXAMPLES_DIR.iterdir() if d.is_dir()
    )

    for example_dir in example_dirs:
        print(f"\n{'='*60}")
        print(f"Example: {example_dir.name}")
        print(f"Task: {(example_dir / 'Task.txt').read_text().strip()}")
        print("-" * 60)

        result = evaluate_example(client, example_dir)

        print(f"Verdict: {result['verdict']}")
        print(f"\nModel response:\n{result['response']}")


if __name__ == "__main__":
    main()
