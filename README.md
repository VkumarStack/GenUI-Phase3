# GenUI — Automated UI Revision Generation & Evaluation

This project supports two automated pipelines for UI revision research:

1. **Revision Generation** — given a Before screenshot, generates plausible revision tasks using a fine-tuned VLM conditioned on a 7-category revision taxonomy.
2. **Evaluation** — given a Before/After UI pair and a revision task, determines whether the task was correctly implemented using a two-step pipeline (code analysis → visual rubric verdict).

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

# Vertex AI (for fine-tuned revision generator)
VERTEXAI_PROJECT=your_project
VERTEXAI_LOCATION=us-central1
VERTEXAI_GENERATOR_ENDPOINT_ID=your_generator_endpoint
```

---

## Directory Structure

```
Datasets/
    MUD_GenreUI/                    # 100-screen mobile UI benchmark
        images/                     # original app screenshots
        html/                       # reconstructed HTML/CSS files
        screenshots/                # Playwright renders of the HTML
        metadata/                   # per-screen JSON from source dataset
        results_final_100.csv       # id, app_type, intent, ui_pattern, confidence
        revisions.json              # generated revision tasks per screen

    EvaluatorModelDataset/          # 119 expert-labeled examples (flat, no splits)
        Participant_X_CaseStudy-Y.Z-MODEL/
            Task.txt
            Before/index.html + screenshot.png
            After/index.html + screenshot.png
            html_diff.txt           # cached unified HTML diff (Before → After)
            step1_spec.txt          # cached Stage 1 code analysis
            RubricEvaluation.json   # 5-criterion rubric + overall PASS/FAIL

    RevisionGeneratorModelDataset/
        All/                        # all training examples (Example-NNN/ folders)
            Example-NNN/
                screenshot.png      # Before screenshot
                task.txt            # revision task text
                prompt.txt          # "Category: X\nDescription: Y"
                meta.json           # example_key, label, gcs_uri

    CodeGenerationExperiment/       # 100 screens × 3 models (code generation test)
        <screen_id>/
            Task.txt
            category.txt
            Before/index.html + screenshot.png
            claude-haiku-4-5/index.html + screenshot.png
            gemini-2.5-flash/index.html + screenshot.png
            gpt-4.1-mini/index.html + screenshot.png

    CodeGenEvalSample/              # sampled subset for auto-evaluation
        <screen_id>_<model>/
            Task.txt
            Before/ + After/
            html_diff.txt
            step1_spec.txt
            eval_result.json

CodeGeneration/
    build_dataset.py                # build CodeGenerationExperiment from MUD screens
    build_eval_sample.py            # sample 1 model/screen and run full evaluator pipeline
    generate.py                     # search-replace code generation (single example)
    generate_core.py                # core generation logic

RevisionGeneration/
    generate.py                     # generate revision tasks from Before screenshots
    generate_core.py                # core generation logic (prompt, parser)

Taxonomy/
    RevisionTaxonomy/
        label.py                    # Phase 1: VLM-label each unique revision example
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
    step1.py                        # Stage 1: code analysis (single example / testing)
    step1_prompt.txt                # prompt: task + before HTML + html_diff → code report
    step2.py                        # Stage 2: visual rubric verdict
    step2_prompt.txt                # editable prompt template for Stage 2

DatasetBuilder/
    EvaluatorModel/
        cache_html_diffs.py         # compute and cache html_diff.txt for EvaluatorModelDataset
        fill_step1.py               # fill/regenerate Stage 1 specs (--force to overwrite all)
    RevisionGeneratorModel/
        build_from_jsonl.py         # build RevisionGeneratorModelDataset from train.jsonl + GCS
        check_missing.py            # find examples with no taxonomy assignment

FineTuning/
    count_tokens.py                 # estimate token cost for a training JSONL
    upload_assets.py                # upload Before/After screenshots to GCS
    manifest.json                   # GCS URIs for all uploaded screenshots
    RevisionGenerator/
        build_dataset.py            # build train.jsonl for revision generator SFT
        inspect_dataset.py          # preview sampled training examples as markdown
        train.jsonl                 # SFT training data (152 examples)

Testing/
    Evaluator/
        run.py                      # evaluate the pipeline; --rerun-failed supported
        inspect_results.py          # format results JSON as markdown (wrong-first)
        Results/                    # per-run JSON with metrics + per-example predictions

Util/
    backends.py                     # LLM backends: Gemini, VertexAI, Anthropic, OpenAI
    html_diff.py                    # unified HTML diff utility (difflib-based)
    screenshot.py                   # render HTML to screenshot.png via Playwright
    .env                            # API keys (not committed)

MUD_Dataset_Utils/
    MUD_generate_html.py            # reconstruct each MUD screen as HTML (Gemini 2.5 Pro)
    MUD_screenshot.py               # render HTML files to screenshots (Playwright)
    MUD_inspect.py                  # inspect rendered screenshots → review_mud.md
    MUD_generate_revisions.py       # taxonomy filter + revision task generation
    MUD_inspect_revisions.py        # inspect revisions + screenshots → review_mud_revisions.md
    MUD_upload_hf.py                # upload MUD_GenreUI dataset to HuggingFace

