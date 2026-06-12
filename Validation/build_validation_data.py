"""
Build Datasets/ValidationData/ from the iteration-3 user-study screens.

Source (Validation/iteration-3-screens/cge/{screen_id}/):
    {screen_id}.html                 — before (original) HTML
    {screen_id}.png                  — before screenshot
    claude_generated_output.html     — Claude Haiku 4.5 revision
    gemini_generated_output.html     — Gemini 2.5 Flash revision
    openai_generated_output.html     — GPT-4.1 mini revision
    revision_prompt.txt              — the task

Output (Datasets/ValidationData/{screen_id}/), mirroring CodeGenerationExperiment
so the same evaluation pipeline applies:
    Task.txt
    Before/index.html, Before/screenshot.png
    claude-haiku-4-5/index.html, claude-haiku-4-5/screenshot.png
    gemini-2.5-flash/index.html, gemini-2.5-flash/screenshot.png
    gpt-4.1-mini/index.html,     gpt-4.1-mini/screenshot.png

All screenshots are rendered fresh from HTML at 375x812 (the experiment viewport)
so before/after renders are produced by the same engine.

Usage:
    python Validation/build_validation_data.py
    python Validation/build_validation_data.py --force
"""

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

_ROOT   = Path(__file__).parent.parent
_SOURCE = Path(__file__).parent / "iteration-3-screens" / "cge"
_OUT    = _ROOT / "Datasets" / "ValidationData"
_VIEWPORT = {"width": 375, "height": 812}

# source generated-output filename -> destination model folder
_OUTPUTS = {
    "claude_generated_output.html": "claude-haiku-4-5",
    "gemini_generated_output.html": "gemini-2.5-flash",
    "openai_generated_output.html": "gpt-4.1-mini",
}


def _render(html_path: Path, out_path: Path, page) -> None:
    page.goto(html_path.resolve().as_uri())
    page.screenshot(path=str(out_path))


def _build_screen(screen_dir: Path, page, force: bool) -> str:
    sid = screen_dir.name
    before_html = screen_dir / f"{sid}.html"
    prompt_file = screen_dir / "revision_prompt.txt"
    if not before_html.exists() or not prompt_file.exists():
        return "skip-missing"

    dest = _OUT / sid
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "Task.txt").write_text(prompt_file.read_text(encoding="utf-8").strip(), encoding="utf-8")

    # Before
    bdir = dest / "Before"
    bdir.mkdir(exist_ok=True)
    (bdir / "index.html").write_text(before_html.read_text(encoding="utf-8"), encoding="utf-8")
    if force or not (bdir / "screenshot.png").exists():
        _render(bdir / "index.html", bdir / "screenshot.png", page)

    # Model outputs
    for src_name, model_key in _OUTPUTS.items():
        src = screen_dir / src_name
        if not src.exists():
            print(f"    {sid}: missing {src_name}")
            continue
        mdir = dest / model_key
        mdir.mkdir(exist_ok=True)
        (mdir / "index.html").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        if force or not (mdir / "screenshot.png").exists():
            _render(mdir / "index.html", mdir / "screenshot.png", page)

    return "ok"


def main():
    parser = argparse.ArgumentParser(description="Build Datasets/ValidationData from iteration-3 screens.")
    parser.add_argument("--force", action="store_true", help="Re-render existing screenshots.")
    parser.add_argument("--screens", nargs="+", metavar="ID",
                        help="Only build these screen IDs (default: all).")
    args = parser.parse_args()

    if not _SOURCE.exists():
        raise SystemExit(f"Source not found: {_SOURCE}")

    screen_dirs = sorted((d for d in _SOURCE.iterdir() if d.is_dir()),
                         key=lambda p: int(p.name) if p.name.isdigit() else p.name)
    if args.screens:
        wanted = set(args.screens)
        screen_dirs = [d for d in screen_dirs if d.name in wanted]

    _OUT.mkdir(parents=True, exist_ok=True)
    print(f"Source:  {_SOURCE.relative_to(_ROOT)}")
    print(f"Output:  {_OUT.relative_to(_ROOT)}")
    print(f"Screens: {len(screen_dirs)}")
    print()

    ok = skipped = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport=_VIEWPORT)
        for i, sd in enumerate(screen_dirs, 1):
            status = _build_screen(sd, page, args.force)
            if status == "ok":
                ok += 1
            else:
                skipped += 1
            print(f"  [{i:>3}/{len(screen_dirs)}] {sd.name}: {status}")
        browser.close()

    print(f"\nDone.  Built: {ok}  Skipped: {skipped}")
    print(f"Dataset: {_OUT.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
