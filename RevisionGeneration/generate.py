"""
Generate UI revision tasks from a Before screenshot using Gemini 2.5 Pro.

Each generated task includes a motivation, a precise component description
anchored to the screenshot, and an unambiguous change specification.

Running:
    # Generate tasks for one example directory
    python RevisionGeneration/generate.py --example Examples/TestExamples/task-10.1-claude

    # Generate tasks for every example in a directory
    python RevisionGeneration/generate.py --dir Examples/TestExamples

    # Control how many tasks are generated per screenshot (default: 5)
    python RevisionGeneration/generate.py --example Examples/TestExamples/task-10.1-claude --count 3

    # Save each task as Task.txt + screenshot.png under GeneratedRevisions/<timestamp>/
    python RevisionGeneration/generate.py --dir Examples/TestExamples --save

    # Override the default model
    python RevisionGeneration/generate.py --example Examples/TestExamples/task-10.1-claude --model gemini-2.5-flash
"""

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / "Evaluation" / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent / "Evaluation"))
from backends import GeminiBackend

sys.path.insert(0, str(Path(__file__).parent))
from generate_core import generate_tasks

_DEFAULT_MODEL = "gemini-2.5-pro"
_GENERATED_ROOT = Path(__file__).parent.parent / "GeneratedRevisions"


def _screenshot_path(example_dir: Path) -> Path:
    candidates = [
        example_dir / "Before" / "screenshot.png",
        example_dir / "screenshot.png",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _save_task(task: str, screenshot_src: Path, timestamp_base: str, idx: int) -> Path:
    """Write Task.txt and screenshot.png under GeneratedRevisions/<timestamp_base>_<idx>/."""
    folder_name = f"{timestamp_base}_{idx}"
    dest = _GENERATED_ROOT / folder_name
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "Task.txt").write_text("\n".join(line.rstrip() for line in task.splitlines()))
    shutil.copy2(screenshot_src, dest / "screenshot.png")
    return dest


def _process_example(example_dir: Path, backend: GeminiBackend, count: int, save: bool) -> None:
    screenshot = _screenshot_path(example_dir)
    if not screenshot.exists():
        print(f"  [SKIP] {example_dir.name}: Before/screenshot.png not found")
        return

    print(f"\n{'='*60}")
    print(f"Example: {example_dir.name}")
    print("-" * 60)

    tasks = generate_tasks(screenshot, backend, count=count)

    timestamp_base = datetime.now().strftime("%Y%m%d_%H%M%S")

    for i, task in enumerate(tasks, start=1):
        print(f"\n[{i}] {task}")
        if save:
            dest = _save_task(task, screenshot, timestamp_base, i)
            print(f"     → Saved to {dest.relative_to(Path(__file__).parent.parent)}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate UI revision tasks from a Before screenshot using Gemini 2.5 Pro."
    )

    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--example", metavar="PATH",
                        help="Path to a single example directory (must contain Before/screenshot.png).")
    target.add_argument("--dir", metavar="PATH",
                        help="Path to a directory of example subdirectories.")

    parser.add_argument("--count", type=int, default=5, metavar="N",
                        help="Number of revision tasks to generate per screenshot (default: 5).")
    parser.add_argument("--model", default=_DEFAULT_MODEL,
                        help=f"Gemini model to use (default: {_DEFAULT_MODEL}).")
    parser.add_argument("--save", action="store_true",
                        help="Save each generated task as Task.txt + screenshot.png under "
                             "GeneratedRevisions/<timestamp_index>/.")
    args = parser.parse_args()

    backend = GeminiBackend(args.model)
    print(f"Model: {backend.model}  |  Tasks per screenshot: {args.count}"
          + ("  |  Saving to GeneratedRevisions/" if args.save else ""))

    if args.example:
        example_dirs = [Path(args.example)]
    else:
        example_dirs = sorted(d for d in Path(args.dir).iterdir() if d.is_dir())

    for example_dir in example_dirs:
        _process_example(example_dir, backend, count=args.count, save=args.save)


if __name__ == "__main__":
    main()