Paper/
    main.tex                        # ACM-format capstone paper
    main.pdf                        # compiled output

Deprecated/                         # old approaches kept for reference
```

---

## Supported Backends

| Backend | Default Model | Notes |
|---|---|---|
| `gemini` | `gemini-2.5-pro` | Requires `GOOGLE_API_KEY` |
| `vertexai` | _(endpoint required)_ | Requires `VERTEXAI_PROJECT` + `VERTEXAI_LOCATION` |
| `anthropic` | `claude-sonnet-4-6` | Requires `ANTHROPIC_API_KEY` |
| `openai` | `gpt-4o` | Requires `OPENAI_API_KEY` |

---

## Util Scripts

### `screenshot.py`

Renders an HTML file to `screenshot.png` via headless Playwright.

```bash
python Util/screenshot.py --example Datasets/EvaluatorModelDataset/Participant_2_CaseStudy-1.1-CLAUDE
python Util/screenshot.py --dir Datasets/EvaluatorModelDataset --viewport 375x812
```

### `html_diff.py`

Computes a standard unified diff between Before/After HTML source files. Used by Stage 1 of the evaluator.

```python
from html_diff import html_diff
diff_text = html_diff(Path("Before/index.html"), Path("After/index.html"))
```

---

## MUD Dataset Pipeline

Generates a revision task dataset from 100 curated mobile UI screens using the fine-tuned revision generator. All scripts live in `MUD_Dataset_Utils/`.

### 1. Generate HTML reconstructions

```bash
python MUD_Dataset_Utils/MUD_generate_html.py           # generate all missing
python MUD_Dataset_Utils/MUD_generate_html.py --ids 5149 6236  # specific screens
```

### 2. Render screenshots

```bash
python MUD_Dataset_Utils/MUD_screenshot.py              # 390px wide, full-page
```

### 3. Inspect rendered HTML

```bash
python MUD_Dataset_Utils/MUD_inspect.py [--output review_mud.md]
```

### 4. Generate revision tasks

```bash
python MUD_Dataset_Utils/MUD_generate_revisions.py             # default: fine-tuned VertexAI
python MUD_Dataset_Utils/MUD_generate_revisions.py --id 7122   # single screen preview
python MUD_Dataset_Utils/MUD_generate_revisions.py --backend gemini  # base Gemini
```

Step 1 (filter): Gemini 2.5 Pro identifies which of the 7 taxonomy categories apply to the screen.
Step 2 (generate): the fine-tuned VertexAI generator produces 3 tasks per applicable category.
Output: `Datasets/MUD_GenreUI/revisions.json`. Resume-safe.

### 5. Inspect revisions

```bash
python MUD_Dataset_Utils/MUD_inspect_revisions.py [--output review_mud_revisions.md]
```

### 6. Upload to HuggingFace

```bash
python MUD_Dataset_Utils/MUD_upload_hf.py --repo username/MUD_GenreUI [--token hf_xxx]
```

---

## Revision Generation

Generates revision tasks from a Before screenshot conditioned on a taxonomy category.

```bash
# Generate one task per category for one example
python RevisionGeneration/generate.py --example Datasets/EvaluatorModelDataset/Participant_2_CaseStudy-1.1-CLAUDE

# Generate for every example in a directory
python RevisionGeneration/generate.py --dir Datasets/EvaluatorModelDataset

# Target a specific category
python RevisionGeneration/generate.py --example ... --category "Clarify Function & State"

# Generate multiple tasks per category
python RevisionGeneration/generate.py --example ... --count 3

# Use the fine-tuned model on Vertex AI
python RevisionGeneration/generate.py --example ... --backend vertexai
```

---

## Evaluation Pipeline

The evaluator uses a two-stage pipeline. The default model for both stages is `gemini-3.1-pro-preview`.

### Stage 1 — Code Analysis

Given the revision task, the full Before HTML, a unified HTML diff (Before → After), and the Before screenshot, Stage 1 produces a structured code analysis with four sections:

- **Task-Relevant Changes** — diff hunks that implement the task and their expected visual effect
- **Unrelated or Potentially Problematic Changes** — off-task modifications and their potential impact
- **Completeness Check** — each distinct requirement enumerated and checked against the diff
- **Visual Verification Notes** — 2–4 specific things to confirm in the After screenshot

Stage 1 surfaces evidence only — it never issues a PASS/FAIL verdict.

Cache Stage 1 specs for all EvaluatorModelDataset examples:

```bash
python DatasetBuilder/EvaluatorModel/fill_step1.py          # fill missing only
python DatasetBuilder/EvaluatorModel/fill_step1.py --force  # regenerate all
```

Test a single example:

```bash
python Evaluator/step1.py --example Datasets/EvaluatorModelDataset/Participant_2_CaseStudy-1.1-CLAUDE
```

### Stage 2 — Rubric Verdict

Given the revision task, the Stage 1 code analysis (as supplementary context), and both Before/After screenshots, Stage 2 outputs a 5-criterion rubric verdict plus a binary overall PASS/FAIL.

```bash
# Run over EvaluatorModelDataset (default)
python Evaluator/step2.py

