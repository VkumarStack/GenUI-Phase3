"""
Generates a unified diff between Before/ and After/ code for revision examples
and writes it to After/diff.txt.

Usage:
    python diff.py --example path/to/Example1
    python diff.py --dir path/to/Examples/RevisionExamples
"""

import argparse
import difflib
from pathlib import Path

CODE_EXTENSIONS = {".html", ".css", ".js"}


def write_diff(example_dir: Path) -> None:
    """Compute and write After/diff.txt for one example directory."""
    before_dir = example_dir / "Before"
    after_dir  = example_dir / "After"

    before_files = {f.name for f in before_dir.iterdir() if f.suffix in CODE_EXTENSIONS}
    after_files  = {f.name for f in after_dir.iterdir()  if f.suffix in CODE_EXTENSIONS}

    chunks = []
    for filename in sorted(before_files | after_files):
        before_lines = (before_dir / filename).read_text().splitlines(keepends=True) if (before_dir / filename).exists() else []
        after_lines  = (after_dir  / filename).read_text().splitlines(keepends=True) if (after_dir  / filename).exists() else []
        chunks.append("".join(difflib.unified_diff(
            before_lines, after_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
        )))

    diff_text = "\n".join(chunks)
    if diff_text.strip():
        (after_dir / "diff.txt").write_text(diff_text)
        print(f"  {example_dir.name}: diff written")
    else:
        print(f"  {example_dir.name}: no differences found, skipping")


def main():
    parser = argparse.ArgumentParser(description="Generate diffs for revision examples.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--example", metavar="PATH", help="Path to a single example directory.")
    group.add_argument("--dir",     metavar="PATH", help="Path to a directory of examples.")
    args = parser.parse_args()

    if args.example:
        write_diff(Path(args.example))
    else:
        example_dirs = sorted(d for d in Path(args.dir).iterdir() if d.is_dir())
        for example_dir in example_dirs:
            write_diff(example_dir)


if __name__ == "__main__":
    main()
