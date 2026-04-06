"""
Imports a case study zip into CaseStudyExamples/ and prepares it for evaluation.

Expected zip structure:
    task-X-MODEL/
        task-X-issue.txt        — task description
        before-task-X.html      — before code
        after-task-X-MODEL.html — after code

Where X is a task number and MODEL is the model name (e.g. gemini, gpt4).

For each task folder found in the zip, this script will:
  1. Create CaseStudyExamples/task-X-MODEL/Before/ and .../After/
  2. Write the HTML files and Task.txt
  3. Render screenshots at a mobile viewport (375x812)
  4. Generate After/diff.txt

Running:
    /Users/vivek/miniforge3/envs/GenUI/bin/python import_case_study.py path/to/study.zip

    # Dry run to preview what would be created without writing anything:
    /Users/vivek/miniforge3/envs/GenUI/bin/python import_case_study.py path/to/study.zip --dry-run
"""

import argparse
import difflib
import re
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright

CASE_STUDY_DIR = Path(__file__).parent / "CaseStudyExamples"
CODE_EXTENSIONS = {".html", ".css", ".js"}

# Mobile viewport matching the source project's rendering context.
VIEWPORT = {"width": 375, "height": 812}


# ---------------------------------------------------------------------------
# Zip parsing
# ---------------------------------------------------------------------------

def parse_zip(zip_path: Path) -> list[dict]:
    """Extract and parse task folders from the zip.

    Returns a list of dicts with keys:
        name        — folder name used as the example directory name
        task        — task description string
        before_html — HTML source string
        after_html  — HTML source string
    """
    tasks = []

    with zipfile.ZipFile(zip_path) as zf:
        all_entries = [e for e in zf.namelist() if not e.endswith("/")]

        # Support two layouts:
        #   Flat:   files sit at the zip root (task-X-issue.txt, before-task-X.html, ...)
        #   Nested: files live inside a task-X-MODEL/ subfolder
        #
        # In the flat case we derive the folder name from the zip filename itself.
        has_subfolders = any(len(Path(e).parts) > 1 for e in all_entries)

        folders: dict[str, dict[str, bytes]] = {}
        if has_subfolders:
            for entry in all_entries:
                parts = Path(entry).parts
                folder, filename = parts[0], parts[-1]
                folders.setdefault(folder, {})[filename] = zf.read(entry)
        else:
            # Flat zip — treat the zip stem (e.g. "task-1-gemini") as the folder name.
            folder_name = zip_path.stem
            folders[folder_name] = {Path(e).name: zf.read(e) for e in all_entries}

        for folder_name, files in sorted(folders.items()):
            # Locate the three required files by matching naming patterns.
            # task-X-issue.txt
            issue_file = next(
                (n for n in files if re.search(r"issue\.txt$", n, re.IGNORECASE)), None
            )
            # before-task-X.html
            before_file = next(
                (n for n in files if re.search(r"^before-", n, re.IGNORECASE)), None
            )
            # after-task-X-MODEL.html
            after_file = next(
                (n for n in files if re.search(r"^after-", n, re.IGNORECASE)), None
            )

            if not all([issue_file, before_file, after_file]):
                print(f"  WARNING: skipping '{folder_name}' — could not find all three required files")
                print(f"    found: {sorted(files.keys())}")
                continue

            tasks.append({
                "name":        folder_name,
                "task":        files[issue_file].decode("utf-8").strip(),
                "before_html": files[before_file].decode("utf-8"),
                "after_html":  files[after_file].decode("utf-8"),
            })

    return tasks


# ---------------------------------------------------------------------------
# File writing
# ---------------------------------------------------------------------------

