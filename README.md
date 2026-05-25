# GenUI — Automated UI Revision Generation & Evaluation

This project supports two automated pipelines for UI revision research:

1. **Revision Generation** — given a Before screenshot, generates plausible revision tasks using a VLM, conditioned on a 7-category revision taxonomy.
2. **Evaluation** — given a Before/After UI pair and a revision task, determines whether the task was correctly implemented using a two-step pipeline that outputs a 5-criterion rubric verdict (each PASS / PARTIAL PASS / FAIL) plus a binary OVERALL (PASS / FAIL).

---

## Setup

```bash
conda create -n GenUI python=3.11
conda activate GenUI
pip install -r requirements.txt
playwright install chromium
```

Create `Util/.env` with the relevant API key(s):

```
GOOGLE_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here

# Vertex AI (for fine-tuned models)
VERTEXAI_PROJECT=your_project
VERTEXAI_LOCATION=us-central1
VERTEXAI_EVALUATOR_ENDPOINT_ID=your_evaluator_endpoint
VERTEXAI_GENERATOR_ENDPOINT_ID=your_generator_endpoint
```

---

## Directory Structure

```
Datasets/
    RawDataset/                     # source UI revision examples (revision generator)
    EvaluatorModelDataset/          # 141 expert-labeled examples (evaluator)
        Train/                      # symlinks → training examples (98 folders)
        Test/                       # symlinks → test examples (43 folders)
        split_manifest.json         # split config, group lists, difficult-case counts
    RevisionGeneratorModelDataset/
        Train/                      # revision generator training examples
        Test/                       # revision generator test examples (17 examples)

RevisionGeneration/
    generate.py                     # generate revision tasks from Before screenshots
    generate_core.py                # core generation logic (prompt, parser)

Taxonomy/
    RevisionTaxonomy/
        label.py                    # Phase 1: VLM-label each revision example
        consolidate.py              # Phase 2: merge labels into final taxonomy
        assign.py                   # assign new examples to existing categories
        Results/
            taxonomy.json           # 7 revision categories (name + description)
            taxonomy.md
    EvaluationTaxonomy/
        collect.py                  # parse Output.txt files into raw_data.json
        label.py                    # Phase 1: VLM-label pass/fail reasons
        consolidate.py              # Phase 2: merge into pass/fail taxonomies
        Results/
            pass_taxonomy.json
            fail_taxonomy.json
            taxonomy.md

Evaluator/
    step1.py                        # generate UI component context (single example / testing)
    step1_prompt.txt                # prompt — visual attention guide, not expected-change spec
    step2.py                        # 5-criterion rubric verdict from context + screenshots + DOM diff
    step2_prompt.txt                # editable prompt template for Step 2

DatasetBuilder/
    EvaluatorModel/
        cache_dom_diffs.py          # compute and cache dom_diff.txt for RawDataset
        fill_step1.py               # fill/regenerate Step 1 specs (--force to overwrite all)
        split.py                    # stratified train/test split
        sync_dom_diffs.py           # copy updated dom_diffs into Train/Test splits
        split_summary.json
    RevisionGeneratorModel/
        split.py                    # multi-label stratified train/test split
        check_missing.py            # find and fill missing Taxonomy.txt
        split_summary.json

FineTuning/
    count_tokens.py                 # estimate token cost for a training JSONL
    upload_assets.py                # upload Before/After screenshots to GCS (any dataset)
    manifest.json                   # GCS URIs for all uploaded screenshots
    Evaluator/
        build_dataset.py            # build train.jsonl for evaluator model
        inspect_dataset.py          # preview sampled training examples as markdown
    RevisionGenerator/
        build_dataset.py            # build train.jsonl for revision generator model
        inspect_dataset.py          # preview sampled training examples as markdown

Testing/
    Evaluator/
        run.py                      # evaluate a model (--no-dom-diff, --no-step1, --rerun-failed)
        inspect_results.py          # format results JSON as markdown (wrong-first, with DOM diff + Step 1)
        run_ablations.sh            # run all 4 ablation conditions sequentially
        Results/                    # per-run JSON with metrics + predictions
    RevisionGenerator/
        run.py                      # generate tasks for all unique test screens
        compare.py                  # pairwise A/B comparison using Claude as judge
        add_avg_scores.py           # backfill avg_scores into existing result files
        Results/                    # per-run JSONs + comparison JSONs

Util/
    backends.py                     # LLM backends: Gemini, VertexAI, Anthropic, OpenAI
    dom_diff.py                     # three-section DOM + CSS diff (Playwright-based)
    screenshot.py                   # render HTML to screenshot.png
    diff.py                         # generate unified code diffs
    import_case_study.py            # import a Phase 2 zip into CaseStudyExamples/
    .env                            # API keys (not committed)

MUD_Dataset_Utils/
    MUD_generate_html.py        # reconstruct each MUD screen as HTML (Gemini 2.5 Pro)
    MUD_screenshot.py           # render HTML files to screenshots (Playwright, 390px, full-page)
    MUD_inspect.py              # inspect rendered screenshots → review_mud.md
    MUD_generate_revisions.py   # taxonomy filter + revision task generation for MUD screens
    MUD_inspect_revisions.py    # inspect revisions paired with screenshots → review_mud_revisions.md
    MUD_upload_hf.py            # upload MUD_GenreUI dataset to HuggingFace as Parquet

Datasets/
    MUD_GenreUI/                # 100-screen mobile UI dataset
        images/                 # original app screenshots
        html/                   # reconstructed HTML/CSS files
        screenshots/            # Playwright renders of the HTML
        metadata/               # per-screen JSON from the source dataset
        results_final_100.csv   # id, app_type, intent, ui_pattern, confidence
        revisions.json          # generated revision tasks per screen

DEPRECATED/                         # old evaluation approach, kept for reference
```

