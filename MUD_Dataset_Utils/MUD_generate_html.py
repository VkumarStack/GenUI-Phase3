"""
Batch HTML generation for MUD_GenreUI dataset.

Reads Datasets/MUD_GenreUI/results_final_100.csv, finds images that don't yet
have a corresponding HTML file, and generates them with Gemini 2.5 Pro.

Usage:
    export GEMINI_API_KEY=<your-key>
    python MUD_generate_html.py

Resume-safe: skips images whose HTML already exists. Re-run freely.
"""

import io
import os
import re
import sys
import time
from pathlib import Path

from PIL import Image
from google import genai
from google.genai import types
import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent.parent  # project root (GenUI/)
DATASET_DIR = ROOT / "Datasets/MUD_GenreUI"
CSV_PATH = DATASET_DIR / "results_final_100.csv"
IMAGES_DIR = DATASET_DIR / "images"
HTML_DIR = DATASET_DIR / "html"

MODEL = "gemini-2.5-pro"
VIEWPORT_W = 390
VIEWPORT_H = 844
MAX_SIDE = 1400
MAX_OUTPUT_TOKENS = 65536  # model ceiling; thinking tokens count against this
THINKING_BUDGET   = 2048   # cap thinking overhead, leaving ~63k for HTML
TEMPERATURE = 0.2
RETRIES = 3
RETRY_DELAY = 5  # seconds between retries

# ---------------------------------------------------------------------------
# Gemini helpers
# ---------------------------------------------------------------------------

def get_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        sys.exit("Error: GEMINI_API_KEY environment variable is not set.")
    return genai.Client(api_key=api_key)


def resize_for_gemini(image_path: Path, max_side: int = MAX_SIDE) -> bytes:
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    scale = min(max_side / max(w, h), 1.0)
    img = img.resize((int(w * scale), int(h * scale)))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```html\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def extract_text(response) -> str:
    if getattr(response, "text", None):
        return response.text
    parts = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            t = getattr(part, "text", None)
            if t:
                parts.append(t)
    return "\n".join(parts)


PROMPT = f"""
Recreate this mobile app screenshot as a single self-contained HTML file.

Requirements:
- Return only raw HTML.
- Include <!DOCTYPE html>, <html>, <head>, and <body>.
- Use only HTML and CSS (put all CSS inside a <style> tag).
- No external assets, no CDN, no web fonts, no JavaScript.
- Match the screenshot as closely as possible: layout, spacing, typography, \
colors, card structure, icon placement, and visual hierarchy.
- Use CSS shapes, gradients, borders, and placeholders where needed for icons/images.
- Do not invent a different design — reconstruct the screenshot you see.
- Target a mobile viewport of {VIEWPORT_W}px wide and ~{VIEWPORT_H}px tall.
- The page must have visible UI and must not be blank.

IMPORTANT — exclude phone-specific chrome:
- Do NOT recreate the Android or iOS status bar (time, battery, signal icons at the top).
- Do NOT recreate the Android gesture/navigation bar or home indicator at the bottom.
- Start the HTML content directly with the app's own header or first UI element.
"""


def generate_html(client, image_path: Path) -> str:
    image_bytes = resize_for_gemini(image_path)
    last_raw = ""

    for attempt in range(1, RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                    PROMPT,
                ],
                config=types.GenerateContentConfig(
                    temperature=TEMPERATURE,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    thinking_config=types.ThinkingConfig(thinking_budget=THINKING_BUDGET),
                ),
            )
            raw = extract_text(response) or ""
            last_raw = raw

            if not raw:
                # Empty response — likely a safety refusal; no point retrying
                print(f"  attempt {attempt}: empty response (safety filter?), skipping.")
                raise RuntimeError("Empty response from Gemini (safety filter)")

            html = strip_fences(raw)

            if html and "<html" in html.lower():
                return html

            print(f"  attempt {attempt}: response present but no <html> tag (len={len(raw)}), retrying...")

        except RuntimeError as e:
            if "safety filter" in str(e):
                raise  # don't retry safety refusals
            print(f"  attempt {attempt}: error — {e}, retrying in {RETRY_DELAY}s...")
        except Exception as e:
            print(f"  attempt {attempt}: API error — {e}, retrying in {RETRY_DELAY}s...")

        time.sleep(RETRY_DELAY * attempt)

    raise RuntimeError(
        f"Failed after {RETRIES} attempts. Last raw preview: {repr(last_raw[:300])}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ids", nargs="+", metavar="ID",
        help="Specific image IDs to (re)generate, overwriting any existing HTML.",
    )
    args = parser.parse_args()

    HTML_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(CSV_PATH)
    all_ids = [str(p.stem) for p in sorted(IMAGES_DIR.glob("*.png"), key=lambda p: int(p.stem))]

    if args.ids:
        todo = [id_ for id_ in args.ids if (IMAGES_DIR / f"{id_}.png").exists()]
        missing_imgs = [id_ for id_ in args.ids if not (IMAGES_DIR / f"{id_}.png").exists()]
        if missing_imgs:
            print(f"Warning: no source image found for: {missing_imgs}")
        print(f"Regenerating {len(todo)} specified IDs.")
    else:
        done = {p.stem for p in HTML_DIR.glob("*.html")}
        todo = [id_ for id_ in all_ids if id_ not in done]
        print(f"Total images: {len(all_ids)}, already done: {len(done)}, remaining: {len(todo)}")

    if not todo:
        print("Nothing to do.")
        return

    client = get_client()

    for i, id_ in enumerate(todo, 1):
        image_path = IMAGES_DIR / f"{id_}.png"
        html_path = HTML_DIR / f"{id_}.html"

        # Look up metadata for display
        row = df[df["id"].astype(str) == id_]
        if not row.empty:
            r = row.iloc[0]
            label = f"{r['app_type']} | {r['intent']} | {r['ui_pattern']}"
        else:
            label = "unknown"

        print(f"[{i}/{len(todo)}] {id_} ({label})")

        try:
            html = generate_html(client, image_path)
            html_path.write_text(html, encoding="utf-8")
            print(f"  saved: {html_path} ({len(html)} chars)")
        except Exception as e:
            print(f"  FAILED: {e}")

    done_after = len(list(HTML_DIR.glob("*.html")))
    print(f"\nDone. HTML files in {HTML_DIR}: {done_after}/{len(all_ids)}")


if __name__ == "__main__":
    main()