# Single example
python Evaluator/step2.py --example Datasets/EvaluatorModelDataset/Participant_2_CaseStudy-1.1-CLAUDE

# Ablation: skip Step 1 — pass the raw HTML diff directly instead of the code analysis
python Evaluator/step2.py --no-step1

# Resume interrupted run
python Evaluator/step2.py --resume
```

The `--no-step1` flag uses `step2_prompt_no_step1.txt`, a separate prompt that replaces the structured Stage 1 analysis block with the raw unified diff and adjusts all guidance accordingly. This is the ablation condition for measuring the contribution of Stage 1.

Output format:

```
REQUIREMENT FULFILLMENT: PASS / PARTIAL PASS / FAIL
CONSISTENCY: PASS / PARTIAL PASS / FAIL
VISUAL & USABILITY: PASS / PARTIAL PASS / FAIL
MINIMALITY: PASS / PARTIAL PASS / FAIL
NO REGRESSIONS: PASS / PARTIAL PASS / FAIL

OVERALL: PASS / FAIL

COMMENT: <1–3 sentence rationale>
```

---

## Dataset Building

### Cache HTML diffs

```bash
python DatasetBuilder/EvaluatorModel/cache_html_diffs.py           # skip existing
python DatasetBuilder/EvaluatorModel/cache_html_diffs.py --force   # recompute all
```

### Build RevisionGeneratorModelDataset from train.jsonl

Pulls screenshots from GCS, extracts task text and taxonomy categories from `train.jsonl`, and writes `Example-NNN/` folders:

```bash
python DatasetBuilder/RevisionGeneratorModel/build_from_jsonl.py
python DatasetBuilder/RevisionGeneratorModel/build_from_jsonl.py --force
```

### Check for missing taxonomy assignments

```bash
python DatasetBuilder/RevisionGeneratorModel/check_missing.py
```

### Build revision generator fine-tuning dataset

```bash
python FineTuning/RevisionGenerator/build_dataset.py
python FineTuning/RevisionGenerator/inspect_dataset.py --n 10 > review.md
```

### Upload screenshots to GCS

```bash
python FineTuning/upload_assets.py --bucket my-bucket --dataset Datasets/EvaluatorModelDataset
python FineTuning/upload_assets.py --bucket my-bucket --force   # re-upload all
```

### Estimate training token cost

```bash
python FineTuning/count_tokens.py --dataset FineTuning/RevisionGenerator/train.jsonl --epochs 40
```

---

## Code Generation Experiment

Tests how well LLMs implement revision tasks using search-replace code generation.

### Build the experiment dataset

Runs Claude Haiku 4.5, Gemini 2.5 Flash, and GPT-4.1 mini on each of the 100 MUD screens × 1 sampled revision task:

```bash
python CodeGeneration/build_dataset.py
python CodeGeneration/build_dataset.py --models claude-haiku-4-5 gemini-2.5-flash   # subset
python CodeGeneration/build_dataset.py --force   # rerun all
```

### Sample and auto-evaluate

Picks one model per screen at random (seeded) and runs the full evaluator pipeline on each:

```bash
python CodeGeneration/build_eval_sample.py              # seed=42, gemini-3.1-pro-preview
python CodeGeneration/build_eval_sample.py --seed 0 --force
```

Output: `Datasets/CodeGenEvalSample/` with one folder per (screen, model) containing `eval_result.json`.

---

## Evaluator Testing

```bash
# Run the full pipeline against EvaluatorModelDataset
python Testing/Evaluator/run.py --backend gemini

# Override model
python Testing/Evaluator/run.py --backend gemini --model gemini-2.5-pro

# Ablation: skip Step 1 (run name is auto-suffixed with -no_step1)
python Testing/Evaluator/run.py --backend gemini --no-step1

# Resume an interrupted run
python Testing/Evaluator/run.py --backend gemini --resume

# Rerun only previously wrong examples
python Testing/Evaluator/run.py --rerun-failed Testing/Evaluator/Results/gemini-3.1-pro-preview.json

# Custom dataset
python Testing/Evaluator/run.py --dataset Datasets/CodeGenEvalSample

# Inspect results as markdown (wrong predictions first)
python Testing/Evaluator/inspect_results.py Testing/Evaluator/Results/gemini-3.1-pro-preview.json > review.md
```

Output: `Testing/Evaluator/Results/<run-name>.json` with accuracy, macro F1, per-class P/R/F1, confusion matrix, and per-example predictions.
