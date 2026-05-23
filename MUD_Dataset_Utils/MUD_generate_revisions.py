"""
Two-step revision generation for the MUD_GenreUI dataset.

Step 1 — Taxonomy filter (base Gemini 2.5 Pro):
    For each screen's rendered screenshot, ask the model which of the 7 taxonomy
    categories have meaningful revision opportunities. Categories where no useful
    revision exists are skipped.

Step 2 — Task generation (fine-tuned VertexAI generator):
    For each applicable category, generate 3 revision tasks.

Output: Datasets/MUD_GenreUI/revisions.json
    {
      "<id>": {
        "applicable_categories": ["..."],
        "tasks": {
          "<category>": ["task1", "task2", "task3"]
        }
      }
    }

Resume-safe: screens already present in revisions.json are skipped.

Usage:
    python MUD_generate_revisions.py [--backend vertexai|gemini]
"""

import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent  # project root (GenUI/)
load_dotenv(ROOT / "Util/.env")

# Make Util importable
sys.path.insert(0, str(ROOT / "Util"))
from backends import get_backend  # noqa: E402

DATASET_DIR   = ROOT / "Datasets/MUD_GenreUI"
SCREENSHOTS   = DATASET_DIR / "screenshots"
TAXONOMY_PATH = ROOT / "Taxonomy/RevisionTaxonomy/Results/taxonomy.json"
OUTPUT_JSON   = DATASET_DIR / "revisions.json"

TASKS_PER_CATEGORY = 3
RETRY_DELAY = 5


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

def load_taxonomy() -> list[dict]:
    return json.loads(TAXONOMY_PATH.read_text())["categories"]


# ---------------------------------------------------------------------------
# Step 1: Taxonomy applicability filter
# ---------------------------------------------------------------------------

_FILTER_PROMPT_TEMPLATE = """\
You are a UI/UX expert reviewing a mobile app screenshot.

Below are 7 revision categories. For each one, decide whether this particular \
screenshot has a MEANINGFUL revision opportunity — i.e. a concrete, useful change \
that a designer or engineer could make. Skip a category only if it genuinely does \
not apply (e.g. "Improve Readability & Accessibility" on a screen that is already \
perfectly legible with high contrast and large text).

Revision categories:
{category_list}

Return ONLY a JSON array of the applicable category names, in the same spelling as \
above. No explanation, no markdown fences — just the JSON array.

Example output:
["Refine Layout & Spacing", "Clarify Function & State"]
"""


def build_filter_prompt(categories: list[dict]) -> str:
    category_list = "\n".join(
        f"  {i+1}. {c['name']}: {c['description']}"
        for i, c in enumerate(categories)
    )
    return _FILTER_PROMPT_TEMPLATE.format(category_list=category_list)


def filter_applicable_categories(
    screenshot_bytes: bytes,
    gemini_backend,
    categories: list[dict],
    retries: int = 3,
) -> list[str]:
    valid_names = {c["name"] for c in categories}
    prompt = build_filter_prompt(categories)

    for attempt in range(1, retries + 1):
        try:
            raw = gemini_backend.generate(prompt, images=[screenshot_bytes])
            # Strip markdown fences if present
            text = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                raise ValueError(f"Expected list, got {type(parsed)}")
            # Validate names
            valid = [n for n in parsed if n in valid_names]
            unknown = [n for n in parsed if n not in valid_names]
            if unknown:
                print(f"    warning: unknown category names ignored: {unknown}")
            return valid
        except Exception as e:
            print(f"    filter attempt {attempt}: {e}")
            time.sleep(RETRY_DELAY * attempt)

    raise RuntimeError(f"filter_applicable_categories failed after {retries} attempts")


# ---------------------------------------------------------------------------
# Step 2: Task generation (reuses generate_core logic inline)
# ---------------------------------------------------------------------------

import re

_SYSTEM_BASE = (
    "You are a UI/UX product expert generating revision task specifications for "
    "software engineers. You will be shown a screenshot of a mobile or web UI and "
    "asked to generate a concrete revision task.\n\n"

    "SCOPE GUIDELINES:\n"
    "Each task should be a minor, targeted revision — roughly one incremental step "
    "above the current state of the UI (think n → n+1, not n → n+10). A good task "
    "touches one to three components. Avoid:\n"
    "  • Trivially cosmetic changes (e.g. shifting one element by a pixel).\n"
    "  • Sweeping redesigns that restructure the entire layout or replace multiple "
    "sections of the page at once.\n\n"

    "REVISION TYPE — your task must belong to this category:\n"
    "  {category_name}: {category_description}\n\n"

    "EACH TASK MUST CONTAIN ALL THREE OF THE FOLLOWING:\n"
    "  (a) Motivation: Why is this change needed? Explain what is currently "
    "suboptimal or what goal the revision serves, framed in terms of the revision "
    "type above.\n"
    "  (b) Precise component identification: Name the specific component(s) to be "
    "changed and describe their current appearance and location in the screenshot "
    "(e.g. 'the dark blue primary action button labeled \"Continue\" in the bottom "
    "center of the screen', or 'the row of three icon buttons in the top-right "
    "corner of the navigation bar').\n"
    "  (c) Unambiguous change description: Describe exactly what the component "
    "should look like or do after the revision. Leave no room for interpretation — "
    "if a color is changing, say which color; if text is moving, say where it "
    "should end up.\n\n"

    "EXAMPLE OUTPUT (category: Clarify Function & State):\n"
    "The \"Continue\" button is fully green and active even though no departure "
    "point has been selected yet. This could lead to errors if the user taps "
    "Continue without selecting anything. Set the Continue button to a "
    "disabled/muted state by using a faint green at 20% opacity instead of the "
    "full green.\n\n"
)