Each RawDataset example follows this layout:

```
Participant_X_CaseStudy-Y.Z-MODEL/
    Task.txt
    Before/
        index.html
        screenshot.png
    After/
        index.html
        screenshot.png
    dom_diff.txt
    step1_spec.txt
    Output.txt                      # expert evaluation notes
    Taxonomy.txt                    # revision category assignment(s)
```

---

## Supported Backends

| Backend | Default Model | Notes |
|---|---|---|
| `gemini` | `gemini-2.5-pro` | Requires `GOOGLE_API_KEY` |
| `vertexai` | _(endpoint required)_ | Requires `VERTEXAI_PROJECT` + `VERTEXAI_LOCATION`; separate endpoints for evaluator vs. generator |
| `anthropic` | `claude-sonnet-4-6` | Requires `ANTHROPIC_API_KEY` |
| `openai` | `gpt-4o` | Requires `OPENAI_API_KEY` |

Scripts that accept `--backend` pass `endpoint_env_var` so the correct endpoint is selected automatically:
- Evaluator scripts use `VERTEXAI_EVALUATOR_ENDPOINT_ID`
- RevisionGenerator scripts use `VERTEXAI_GENERATOR_ENDPOINT_ID`

---

## Util Scripts

### `screenshot.py`

Renders HTML files to `screenshot.png` for one example or an entire directory.

```bash
python Util/screenshot.py --example Datasets/RawDataset/Participant_2_CaseStudy-1.1-CLAUDE
python Util/screenshot.py --dir Datasets/RawDataset --viewport 375x812
python Util/screenshot.py --dir Datasets/RawDataset --viewport 375x812 --full-page
```

### `diff.py`

Generates `After/diff.txt` (unified code diff between Before/ and After/ HTML) for one example or a directory.

```bash
python Util/diff.py --example Datasets/RawDataset/Participant_2_CaseStudy-1.1-CLAUDE
python Util/diff.py --dir Datasets/RawDataset
```

### `import_case_study.py`

Imports a zip exported from Phase 2 into an output directory. Renders screenshots and generates diffs automatically.

```bash
python Util/import_case_study.py path/to/study.zip --output-dir Datasets/RawDataset
python Util/import_case_study.py path/to/study.zip --output-dir Datasets/RawDataset --viewport 375x812 --full-page
```

### `dom_diff.py`

Computes a three-section semantic diff between Before/After HTML files:

1. **CSS Rule Changes** — declarations that changed inside `<style>` blocks (declared intent)
2. **Computed Style Changes** — final browser-resolved values via Playwright (authoritative signal for subtle changes)
3. **DOM Structure Changes** — additions, removals, attribute changes as a unified diff

---

## MUD Dataset Pipeline

Generates a revision task dataset from 100 curated mobile UI screens using the fine-tuned revision generator. All scripts live in `MUD_Dataset_Utils/` and resolve paths relative to the project root, so they can be run from anywhere.

### 1. Generate HTML reconstructions

