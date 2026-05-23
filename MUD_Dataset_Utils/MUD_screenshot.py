"""
Renders each HTML file in Datasets/MUD_GenreUI/html/ to a screenshot PNG
and saves it alongside the images in Datasets/MUD_GenreUI/screenshots/.

Resume-safe: skips IDs whose screenshot already exists.

Usage:
    python MUD_screenshot.py
"""

from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT        = Path(__file__).parent.parent  # project root (GenUI/)
DATASET_DIR = ROOT / "Datasets/MUD_GenreUI"
HTML_DIR    = DATASET_DIR / "html"
OUT_DIR     = DATASET_DIR / "screenshots"
VIEWPORT    = {"width": 390, "height": 844}  # height is initial viewport; screenshot captures full page


def render_html_files(html_files: list[Path], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT)
        for html_file in html_files:
            out = out_dir / f"{html_file.stem}.png"
            page.goto(html_file.resolve().as_uri())
            page.screenshot(path=str(out), full_page=True)
            print(f"  {html_file.stem}: saved")
        browser.close()


def main():
    html_files = sorted(HTML_DIR.glob("*.html"), key=lambda p: int(p.stem))
    done = {p.stem for p in OUT_DIR.glob("*.png")} if OUT_DIR.exists() else set()
    todo = [f for f in html_files if f.stem not in done]

    print(f"HTML files: {len(html_files)}, already done: {len(done)}, remaining: {len(todo)}")
    if not todo:
        print("All screenshots already exist.")
        return

    render_html_files(todo, OUT_DIR)
    print(f"\nDone. Screenshots saved to {OUT_DIR}/")


if __name__ == "__main__":
    main()
