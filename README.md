# GenUI — Automated UI Revision Generation & Evaluation

This project supports two automated pipelines for UI revision research:

1. **Revision Generation** — given a Before screenshot, generates plausible revision tasks using a VLM, conditioned on a 7-category revision taxonomy.
2. **Evaluation** — given a Before/After UI pair and a revision task, determines whether the task was correctly implemented (PASS / PARTIAL / FAIL) using a two-step pipeline.

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
    RawDataset/                     # 139 expert-labeled UI revision examples
    EvaluatorModelDataset/
        Train/                      # evaluator model training examples
        Test/                       # evaluator model test examples (30 examples)
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
    step1.py                        # generate expected-change spec (single example / testing)
    step1_prompt.txt                # editable prompt template for Step 1
    step2.py                        # verdict from spec + screenshots + DOM diff
    step2_prompt.txt                # editable prompt template for Step 2

DatasetBuilder/
    EvaluatorModel/
        cache_dom_diffs.py          # compute and cache dom_diff.txt for RawDataset
        fill_step1.py               # fill missing Step 1 specs
        split.py                    # stratified train/test split
        sync_dom_diffs.py           # copy updated dom_diffs into Train/Test splits
        split_summary.json
    RevisionGeneratorModel/
        split.py                    # multi-label stratified train/test split
        check_missing.py            # find and fill missing Taxonomy.txt
        split_summary.json

FineTuning/
    count_tokens.py                 # estimate token cost for a training JSONL
    sample_dataset.py               # spot-check random training examples as markdown
    upload_assets.py                # upload Before/After screenshots to GCS
    manifest.json                   # GCS URIs for all uploaded screenshots
    Evaluator/
        build_dataset.py            # build train.jsonl for evaluator model
    RevisionGenerator/
        build_dataset.py            # build train.jsonl for revision generator model

Testing/
    Evaluator/
        run.py                      # evaluate a model against the test set
        inspect_results.py          # format results JSON as markdown (wrong-first)
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

### Step 1 — Expected-change specification

Fill missing specs for all RawDataset examples (run before step2 or fine-tuning):

```bash
python DatasetBuilder/EvaluatorModel/fill_step1.py
python DatasetBuilder/EvaluatorModel/fill_step1.py --resume
```

Test a single example:

```bash
python Evaluator/step1.py --example Datasets/RawDataset/Participant_2_CaseStudy-1.1-CLAUDE
```

### Step 2 — Pass / Partial / Fail verdict

```bash
# Run over all RawDataset examples
python Evaluator/step2.py

# Single example
python Evaluator/step2.py --example Datasets/RawDataset/Participant_2_CaseStudy-1.1-CLAUDE

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
# Compute dom_diff.txt for all RawDataset examples (skip existing)
python DatasetBuilder/EvaluatorModel/cache_dom_diffs.py

# Force recompute all
python DatasetBuilder/EvaluatorModel/cache_dom_diffs.py --force

# After recomputing, sync updated diffs into Train/Test splits
python DatasetBuilder/EvaluatorModel/sync_dom_diffs.py
```

### Build fine-tuning datasets

```bash
# Evaluator model
python FineTuning/Evaluator/build_dataset.py

# Revision generator model
python FineTuning/RevisionGenerator/build_dataset.py
```

### Estimate training cost

```bash
python FineTuning/count_tokens.py --dataset FineTuning/Evaluator/train.jsonl
python FineTuning/count_tokens.py --dataset FineTuning/RevisionGenerator/train.jsonl --epochs 5
```

### Spot-check training examples

```bash
python FineTuning/sample_dataset.py --n 5 --seed 42 > review.md
```

### Upload screenshots to GCS

```bash
python FineTuning/upload_assets.py --bucket my-bucket --prefix genui
python FineTuning/upload_assets.py --bucket my-bucket --prefix genui --force  # re-upload all
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

# Format results for manual inspection (wrong predictions first)
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
