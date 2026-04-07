"""
Imports a case study zip and prepares it for evaluation.

Expected zip structure (flat or nested):
    task-X-issue.txt        — task description
    before-task-X.html      — before code
    after-task-X-MODEL.html — after code

For each task found in the zip this script will:
  1. Write Before/, After/, and Task.txt under --output-dir/task-X-MODEL/
  2. Render screenshots (via screenshot.py)
  3. Generate After/diff.txt (via diff.py)

Usage:
    python import_case_study.py path/to/study.zip --output-dir path/to/Examples/CaseStudyExamples
    python import_case_study.py path/to/study.zip --output-dir path/to/output --dry-run
    python import_case_study.py path/to/study.zip --output-dir path/to/output --viewport 1280x800 --full-page
"""

import argparse
import re
import sys
import zipfile
from pathlib import Path

# Allow imports from the same Util/ directory regardless of invocation location.
sys.path.insert(0, str(Path(__file__).parent))
from diff import write_diff
from screenshot import screenshot_examples


def parse_zip(zip_path: Path) -> list[dict]:
    """Extract and parse task folders from the zip.

    Supports both flat zips (files at root) and nested zips (files in a subfolder).
    Returns a list of dicts: { name, task, before_html, after_html }.
    """
    tasks = []
    with zipfile.ZipFile(zip_path) as zf:
        all_entries = [e for e in zf.namelist() if not e.endswith("/")]
        has_subfolders = any(len(Path(e).parts) > 1 for e in all_entries)

        if has_subfolders:
            folders: dict[str, dict] = {}
            for entry in all_entries:
                parts = Path(entry).parts
                folders.setdefault(parts[0], {})[parts[-1]] = zf.read(entry)
        else:
            # Flat zip — use the zip filename as the folder name.
            folders = {zip_path.stem: {Path(e).name: zf.read(e) for e in all_entries}}

        for folder_name, files in sorted(folders.items()):
            issue_file  = next((n for n in files if re.search(r"issue\.txt$",  n, re.IGNORECASE)), None)
            before_file = next((n for n in files if re.search(r"^before-",     n, re.IGNORECASE)), None)
            after_file  = next((n for n in files if re.search(r"^after-",      n, re.IGNORECASE)), None)

            if not all([issue_file, before_file, after_file]):
                print(f"  WARNING: skipping '{folder_name}' — missing required files {sorted(files.keys())}")
                continue

            tasks.append({
                "name":        folder_name,
                "task":        files[issue_file].decode("utf-8").strip(),
                "before_html": files[before_file].decode("utf-8"),
                "after_html":  files[after_file].decode("utf-8"),
            })

    return tasks


def write_example(task: dict, output_dir: Path, dry_run: bool) -> Path:
    """Write Before/, After/, and Task.txt for one task. Returns the example dir."""
    example_dir = output_dir / task["name"]
    if dry_run:
        print(f"  [dry-run] would create: {example_dir}")
        return example_dir

    (example_dir / "Before").mkdir(parents=True, exist_ok=True)
    (example_dir / "After").mkdir(parents=True, exist_ok=True)
    (example_dir / "Before" / "index.html").write_text(task["before_html"])
    (example_dir / "After"  / "index.html").write_text(task["after_html"])
    (example_dir / "Task.txt").write_text(task["task"])
    return example_dir


def main():
    parser = argparse.ArgumentParser(description="Import a case study zip for evaluation.")
    parser.add_argument("zip_path", help="Path to the zip file to import.")
    parser.add_argument("--output-dir", required=True, metavar="PATH",
                        help="Directory to write examples into (e.g. Examples/CaseStudyExamples).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would be created without writing any files.")
    parser.add_argument("--viewport", default="375x812", metavar="WxH",
                        help="Viewport size as WIDTHxHEIGHT (default: 375x812).")
    parser.add_argument("--full-page", action="store_true",
                        help="Capture the full scrollable page height.")
    args = parser.parse_args()

    try:
        vw, vh = (int(x) for x in args.viewport.lower().split("x"))
    except ValueError:
        raise SystemExit(f"Error: --viewport must be WxH format, e.g. 375x812, got: {args.viewport}")

    zip_path   = Path(args.zip_path)
    output_dir = Path(args.output_dir)

    if not zip_path.exists():
        raise SystemExit(f"Error: file not found: {zip_path}")

    print(f"Parsing {zip_path.name} ...")
    tasks = parse_zip(zip_path)
    print(f"Found {len(tasks)} task(s)\n")

    written_dirs = []
    for task in tasks:
        print(f"{task['name']}")
        example_dir = write_example(task, output_dir, dry_run=args.dry_run)
        if not args.dry_run:
            written_dirs.append(example_dir)

    if written_dirs:
        print("\nRendering screenshots ...")
        screenshot_examples(written_dirs, viewport={"width": vw, "height": vh}, full_page=args.full_page)

        print("\nGenerating diffs ...")
        for example_dir in written_dirs:
            write_diff(example_dir)

    print("\nDone.")


if __name__ == "__main__":
    main()