_FORMAT_MULTI = (
    "OUTPUT FORMAT:\n"
    "Return exactly {count} numbered tasks. Each task is a short, self-contained "
    "paragraph of two to four sentences. Use this format:\n"
    "1. <task text>\n"
    "2. <task text>\n"
    "...\n"
    "Do not include any preamble, section headers, or closing remarks — only the "
    "numbered list."
)


def _build_generation_prompt(category: dict, count: int) -> str:
    base = _SYSTEM_BASE.format(
        category_name=category["name"],
        category_description=category["description"],
    )
    fmt = _FORMAT_MULTI.format(count=count)
    return base + fmt + "\n\nGenerate the revision task(s) for the UI shown in the screenshot."


def _parse_tasks(text: str, count: int) -> list[str]:
    pattern = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
    splits = pattern.split(text)
    tasks = [t.strip() for t in splits if t.strip()]
    return tasks[:count]


def generate_tasks_for_category(
    screenshot_bytes: bytes,
    generator_backend,
    category: dict,
    count: int = TASKS_PER_CATEGORY,
    retries: int = 3,
) -> list[str]:
    prompt = _build_generation_prompt(category, count)

    for attempt in range(1, retries + 1):
        try:
            raw = generator_backend.generate(prompt, images=[screenshot_bytes])
            tasks = _parse_tasks(raw, count)
            if tasks:
                return tasks
            print(f"    gen attempt {attempt}: parsed 0 tasks from response, retrying...")
        except Exception as e:
            print(f"    gen attempt {attempt}: {e}")
        time.sleep(RETRY_DELAY * attempt)

    raise RuntimeError(f"generate_tasks_for_category failed for '{category['name']}' after {retries} attempts")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend", default="vertexai",
        choices=["vertexai", "gemini"],
        help="Backend for the revision generator (default: vertexai for fine-tuned model)",
    )
    parser.add_argument(
        "--id", metavar="ID",
        help="Process a single screen ID (overwrites any existing entry for that ID).",
    )
    args = parser.parse_args()

    categories = load_taxonomy()

    # Load existing results for resume support
    if OUTPUT_JSON.exists():
        results = json.loads(OUTPUT_JSON.read_text())
        print(f"Loaded {len(results)} existing entries from {OUTPUT_JSON}")
    else:
        results = {}

    screenshots = sorted(SCREENSHOTS.glob("*.png"), key=lambda p: int(p.stem))
    if not screenshots:
        sys.exit(f"No screenshots found in {SCREENSHOTS}. Run MUD_screenshot.py first.")

    if args.id:
        png = SCREENSHOTS / f"{args.id}.png"
        if not png.exists():
            sys.exit(f"No screenshot found for ID {args.id} in {SCREENSHOTS}")
        todo = [png]
        print(f"Single-screen mode: {args.id}")
    else:
        todo = [p for p in screenshots if p.stem not in results]
        print(f"Total screens: {len(screenshots)}, done: {len(screenshots) - len(todo)}, remaining: {len(todo)}")

    if not todo:
        print("All screens already processed.")
        return

    # Initialise backends
    gemini_backend = get_backend("gemini")  # always Gemini 2.5 Pro for filter step
    if args.backend == "vertexai":
        generator_backend = get_backend("vertexai", endpoint_env_var="VERTEXAI_GENERATOR_ENDPOINT_ID")
    else:
        generator_backend = get_backend("gemini")

    for i, png in enumerate(todo, 1):
        id_ = png.stem
        print(f"[{i}/{len(todo)}] {id_}")

        screenshot_bytes = png.read_bytes()

        # Step 1: filter
        try:
            applicable = filter_applicable_categories(screenshot_bytes, gemini_backend, categories)
        except Exception as e:
            print(f"  FAILED (filter): {e}")
            results[id_] = {"applicable_categories": [], "tasks": {}, "error": str(e)}
            OUTPUT_JSON.write_text(json.dumps(results, indent=2))
            continue

        print(f"  applicable ({len(applicable)}): {applicable}")

        # Step 2: generate tasks per applicable category
        tasks = {}
        for cat_name in applicable:
            cat = next(c for c in categories if c["name"] == cat_name)
            try:
                cat_tasks = generate_tasks_for_category(screenshot_bytes, generator_backend, cat)
                tasks[cat_name] = cat_tasks
                print(f"    {cat_name}: {len(cat_tasks)} tasks")
            except Exception as e:
                print(f"    FAILED ({cat_name}): {e}")
                tasks[cat_name] = []

        results[id_] = {"applicable_categories": applicable, "tasks": tasks}
        OUTPUT_JSON.write_text(json.dumps(results, indent=2))

    print(f"\nDone. Results saved to {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
