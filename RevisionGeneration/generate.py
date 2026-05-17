"""
Generate UI revision tasks from a Before screenshot, conditioned on a taxonomy category.

By default, one task is generated per taxonomy category (7 total per screenshot).
Use --category to target a single category, and --count to generate multiple tasks
per category.

Running:
    # Generate one task per taxonomy category for one example
    python RevisionGeneration/generate.py --example Examples/CaseStudyExamples/task-10.1-claude

    # Generate tasks for every example in a directory
    python RevisionGeneration/generate.py --dir Examples/CaseStudyExamples

    # Target a specific taxonomy category
    python RevisionGeneration/generate.py --example ... --category "Clarify Function & State"

    # Generate multiple tasks per category
    python RevisionGeneration/generate.py --example ... --category "Add or Surface Functionality" --count 3

    # Save each task as Task.txt + screenshot.png under GeneratedRevisions/
    python RevisionGeneration/generate.py --dir Examples/CaseStudyExamples --save

    # Use the fine-tuned revision generator model on Vertex AI
    python RevisionGeneration/generate.py --example ... --backend vertexai
"""

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
from backends import Backend, get_backend

sys.path.insert(0, str(Path(__file__).parent))
from generate_core import generate_tasks

_DEFAULT_BACKEND = "gemini"
_TAXONOMY_JSON = _ROOT / "Taxonomy" / "RevisionTaxonomy" / "Results" / "taxonomy.json"
_GENERATED_ROOT = _ROOT / "GeneratedRevisions"


def _load_categories(category_name: str | None) -> list[dict]:
    """Load taxonomy categories, optionally filtered to a single named category."""
    taxonomy = json.loads(_TAXONOMY_JSON.read_text())
    categories = taxonomy["categories"]
    if category_name is None:
        return categories
    matched = [c for c in categories if c["name"] == category_name]
    if not matched:
        names = [c["name"] for c in categories]
        raise SystemExit(
            f"Category '{category_name}' not found.\nAvailable categories:\n"
            + "\n".join(f"  - {n}" for n in names)
        )
    return matched


def _screenshot_path(example_dir: Path) -> Path:
    candidates = [
        example_dir / "Before" / "screenshot.png",
        example_dir / "screenshot.png",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _save_task(task: str, screenshot_src: Path, category: dict, timestamp_base: str, idx: int) -> Path:
    """Write Task.txt, Category.txt, and screenshot.png under GeneratedRevisions/<name>/."""
    dest = _GENERATED_ROOT / f"{timestamp_base}_{idx}"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "Task.txt").write_text("\n".join(line.rstrip() for line in task.splitlines()))
    (dest / "Category.txt").write_text(f"{category['name']}\n{category['description']}\n")
    shutil.copy2(screenshot_src, dest / "screenshot.png")
    return dest


def _process_example(
    example_dir: Path,
    backend: Backend,
    categories: list[dict],
    count: int,
    save: bool,
) -> None:
    screenshot = _screenshot_path(example_dir)
    if not screenshot.exists():
        print(f"  [SKIP] {example_dir.name}: screenshot not found")
        return

    print(f"\n{'='*60}")
    print(f"Example: {example_dir.name}")

    timestamp_base = datetime.now().strftime("%Y%m%d_%H%M%S")
    idx = 1

    for category in categories:
        print(f"\n  [{category['name']}]")
        tasks = generate_tasks(screenshot, backend, category, count=count)
        for task in tasks:
            print(f"    {task[:120]}{'…' if len(task) > 120 else ''}")
            if save:
                dest = _save_task(task, screenshot, category, timestamp_base, idx)
                print(f"    → Saved to {dest.relative_to(_ROOT)}")
                idx += 1


def main():
    parser = argparse.ArgumentParser(
        description="Generate revision tasks from a Before screenshot, conditioned on a taxonomy category."
    )

    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--example", metavar="PATH",
                        help="Path to a single example directory.")
    target.add_argument("--dir", metavar="PATH",
                        help="Path to a directory of example subdirectories.")

    parser.add_argument("--category", metavar="NAME",
                        help="Taxonomy category to generate tasks for (default: all categories).")
    parser.add_argument("--count", type=int, default=1, metavar="N",
                        help="Tasks to generate per category per screenshot (default: 1).")
    parser.add_argument("--backend", default=_DEFAULT_BACKEND,
                        choices=["gemini", "vertexai", "anthropic", "openai"],
                        help=f"Model backend (default: {_DEFAULT_BACKEND}). "
                             "Use 'vertexai' for the fine-tuned revision generator model "
                             "(reads VERTEXAI_GENERATOR_ENDPOINT_ID from .env).")
    parser.add_argument("--model", default=None,
                        help="Override the model/endpoint (optional; uses backend default or env var).")
    parser.add_argument("--save", action="store_true",
                        help="Save each task as Task.txt + Category.txt + screenshot.png "
                             "under GeneratedRevisions/.")
    args = parser.parse_args()

    categories = _load_categories(args.category)

    backend = get_backend(args.backend, args.model,
                          endpoint_env_var="VERTEXAI_GENERATOR_ENDPOINT_ID")
    cat_desc = args.category or f"all {len(categories)} categories"
    model_label = backend.model if hasattr(backend, "model") else args.backend
    print(f"Backend: {args.backend} | Model: {model_label}  |  Categories: {cat_desc}  |  Tasks per category: {args.count}"
          + ("  |  Saving to GeneratedRevisions/" if args.save else ""))

    if args.example:
        example_dirs = [Path(args.example)]
    else:
        example_dirs = sorted(d for d in Path(args.dir).iterdir() if d.is_dir())

    for example_dir in example_dirs:
        _process_example(example_dir, backend, categories, count=args.count, save=args.save)


if __name__ == "__main__":
    main()
