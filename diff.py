"""
Generates a unified diff between the Before and After code for each revision
example and writes it to After/diff.txt.

The diff covers all code files (.html, .css, .js) found in the Before and After
directories. Files present in only one side are shown as pure additions or
deletions in the diff.

Expected directory layout:
    RevisionExamples/
        Example1/
            Before/index.html
            After/index.html   ->  After/diff.txt

Running:
    /Users/vivek/miniforge3/envs/GenUI/bin/python diff.py
"""

import difflib
from pathlib import Path

EXAMPLES_DIR = Path(__file__).parent / "RevisionExamples"
CODE_EXTENSIONS = {".html", ".css", ".js"}
DIFF_FILENAME = "diff.txt"


def diff_example(example_dir: Path) -> str:
    """Produce a unified diff string for all code files in one example."""
    before_dir = example_dir / "Before"
    after_dir = example_dir / "After"

    # Collect all code filenames that appear in either side.
    before_files = {f.name for f in before_dir.iterdir() if f.suffix in CODE_EXTENSIONS}
    after_files = {f.name for f in after_dir.iterdir() if f.suffix in CODE_EXTENSIONS}
    all_files = sorted(before_files | after_files)

    chunks = []
    for filename in all_files:
        before_path = before_dir / filename
        after_path = after_dir / filename

        before_lines = before_path.read_text().splitlines(keepends=True) if before_path.exists() else []
        after_lines = after_path.read_text().splitlines(keepends=True) if after_path.exists() else []

        # Label paths the way standard diff tools do (a/ b/ prefixes).
        diff = difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
        )
        chunks.append("".join(diff))

    return "\n".join(chunks)


def main():
    example_dirs = sorted(d for d in EXAMPLES_DIR.iterdir() if d.is_dir())

    for example_dir in example_dirs:
        diff_text = diff_example(example_dir)

        if not diff_text.strip():
            print(f"{example_dir.name}: no differences found, skipping")
            continue

        output_path = example_dir / "After" / DIFF_FILENAME
        output_path.write_text(diff_text)
        print(f"{example_dir.name}: diff written to {output_path.relative_to(EXAMPLES_DIR.parent)}")


if __name__ == "__main__":
    main()
