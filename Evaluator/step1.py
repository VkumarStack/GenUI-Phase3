"""
Step 1 of the evaluation pipeline: generate an expected-change specification.

Given a revision task and Before screenshot, produces a grounded spec describing
what the revised interface should look like. This spec is passed as context to
the Step 2 evaluator.

The prompt lives in step1_prompt.txt (only {task} placeholder).

Step 1 only depends on the task + Before screenshot, which are identical across
all model variants of the same case study. Results are keyed by the deduplicated
Participant+CaseStudy key so all variants can share one spec.

For running over the full dataset (finding and filling missing entries), use:
    python DatasetBuilder/EvaluatorModel/fill_step1.py

Running standalone (single example, for testing):
    python Evaluator/step1.py --example Datasets/RawDataset/Participant_2_CaseStudy-1.1-CLAUDE
    python Evaluator/step1.py --example ... --model gemini-2.5-flash
"""

import argparse
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
from backends import GeminiBackend

_PROMPT_FILE = Path(__file__).parent / "step1_prompt.txt"
_DEFAULT_MODEL = "gemini-2.5-pro"
_MODEL_SUFFIX = re.compile(r"-(CLAUDE|GEMINI|OPENAI)$")


def unique_key(folder_name: str) -> str:
    """Strip model suffix to get the deduplicated example key."""
    return _MODEL_SUFFIX.sub("", folder_name)


def run_one(folder: Path, backend: GeminiBackend) -> dict:
    """Generate a Step 1 expected-change spec for one example folder."""
    task = (folder / "Task.txt").read_text().strip()
    screenshot = folder / "Before" / "screenshot.png"

    if not screenshot.exists():
        return {"error": f"Before/screenshot.png not found in {folder.name}"}

    prompt = _PROMPT_FILE.read_text().format(task=task)
    response = backend.generate(prompt, images=[screenshot.read_bytes()])

    return {
        "task": task,
        "representative_folder": folder.name,
        "expected_change_spec": response,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Step 1: generate an expected-change spec for a single example (testing)."
    )
    parser.add_argument("--example", metavar="PATH", required=True,
                        help="Path to example folder (must contain Task.txt and Before/screenshot.png).")
    parser.add_argument("--model", default=_DEFAULT_MODEL,
                        help=f"Gemini model (default: {_DEFAULT_MODEL}).")
    args = parser.parse_args()

    backend = GeminiBackend(args.model)
    result = run_one(Path(args.example), backend)
    if "error" in result:
        raise SystemExit(f"ERROR: {result['error']}")
    print(result["expected_change_spec"])


if __name__ == "__main__":
    main()