```bash
# Generate HTML for all screens missing one
python MUD_Dataset_Utils/MUD_generate_html.py

# Regenerate specific screens (overwrites existing)
python MUD_Dataset_Utils/MUD_generate_html.py --ids 5149 6236 7122
```

### 2. Render screenshots

```bash
python MUD_Dataset_Utils/MUD_screenshot.py
```

Renders each HTML at 390px wide, full-page height. Resume-safe.

### 3. Inspect rendered HTML

```bash
python MUD_Dataset_Utils/MUD_inspect.py [--output review_mud.md]
```

### 4. Generate revision tasks

```bash
# Use fine-tuned VertexAI generator (default) + Gemini 2.5 Pro filter
python MUD_Dataset_Utils/MUD_generate_revisions.py

# Preview a single screen before running the full batch
python MUD_Dataset_Utils/MUD_generate_revisions.py --id 7122

# Use base Gemini for both steps (no VertexAI needed)
python MUD_Dataset_Utils/MUD_generate_revisions.py --backend gemini
```

Step 1 (filter): base Gemini 2.5 Pro identifies which of the 7 taxonomy categories have meaningful revision opportunities for the screen.  
Step 2 (generate): the fine-tuned VertexAI generator produces 3 tasks per applicable category.  
Output: `Datasets/MUD_GenreUI/revisions.json`. Resume-safe.

### 5. Inspect revisions

```bash
python MUD_Dataset_Utils/MUD_inspect_revisions.py [--output review_mud_revisions.md]
```

### 6. Upload to HuggingFace

```bash
python MUD_Dataset_Utils/MUD_upload_hf.py --repo username/MUD_GenreUI [--private] [--token hf_xxx]
# or: export HF_TOKEN=hf_xxx
```

Packages the dataset as `data/train.parquet` (one row per screen: embedded image + screenshot bytes, HTML source, revision tasks) plus raw HTML files. Requires `pip install pyarrow`.

---

## Revision Generation

Generates one task per taxonomy category by default (7 tasks per screenshot). Use `--category` to target a single category and `--count` to generate multiple tasks per category.

```bash
# Generate one task per category for one example
python RevisionGeneration/generate.py --example Datasets/RawDataset/Participant_2_CaseStudy-1.1-CLAUDE

# Generate for every example in a directory
python RevisionGeneration/generate.py --dir Datasets/RawDataset

# Target a specific category
python RevisionGeneration/generate.py --example ... --category "Clarify Function & State"

# Generate multiple tasks per category
python RevisionGeneration/generate.py --example ... --count 3

# Use a fine-tuned model on Vertex AI
python RevisionGeneration/generate.py --example ... --backend vertexai

# Save each generated task under DummyData/GeneratedRevisions/
python RevisionGeneration/generate.py --dir ... --save
```

---

## Evaluation Pipeline

### Step 1 — UI Component Context (visual attention guide)

Step 1 identifies which UI components the evaluator should look at — their location, appearance, and visual relationships. It is **not** an expected-change spec and must not prescribe implementation details.

Fill/regenerate specs for all EvaluatorModelDataset examples:

```bash
python DatasetBuilder/EvaluatorModel/fill_step1.py          # fill missing only
python DatasetBuilder/EvaluatorModel/fill_step1.py --force  # regenerate all
```

Test a single example:

```bash
python Evaluator/step1.py --example Datasets/EvaluatorModelDataset/Participant_2_CaseStudy-1.1-CLAUDE
```

### Step 2 — Rubric verdict

Outputs 5-criterion rubric (PASS / PARTIAL PASS / FAIL each) + binary OVERALL (PASS / FAIL) + COMMENT.

```bash
# Run over EvaluatorModelDataset (default)
python Evaluator/step2.py

# Single example
python Evaluator/step2.py --example Datasets/EvaluatorModelDataset/Participant_2_CaseStudy-1.1-CLAUDE

# Ablation flags
python Evaluator/step2.py --no-dom-diff
python Evaluator/step2.py --no-step1

# Resume interrupted run
python Evaluator/step2.py --resume

# Use a fine-tuned evaluator on Vertex AI
python Evaluator/step2.py --backend vertexai
```

Output: `Evaluator/step2_results.json`

---

## Dataset Building

### Compute DOM diffs

```bash
# Compute dom_diff.txt for all EvaluatorModelDataset examples (skip existing)
python DatasetBuilder/EvaluatorModel/cache_dom_diffs.py

# Force recompute all
python DatasetBuilder/EvaluatorModel/cache_dom_diffs.py --force
```

### Create train/test split

