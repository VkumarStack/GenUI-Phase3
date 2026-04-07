"""
Renders Before/ and After/ HTML files for revision examples using a headless
Chromium browser and saves screenshot.png alongside each HTML file.

Usage:
    python screenshot.py --example path/to/Example1
    python screenshot.py --dir path/to/Examples/RevisionExamples
    python screenshot.py --dir path/to/Examples/RevisionExamples --viewport 1280x800
    python screenshot.py --dir path/to/Examples/RevisionExamples --full-page
"""

import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

DEFAULT_VIEWPORT = {"width": 375, "height": 812}


def screenshot_examples(example_dirs: list[Path], viewport: dict, full_page: bool) -> None:
    """Render Before and After HTML files to screenshots for each example.

    Opens one browser session for efficiency across multiple examples.
    full_page: if True, captures the full scrollable height instead of just the viewport.
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
                print(f"  {example_dir.name}/{variant}: screenshot saved")

        browser.close()


def main():
    parser = argparse.ArgumentParser(description="Screenshot revision examples.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--example", metavar="PATH", help="Path to a single example directory.")
    group.add_argument("--dir",     metavar="PATH", help="Path to a directory of examples.")
    parser.add_argument(
        "--viewport", default="375x812", metavar="WxH",
        help="Viewport size as WIDTHxHEIGHT (default: 375x812).",
    )
    parser.add_argument(
        "--full-page", action="store_true",
        help="Capture the full scrollable page height instead of just the viewport area.",
    )
    args = parser.parse_args()

    try:
        vw, vh = (int(x) for x in args.viewport.lower().split("x"))
    except ValueError:
        raise SystemExit(f"Error: --viewport must be WxH format, e.g. 375x812, got: {args.viewport}")

    viewport = {"width": vw, "height": vh}

    if args.example:
        example_dirs = [Path(args.example)]
    else:
        example_dirs = sorted(d for d in Path(args.dir).iterdir() if d.is_dir())

    screenshot_examples(example_dirs, viewport=viewport, full_page=args.full_page)


if __name__ == "__main__":
    main()
