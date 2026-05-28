"""
Compute a unified diff between two HTML files.

Lighter than dom_diff.py — no browser rendering, no computed styles,
just a standard line-by-line unified diff of the raw HTML source.
Used as the code-change signal for the Step 1 code analysis.

Running:
    python Util/html_diff.py --example Datasets/EvaluatorModelDataset/some_folder
    python Util/html_diff.py --before path/to/before.html --after path/to/after.html
    python Util/html_diff.py --example ... --save   # write html_diff.txt into the folder
"""

import argparse
import difflib
from pathlib import Path

_DEFAULT_CONTEXT = 3


def html_diff(before_path: Path, after_path: Path, context: int = _DEFAULT_CONTEXT) -> str:
    """Return a unified diff string comparing two HTML files."""
    before_lines = before_path.read_text(encoding="utf-8").splitlines(keepends=True)
    after_lines  = after_path.read_text(encoding="utf-8").splitlines(keepends=True)
    return "".join(difflib.unified_diff(
        before_lines, after_lines,
        fromfile="before.html", tofile="after.html",
        n=context,
    ))


def main():
    parser = argparse.ArgumentParser(description="Unified diff between two HTML files.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--example", metavar="PATH",
                       help="Example folder containing Before/index.html and After/index.html.")
    group.add_argument("--before", metavar="PATH", help="Before HTML file.")
    parser.add_argument("--after", metavar="PATH",
                        help="After HTML file (required with --before).")
    parser.add_argument("--context", type=int, default=_DEFAULT_CONTEXT,
                        help=f"Context lines around each change (default: {_DEFAULT_CONTEXT}).")
    parser.add_argument("--save", action="store_true",
                        help="Save as html_diff.txt in the example folder (only with --example).")
    args = parser.parse_args()

    if args.example:
        folder = Path(args.example)
        before = folder / "Before" / "index.html"
        after  = folder / "After"  / "index.html"
    else:
        if not args.after:
            raise SystemExit("--after is required when using --before")
        before = Path(args.before)
        after  = Path(args.after)

    result = html_diff(before, after, context=args.context)

    if args.save and args.example:
        out = folder / "html_diff.txt"
        out.write_text(result, encoding="utf-8")
        print(f"Saved to {out}")
    else:
        print(result, end="")


if __name__ == "__main__":
    main()