```bash
# Preview without writing (dry run)
python DatasetBuilder/EvaluatorModel/split.py --dry-run

# Apply (creates Train/ + Test/ symlinks and split_manifest.json)
python DatasetBuilder/EvaluatorModel/split.py
# Key flags: --test-frac 0.30, --difficult-train-frac 0.50, --difficult-test-frac 0.25
```

### Build fine-tuning datasets

```bash
# Evaluator model (reads from Train/ symlinks + RubricEvaluation.json)
python FineTuning/Evaluator/build_dataset.py

# Revision generator model
python FineTuning/RevisionGenerator/build_dataset.py
```

### Inspect training examples

```bash
python FineTuning/Evaluator/inspect_dataset.py --n 10 > review.md
```

### Estimate training cost

```bash
# Note: use --raw-dataset to point at the correct dataset for image resolution
python FineTuning/count_tokens.py \
    --dataset FineTuning/Evaluator/train.jsonl \
    --raw-dataset Datasets/EvaluatorModelDataset
python FineTuning/count_tokens.py --dataset FineTuning/RevisionGenerator/train.jsonl --epochs 5
```

### Upload screenshots to GCS

```bash
# Works with any dataset directory containing Before/After screenshot subfolders
python FineTuning/upload_assets.py --bucket my-bucket --dataset Datasets/EvaluatorModelDataset
python FineTuning/upload_assets.py --bucket my-bucket --dataset Datasets/RawDataset
python FineTuning/upload_assets.py --bucket my-bucket --force  # re-upload all
```

---

## Model Testing

### Evaluator model

```bash
# Run Gemini baseline against the test set
python Testing/Evaluator/run.py --backend gemini

# Run fine-tuned evaluator
python Testing/Evaluator/run.py --backend vertexai --run-name finetuned-v1

# Resume an interrupted run
python Testing/Evaluator/run.py --backend gemini --resume

# Ablation variants (omit DOM diff or Step 1 spec from the prompt)
python Testing/Evaluator/run.py --no-dom-diff
python Testing/Evaluator/run.py --no-step1

# Run all 4 ablation conditions sequentially
bash Testing/Evaluator/run_ablations.sh

# Rerun only previously wrong examples (saves to <stem>-rerun.json)
python Testing/Evaluator/run.py --rerun-failed Testing/Evaluator/Results/gemini-2.5-pro.json

# Inspect results — wrong predictions first, with DOM diff + Step 1 in collapsible sections
python Testing/Evaluator/inspect_results.py Testing/Evaluator/Results/finetuned-v1.json > review.md
```

Output: `Testing/Evaluator/Results/<run-name>.json` with accuracy, macro F1, per-class P/R/F1, and confusion matrix.

### Revision generator model

```bash
# Generate 3 tasks per category for all unique test screens (11 screens × 7 categories)
python Testing/RevisionGenerator/run.py --backend gemini --run-name gemini
python Testing/RevisionGenerator/run.py --backend vertexai --run-name finetuned-v1

# Resume an interrupted run
python Testing/RevisionGenerator/run.py --backend gemini --run-name gemini --resume
```

Output: `Testing/RevisionGenerator/Results/<run-name>.json`

### Pairwise comparison

Uses Claude as judge to avoid same-model bias. By default, all 7 categories for a screen are judged in one API call (11 calls total).

```bash
# Compare two runs (default: batch all categories per screen)
python Testing/RevisionGenerator/compare.py \
    Testing/RevisionGenerator/Results/gemini.json \
    Testing/RevisionGenerator/Results/finetuned-v1.json

# Chunk into groups of 3 categories per call
python Testing/RevisionGenerator/compare.py \
    Testing/RevisionGenerator/Results/gemini.json \
    Testing/RevisionGenerator/Results/finetuned-v1.json \
    --batch-size 3

# Resume interrupted comparison
python Testing/RevisionGenerator/compare.py ... --resume

# Backfill avg_scores into an existing comparison file
python Testing/RevisionGenerator/add_avg_scores.py \
    Testing/RevisionGenerator/Results/gemini_vs_finetuned-v1.json
```

Output: `Testing/RevisionGenerator/Results/<run_a>_vs_<run_b>.json` with:
- `summary.totals` — win/tie/loss counts per run
- `summary.avg_scores` — average scores per dimension (Relevance, Specificity, Actionability, Diversity, overall) per run
- `summary.per_category` — win counts broken down by taxonomy category
- `comparisons` — per-(screen, category) raw judge responses
