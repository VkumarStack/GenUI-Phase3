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

# Make Util + RevisionGeneration importable
sys.path.insert(0, str(ROOT / "Util"))
sys.path.insert(0, str(ROOT / "RevisionGeneration"))
from backends import get_backend  # noqa: E402
from generate_core import build_prompt, parse_tasks  # noqa: E402  (shared generation logic)

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
# Step 2: Task generation
#
# The prompt + parsing are the shared revision-generation logic in
# RevisionGeneration/generate_core.py (build_prompt / parse_tasks). This step
# adds the bytes-based call and retry loop specific to the MUD batch run.
# ---------------------------------------------------------------------------

def generate_tasks_for_category(
    screenshot_bytes: bytes,
    generator_backend,
    category: dict,
    count: int = TASKS_PER_CATEGORY,
    retries: int = 3,
) -> list[str]:
    prompt = build_prompt(category, count)

    for attempt in range(1, retries + 1):
        try:
            raw = generator_backend.generate(prompt, images=[screenshot_bytes])
            tasks = parse_tasks(raw, count)[:count]
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
    parser.add_argument(
        "--tasks-per-category", type=int, default=TASKS_PER_CATEGORY, metavar="N",
        help=f"Tasks to generate per applicable category (default: {TASKS_PER_CATEGORY}). "
             "Increase for a larger dataset.",
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
                cat_tasks = generate_tasks_for_category(
                    screenshot_bytes, generator_backend, cat, count=args.tasks_per_category)
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
