"""
Renders each revision example's Before and After HTML files using a headless
Chromium browser (via Playwright) and saves screenshots alongside the HTML.

Expected directory layout (one subdirectory per example):
    RevisionExamples/
        Example1/
            Before/index.html  ->  Before/screenshot.png
            After/index.html   ->  After/screenshot.png
            Task.txt

Running:
    /Users/vivek/miniforge3/envs/GenUI/bin/python screenshot.py
"""

import os
from pathlib import Path
from playwright.sync_api import sync_playwright

EXAMPLES_DIR = Path(__file__).parent / "RevisionExamples"
SCREENSHOT_FILENAME = "screenshot.png"

# Viewport size used for all screenshots — keep consistent across examples so
# that before/after images are visually comparable at the same scale.
VIEWPORT = {"width": 1280, "height": 800}


def screenshot_html_file(page, html_path: Path) -> None:
    """Load a local HTML file into the page and save a screenshot next to it."""
    # Playwright requires a file:// URI to load local files directly.
    file_uri = html_path.resolve().as_uri()
    page.goto(file_uri)

    output_path = html_path.parent / SCREENSHOT_FILENAME
    page.screenshot(path=str(output_path))
    print(f"  Saved: {output_path.relative_to(EXAMPLES_DIR.parent)}")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT)

        # Iterate over every Example* subdirectory in sorted order.
        example_dirs = sorted(EXAMPLES_DIR.iterdir())
        for example_dir in example_dirs:
            if not example_dir.is_dir():
                continue

            print(f"\n{example_dir.name}")

            for variant in ("Before", "After"):
                html_file = example_dir / variant / "index.html"
                if html_file.exists():
                    screenshot_html_file(page, html_file)
                else:
                    print(f"  Skipping {variant}: no index.html found")

        browser.close()


if __name__ == "__main__":
    main()
