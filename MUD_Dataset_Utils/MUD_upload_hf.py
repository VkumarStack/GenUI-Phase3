"""
Uploads the MUD_GenreUI dataset to Hugging Face in a viewer-friendly format.

Produces:
  - data/train.parquet  — one row per screen with embedded images + all metadata
  - html/<id>.html      — raw HTML files uploaded as repo assets
  - README.md           — dataset card

Each Parquet row contains:
  id, app_type, intent, ui_pattern, confidence,
  image          (original PNG bytes),
  screenshot     (rendered HTML screenshot bytes),
  html           (HTML source as string),
  applicable_categories (list),
  tasks          (dict: category -> [task1, task2, task3])

Usage:
    huggingface-cli login          # once, to store your token
    python MUD_Dataset_Utils/MUD_upload_hf.py --repo your-hf-username/MUD_GenreUI
"""

import argparse
import io
import json
from pathlib import Path

import pandas as pd
from huggingface_hub import HfApi

ROOT        = Path(__file__).parent.parent
DATASET_DIR = ROOT / "Datasets/MUD_GenreUI"


README = """\
---
license: cc-by-4.0
task_categories:
  - image-to-text
tags:
  - mobile-ui
  - ui-design
  - revision-generation
  - html-generation
size_categories:
  - n<1K
---

# MUD_GenreUI

A 100-screen mobile UI dataset with:
- **Original screenshots** — real mobile app screens across 10 app types and 12 user intents
- **Reconstructed HTML** — each screen recreated as a self-contained HTML/CSS file (Gemini 2.5 Pro)
- **Rendered screenshots** — Playwright renders of the HTML at 390px width
- **Revision tasks** — 3 tasks per applicable taxonomy category (fine-tuned Gemini generator)

## Schema

| Column | Type | Description |
|---|---|---|
| `id` | int | Screen ID |
| `app_type` | string | App category (Social Media, E-commerce, …) |
| `intent` | string | User intent (Browse, Search, Transact, …) |
| `ui_pattern` | string | Layout pattern (List, Grid, Form, …) |
| `confidence` | float | Classification confidence (0–1) |
| `image` | bytes | Original PNG screenshot |
| `screenshot` | bytes | Rendered HTML screenshot (Playwright, 390px wide) |
| `html` | string | Reconstructed HTML source |
| `applicable_categories` | list[string] | Taxonomy categories with revision opportunities |
| `tasks` | dict | `{ category: [task1, task2, task3] }` |

## Taxonomy categories

1. Reorganize Information Hierarchy
2. Refine Layout & Spacing
3. Clarify Function & State
4. Add or Surface Functionality
5. Simplify & Reduce Clutter
6. Strengthen Visual Consistency
7. Improve Readability & Accessibility
"""


def build_parquet(dataset_dir: Path) -> bytes:
    csv = pd.read_csv(dataset_dir / "results_final_100.csv")
    revisions = json.loads((dataset_dir / "revisions.json").read_text())

    rows = []
    for _, meta in csv.iterrows():
        id_ = str(int(meta["id"]))

        image_path      = dataset_dir / "images"      / f"{id_}.png"
        screenshot_path = dataset_dir / "screenshots" / f"{id_}.png"
        html_path       = dataset_dir / "html"        / f"{id_}.html"

        image_bytes      = image_path.read_bytes()      if image_path.exists()      else None
        screenshot_bytes = screenshot_path.read_bytes() if screenshot_path.exists() else None
        html_text        = html_path.read_text(encoding="utf-8") if html_path.exists() else None

        rev = revisions.get(id_, {})
        applicable = rev.get("applicable_categories", [])
        tasks      = rev.get("tasks", {})

        rows.append({
            "id":                   int(id_),
            "app_type":             meta["app_type"],
            "intent":               meta["intent"],
            "ui_pattern":           meta["ui_pattern"],
            "confidence":           float(meta["confidence"]),
            "image":                image_bytes,
            "screenshot":           screenshot_bytes,
            "html":                 html_text,
            "applicable_categories": applicable,
            "tasks":                tasks,
        })

    df = pd.DataFrame(rows)

    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="HF repo ID, e.g. username/MUD_GenreUI")
    parser.add_argument("--private", action="store_true", help="Create as private repo")
    parser.add_argument("--token", help="HF write token (or set HF_TOKEN env var)")
    args = parser.parse_args()

    import os
    token = args.token or os.getenv("HF_TOKEN")
    api = HfApi(token=token)

    print(f"Creating/verifying repo: {args.repo}")
    api.create_repo(repo_id=args.repo, repo_type="dataset", private=args.private, exist_ok=True)

    # Build and upload Parquet
    print("Building Parquet...")
    parquet_bytes = build_parquet(DATASET_DIR)
    print(f"  {len(parquet_bytes) / 1e6:.1f} MB")
    api.upload_file(
        path_or_fileobj=parquet_bytes,
        path_in_repo="data/train.parquet",
        repo_id=args.repo,
        repo_type="dataset",
        commit_message="Add train.parquet with embedded images and revisions",
    )
    print("  uploaded data/train.parquet")

    # Upload HTML files
    html_files = sorted((DATASET_DIR / "html").glob("*.html"))
    print(f"Uploading {len(html_files)} HTML files...")
    api.upload_folder(
        folder_path=str(DATASET_DIR / "html"),
        path_in_repo="html",
        repo_id=args.repo,
        repo_type="dataset",
        commit_message=f"Add {len(html_files)} reconstructed HTML files",
    )
    print("  uploaded html/")

    # Upload dataset card
    api.upload_file(
        path_or_fileobj=README.encode(),
        path_in_repo="README.md",
        repo_id=args.repo,
        repo_type="dataset",
        commit_message="Add dataset card",
    )
    print("  uploaded README.md")

    print(f"\nDone. View at: https://huggingface.co/datasets/{args.repo}")


if __name__ == "__main__":
    main()