def write_example(task: dict, dry_run: bool) -> Path:
    """Write Before/, After/, and Task.txt for one task. Returns the example dir."""
    example_dir = CASE_STUDY_DIR / task["name"]
    before_dir = example_dir / "Before"
    after_dir = example_dir / "After"

    if dry_run:
        print(f"  [dry-run] would create: {example_dir.relative_to(Path(__file__).parent)}")
        return example_dir

    before_dir.mkdir(parents=True, exist_ok=True)
    after_dir.mkdir(parents=True, exist_ok=True)

    (before_dir / "index.html").write_text(task["before_html"])
    (after_dir  / "index.html").write_text(task["after_html"])
    (example_dir / "Task.txt").write_text(task["task"])

    return example_dir


# ---------------------------------------------------------------------------
# Screenshot rendering
# ---------------------------------------------------------------------------

def render_screenshots(example_dirs: list[Path], viewport: dict, full_page: bool) -> None:
    """Render Before and After HTML files to screenshots using a headless browser.

    viewport:  dict with 'width' and 'height' keys, used for page layout.
    full_page: if True, captures the full scrollable page height rather than
               just the visible viewport area.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=viewport)

        for example_dir in example_dirs:
            for variant in ("Before", "After"):
                html_file = example_dir / variant / "index.html"
                if not html_file.exists():
                    continue

                page.goto(html_file.resolve().as_uri())
                out = html_file.parent / "screenshot.png"
                page.screenshot(path=str(out), full_page=full_page)
                print(f"  screenshot: {out.relative_to(Path(__file__).parent)}")

        browser.close()


# ---------------------------------------------------------------------------
# Diff generation
# ---------------------------------------------------------------------------

def write_diff(example_dir: Path) -> None:
    """Write After/diff.txt as a unified diff of all code files."""
    before_dir = example_dir / "Before"
    after_dir  = example_dir / "After"

    before_files = {f.name for f in before_dir.iterdir() if f.suffix in CODE_EXTENSIONS}
    after_files  = {f.name for f in after_dir.iterdir()  if f.suffix in CODE_EXTENSIONS}

    chunks = []
    for filename in sorted(before_files | after_files):
        before_path = before_dir / filename
        after_path  = after_dir  / filename

        before_lines = before_path.read_text().splitlines(keepends=True) if before_path.exists() else []
        after_lines  = after_path.read_text().splitlines(keepends=True)  if after_path.exists()  else []

        diff = difflib.unified_diff(
            before_lines, after_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
        )
        chunks.append("".join(diff))

    diff_text = "\n".join(chunks)
    if diff_text.strip():
        (after_dir / "diff.txt").write_text(diff_text)
        print(f"  diff:       {(after_dir / 'diff.txt').relative_to(Path(__file__).parent)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Import a case study zip into CaseStudyExamples/.")
    parser.add_argument("zip_path", help="Path to the zip file to import.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be created without writing any files.",
    )
    parser.add_argument(
        "--viewport",
        default="375x812",
        metavar="WxH",
        help="Viewport size as WIDTHxHEIGHT (default: 375x812).",
    )
    parser.add_argument(
        "--full-page",
        action="store_true",
        help="Capture the full scrollable page height instead of just the viewport area.",
    )
    args = parser.parse_args()

    try:
        vw, vh = (int(x) for x in args.viewport.lower().split("x"))
    except ValueError:
        raise SystemExit(f"Error: --viewport must be in WxH format, e.g. 375x812, got: {args.viewport}")

    zip_path = Path(args.zip_path)
    if not zip_path.exists():
        raise SystemExit(f"Error: file not found: {zip_path}")

    print(f"Parsing {zip_path.name} ...")
    tasks = parse_zip(zip_path)
    print(f"Found {len(tasks)} task(s)\n")

    written_dirs = []
    for task in tasks:
        print(f"{task['name']}")
        example_dir = write_example(task, dry_run=args.dry_run)
        if not args.dry_run:
            written_dirs.append(example_dir)

    if written_dirs:
        print("\nRendering screenshots ...")
        render_screenshots(written_dirs, viewport={"width": vw, "height": vh}, full_page=args.full_page)

        print("\nGenerating diffs ...")
        for example_dir in written_dirs:
            write_diff(example_dir)

    print("\nDone.")


if __name__ == "__main__":
    main()
