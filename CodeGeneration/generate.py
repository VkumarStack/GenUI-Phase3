"""
Apply an LLM-generated UI change to a Before HTML file and write the result.

The model receives the Before HTML and a plain-language designer issue, then
returns a set of <<<FIND>>>...<<<REPLACE>>>...<<<END>>> edit blocks that are
applied surgically to produce the After HTML.

Running:
    # Apply a change using the default backend (anthropic) and print the result
    python CodeGeneration/generate.py --before path/to/before.html --prompt "Make the CTA button larger"

    # Write the modified HTML to a file
    python CodeGeneration/generate.py --before path/to/before.html --prompt "..." --out path/to/after.html

    # Use a specific backend / model
    python CodeGeneration/generate.py --before ... --prompt "..." --backend openai
    python CodeGeneration/generate.py --before ... --prompt "..." --backend gemini --model gemini-2.5-pro

    # Override the target viewport
    python CodeGeneration/generate.py --before ... --prompt "..." --width 390 --height 844
"""

import argparse
import sys
import warnings
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
from backends import get_backend

sys.path.insert(0, str(Path(__file__).parent))
from generate_core import generate_ui_change, is_complete_html

_DEFAULT_BACKEND = "anthropic"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply an LLM-generated UI change to a Before HTML file."
    )
    parser.add_argument(
        "--before", required=True, metavar="PATH",
        help="Path to the Before HTML file.",
    )
    parser.add_argument(
        "--prompt", required=True, metavar="TEXT",
        help="Designer issue / change description to apply.",
    )
    parser.add_argument(
        "--out", metavar="PATH", default=None,
        help="Write the resulting HTML to this path (default: print to stdout).",
    )
    parser.add_argument(
        "--backend", default=_DEFAULT_BACKEND,
        choices=["gemini", "vertexai", "anthropic", "openai"],
        help=f"Model backend (default: {_DEFAULT_BACKEND}).",
    )
    parser.add_argument(
        "--model", default=None,
        help="Override the model/endpoint (optional; uses backend default or env var).",
    )
    parser.add_argument(
        "--width", type=int, default=375, metavar="PX",
        help="Target viewport CSS width in px (default: 375).",
    )
    parser.add_argument(
        "--height", type=int, default=812, metavar="PX",
        help="Target viewport CSS height in px (default: 812).",
    )
    args = parser.parse_args()

    before_path = Path(args.before)
    if not before_path.exists():
        sys.exit(f"Error: Before HTML file not found: {before_path}")

    before_code = before_path.read_text(encoding="utf-8")

    backend = get_backend(args.backend, args.model)
    model_label = getattr(backend, "model", args.backend)
    print(
        f"Backend: {args.backend} | Model: {model_label} | "
        f"Viewport: {args.width}x{args.height}",
        file=sys.stderr,
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        after_html = generate_ui_change(
            prompt=args.prompt,
            before_code=before_code,
            backend=backend,
            css_width=args.width,
            css_height=args.height,
        )

    for w in caught:
        print(f"[warn] {w.message}", file=sys.stderr)

    if not is_complete_html(after_html):
        print("[warn] output does not look like complete HTML", file=sys.stderr)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(after_html, encoding="utf-8")
        print(f"Written to {out_path}", file=sys.stderr)
    else:
        print(after_html)


if __name__ == "__main__":
    main()
