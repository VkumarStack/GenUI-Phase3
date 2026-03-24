"""
Prototype evaluator: given one revision example, asks a VLM whether the
revision task was correctly implemented.

Supported backends (select via --backend flag):
  gemini  — Gemini 2.5 Pro via Google AI Studio (default)
  ollama  — Local model via Ollama (default model: qwen2.5vl:7b)

Input per example:
  - Before screenshot + code
  - Revision task description
  - After screenshot + code

Output: PASS or FAIL with brief reasoning from the model.

Running:
    evaluate.py
    evaluate.py --backend ollama
    evaluate.py --backend ollama --model qwen2.5vl:7b
"""

import argparse
import base64
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

EXAMPLES_DIR = Path(__file__).parent / "RevisionExamples"

DEFAULTS = {
    "gemini": "gemini-2.5-pro",
    "ollama": "qwen2.5vl:7b",
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def load_code(example_variant_dir: Path) -> str:
    """Concatenate all code files found in a Before/ or After/ directory.
    Each file is labeled with its filename so the model knows what it's reading."""
    code_extensions = {".html", ".css", ".js"}
    parts = []
    for f in sorted(example_variant_dir.iterdir()):
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


# ---------------------------------------------------------------------------
# Gemini backend
# ---------------------------------------------------------------------------

def evaluate_gemini(example_dir: Path, model: str) -> dict:
    from google import genai
    from google.genai import types

    task = (example_dir / "Task.txt").read_text().strip()
    before_dir = example_dir / "Before"
    after_dir = example_dir / "After"

    before_image = (before_dir / "screenshot.png").read_bytes()
    after_image = (after_dir / "screenshot.png").read_bytes()
    prompt = build_prompt(task, load_code(before_dir), load_code(after_dir))

    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    response = client.models.generate_content(
        model=model,
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
    return {
        "example": example_dir.name,
        "task": task,
        "verdict": parse_verdict(response_text),
        "response": response_text,
    }


# ---------------------------------------------------------------------------
# Ollama backend
# ---------------------------------------------------------------------------

def evaluate_ollama(example_dir: Path, model: str) -> dict:
    import ollama

    task = (example_dir / "Task.txt").read_text().strip()
    before_dir = example_dir / "Before"
    after_dir = example_dir / "After"

    # Ollama's Python client accepts images as base64-encoded strings or raw bytes.
    before_b64 = base64.b64encode((before_dir / "screenshot.png").read_bytes()).decode()
    after_b64 = base64.b64encode((after_dir / "screenshot.png").read_bytes()).decode()
    prompt = build_prompt(task, load_code(before_dir), load_code(after_dir))

    # Images are passed in the `images` list; the model sees them in order so
    # the prompt text references them as "before" and "after" respectively.
    response = ollama.chat(
        model=model,
        messages=[
            {
                "role": "user",
                "content": f"Before screenshot is image 1, after screenshot is image 2.\n\n{prompt}",
                "images": [before_b64, after_b64],
            }
        ],
    )

    response_text = response["message"]["content"].strip()
    return {
        "example": example_dir.name,
        "task": task,
        "verdict": parse_verdict(response_text),
        "response": response_text,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Evaluate UI revision examples with a VLM.")
    parser.add_argument(
        "--backend",
        choices=["gemini", "ollama"],
        default="gemini",
        help="Which model backend to use (default: gemini)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name override. Defaults: gemini=gemini-2.5-pro, ollama=qwen2.5vl:7b",
    )
    args = parser.parse_args()

    model = args.model or DEFAULTS[args.backend]
    evaluate_fn = evaluate_gemini if args.backend == "gemini" else evaluate_ollama

    example_dirs = sorted(d for d in EXAMPLES_DIR.iterdir() if d.is_dir())

    print(f"Backend: {args.backend}  |  Model: {model}")

    for example_dir in example_dirs:
        print(f"\n{'='*60}")
        print(f"Example: {example_dir.name}")
        print(f"Task: {(example_dir / 'Task.txt').read_text().strip()}")
        print("-" * 60)

        result = evaluate_fn(example_dir, model)

        print(f"Verdict: {result['verdict']}")
        print(f"\nModel response:\n{result['response']}")


if __name__ == "__main__":
    main()
