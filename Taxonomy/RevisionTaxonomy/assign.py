"""
Assign an unlabeled example to one or more existing revision taxonomy categories.

Given a revision task and Before screenshot, sends the task text, screenshot,
and existing taxonomy categories to Gemini and returns the matching category names.

Used by DatasetBuilder/RevisionGeneratorModel/check_missing.py to label examples
added after the initial taxonomy was generated. Can also be run standalone for
testing or one-off assignment.

Running:
    python Taxonomy/RevisionTaxonomy/assign.py --example Datasets/RawDataset/Participant_X_CaseStudy-Y.Z-MODEL
    python Taxonomy/RevisionTaxonomy/assign.py --example ... --model gemini-2.5-flash
"""

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
from backends import get_backend, Backend

_TAXONOMY_JSON = Path(__file__).parent / "Results" / "taxonomy.json"

_ASSIGN_PROMPT = """\
You are classifying a UI revision task into an existing taxonomy.

The revision task is:
"{task}"

The existing taxonomy categories are:
{categories_block}

Assign this task to one or more of the listed categories. Choose only from the
category names above — do not invent new categories.

Most tasks map to 1–2 categories. Assign multiple only if the task genuinely
spans distinct themes from different categories.

Return JSON only, no explanation:
{{"categories": ["Category Name", ...]}}"""


def _build_categories_block(taxonomy: dict) -> str:
    return "\n".join(
        f"- **{cat['name']}**: {cat['description']}"
        for cat in taxonomy["categories"]
    )


def _parse_response(response: str) -> list[str]:
    text = re.sub(r"```(?:json)?|```", "", response).strip()
    return [str(c).strip() for c in json.loads(text)["categories"]]


def assign(task: str, screenshot_bytes: bytes, taxonomy: dict, backend: "Backend") -> list[str]:
    """Assign task + screenshot to existing taxonomy categories. Returns list of category names."""
    prompt = _ASSIGN_PROMPT.format(
        task=task,
        categories_block=_build_categories_block(taxonomy),
    )
    response = backend.generate(prompt, images=[screenshot_bytes])
    return _parse_response(response)


def main():
    parser = argparse.ArgumentParser(
        description="Assign an example to existing revision taxonomy categories."
    )
    parser.add_argument("--example", metavar="PATH", required=True,
                        help="Path to example folder (must contain Task.txt and Before/screenshot.png).")
    parser.add_argument("--backend", default="gemini",
                        choices=["gemini", "vertexai", "anthropic", "openai"])
    parser.add_argument("--model", default=None,
                        help="Override model (optional).")
    args = parser.parse_args()

    if not _TAXONOMY_JSON.exists():
        raise SystemExit(f"Taxonomy not found at {_TAXONOMY_JSON} — run consolidate.py first.")

    taxonomy = json.loads(_TAXONOMY_JSON.read_text())
    backend = get_backend(args.backend, args.model)

    folder = Path(args.example)
    task_file = folder / "Task.txt"
    screenshot = folder / "Before" / "screenshot.png"

    if not task_file.exists():
        raise SystemExit(f"Task.txt not found in {folder}")
    if not screenshot.exists():
        raise SystemExit(f"Before/screenshot.png not found in {folder}")

    task = task_file.read_text().strip()
    categories = assign(task, screenshot.read_bytes(), taxonomy, backend)
    print(f"Categories: {categories}")


if __name__ == "__main__":
    main()
