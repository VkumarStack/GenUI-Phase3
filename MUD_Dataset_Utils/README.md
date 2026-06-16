# MUD_Dataset_Utils/

The pipeline that builds the **MUD_GenreUI** dataset: real mobile screenshots →
reconstructed HTML → rendered screenshots → generated revision tasks → published
to Hugging Face. Everything lives under `Datasets/MUD_GenreUI/`:

```
images/        original MUD app screenshots  ({id}.png)      ← pipeline input
html/          reconstructed HTML            ({id}.html)
screenshots/   Playwright renders of the HTML ({id}.png)
metadata/      per-screen source metadata
results_final_100.csv   id, app_type, intent, ui_pattern, …
revisions.json          generated revision tasks per screen
```

| Script | Step |
|---|---|
| `MUD_generate_html.py` | image → self-contained HTML (Gemini 2.5 Pro). |
| `MUD_screenshot.py` | HTML → screenshot (Playwright, 390px wide, full-page). |
| `MUD_generate_revisions.py` | screenshot → applicable categories + revision tasks. |
| `MUD_upload_hf.py` | package everything → Hugging Face parquet + raw HTML. |

All read `GOOGLE_API_KEY` from `Util/.env`. All three generation scripts are
**resume-safe** (skip ids that already have their output).

---

## Running the pipeline

```bash
# 1. Reconstruct HTML for any image lacking it (or --ids to force specific ones)
python MUD_Dataset_Utils/MUD_generate_html.py
python MUD_Dataset_Utils/MUD_generate_html.py --ids 5149 6236

# 2. Render the HTML to screenshots
python MUD_Dataset_Utils/MUD_screenshot.py

# 3. Generate revision tasks (taxonomy filter + per-category generation)
python MUD_Dataset_Utils/MUD_generate_revisions.py                 # default backend = fine-tuned vertexai
python MUD_Dataset_Utils/MUD_generate_revisions.py --backend gemini
python MUD_Dataset_Utils/MUD_generate_revisions.py --id 7122       # single screen
python MUD_Dataset_Utils/MUD_generate_revisions.py --tasks-per-category 5

# 4. Publish to Hugging Face
python MUD_Dataset_Utils/MUD_upload_hf.py --repo username/MUD_GenreUI
```

`MUD_generate_revisions.py` runs two steps per screen: a base-Gemini filter that
picks the applicable taxonomy categories, then the generator (the fine-tuned
Vertex AI model by default — note its endpoint is tied to the original GCP account;
use `--backend gemini` otherwise). `--tasks-per-category` (default 3) controls how
many tasks are produced per category.

---

## Adding more screens

The pipeline is incremental: to grow the dataset, **drop new `{id}.png` files into
`Datasets/MUD_GenreUI/images/` and re-run the three generation scripts** (1→2→3).
Each only processes ids it hasn't done, so existing entries are untouched and the
new screens are appended (`revisions.json` gains entries; `html/` and
`screenshots/` gain files).

Notes:
- `results_final_100.csv` is **not required** for generation — an image with no CSV
  row still gets HTML/screenshot/revisions (it just shows an `unknown` label). But
  `MUD_upload_hf.py` iterates the CSV, so to **publish** added screens their
  metadata rows must be added to the CSV first.
- ⚠️ **Review the reconstructed HTML.** `MUD_generate_html.py` rebuilds each page
  from the screenshot with an LLM; reconstructions can be imperfect or broken
  (missing sections, mangled layout, placeholder icons). Open the new `html/` files
  (or their rendered `screenshots/`) in a browser and sanity-check them before
  using them as revision starting points — a broken before-state propagates into
  every downstream task and evaluation.
- To generate a **larger** dataset from the same screens, raise
  `--tasks-per-category` above 3.
