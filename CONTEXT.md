# GenUI — Project Context

Feed this file at the start of a new chat to restore full project context.
Last updated: 2026-05-29.

---

## What This Project Is

A research platform for studying automated UI revision. Two machine-learning pipelines:

1. **Revision Generator** — takes a Before screenshot + taxonomy category → generates a concrete revision task (what a designer/engineer should change and why). Fine-tuned on Vertex AI (Gemini SFT).
2. **Evaluator** — takes a revision task + Before/After screenshot pair + HTML diff → outputs a 5-criterion rubric verdict (each PASS / PARTIAL PASS / FAIL) plus a binary OVERALL (PASS / FAIL) and a comment. Prompt-engineered (no fine-tuning).

---

## Tech Stack

- Python 3.11, Playwright (headless Chromium for screenshots)
- LLM backends: Gemini (default: `gemini-3.1-pro-preview` for evaluator, `gemini-2.5-pro` for general use), Vertex AI SFT endpoints, Anthropic Claude, OpenAI GPT
- Fine-tuning: Vertex AI Supervised Fine-Tuning (JSONL format, GCS image URIs) — revision generator only
- HTML diff: `difflib.unified_diff` on raw HTML source (replaces browser-computed DOM diffs)
- All API keys in `Util/.env` (not committed)

---

## Key Environment Variables (`Util/.env`)

```
GOOGLE_API_KEY
ANTHROPIC_API_KEY
OPENAI_API_KEY
VERTEXAI_PROJECT
VERTEXAI_LOCATION
VERTEXAI_GENERATOR_ENDPOINT_ID   # fine-tuned revision generator endpoint
```

---

## Datasets

### EvaluatorModelDataset (`Datasets/EvaluatorModelDataset/`)

119 expert-labeled examples used for evaluator prompt engineering. Flat directory — no Train/Test splits. Each folder is named `Participant_X_CaseStudy-Y.Z-MODEL`:

- `Before/index.html` + `Before/screenshot.png`
- `After/index.html` + `After/screenshot.png`
- `Task.txt` — the revision instruction
- `html_diff.txt` — unified diff of Before → After HTML (cached)
- `step1_spec.txt` — Stage 1 code analysis (cached)
- `RubricEvaluation.json` — ground truth rubric verdict:

```json
{
  "criteria": {
    "requirementFulfillment": "pass",
    "consistencyOriginal":    "pass",
    "visualUsability":        "pass",
    "minimality":             "pass",
    "noRegressions":          "fail"
  },
  "overallEvaluation": "fail",
  "overallComment": "..."
}
```

Criterion values: `"pass"`, `"fail"`, `"partial"`, `"na"`.

**Naming convention**: `CaseStudy-Y.Z` — Y is the unique screen, Z is the participant's variant index. `MODEL` suffix is one of `CLAUDE`, `GEMINI`, `OPENAI`.

### RevisionGeneratorModelDataset (`Datasets/RevisionGeneratorModelDataset/All/`)

Training data for the revision generator SFT. Flat `Example-NNN/` folders:

- `screenshot.png` — Before screenshot
- `task.txt` — revision task text
- `prompt.txt` — `"Category: X\nDescription: Y"` (the taxonomy conditioning)
- `meta.json` — `{ "example_key", "source_folder", "label", "gcs_uri" }`

80 unique case studies × ~1.9 taxonomy labels average = 127 total examples. Built by `DatasetBuilder/RevisionGeneratorModel/build_from_jsonl.py` from `FineTuning/RevisionGenerator/train.jsonl` + GCS screenshot downloads.

### MUD_GenreUI (`Datasets/MUD_GenreUI/`)

100-screen mobile UI benchmark used to generate the broader revision task dataset:

- `images/` — 100 original app screenshots (10 app categories, 9 UI patterns)
- `html/` — reconstructed HTML/CSS files (Gemini 2.5 Pro)
- `screenshots/` — Playwright renders at 390px wide, full-page
- `metadata/` — per-screen JSON from the source MUD dataset
- `results_final_100.csv` — id, app_type, intent, ui_pattern, confidence
- `revisions.json` — `{ "<id>": { "applicable_categories": [...], "tasks": { "<category>": ["task1", ...] } } }`

477 revision tasks total, averaging 4.8 per screen. Published to HuggingFace at `VkumarStack/MUD_GenreUI`.

### CodeGenerationExperiment (`Datasets/CodeGenerationExperiment/`)

100 screens × 3 models (Claude Haiku 4.5, Gemini 2.5 Flash, GPT-4.1 mini). Each screen folder contains `Task.txt`, `category.txt`, `Before/`, and one subfolder per model (`claude-haiku-4-5/`, `gemini-2.5-flash/`, `gpt-4.1-mini/`), each with `index.html` + `screenshot.png`. Models use search-replace code generation.

### CodeGenEvalSample (`Datasets/CodeGenEvalSample/`)

Sampled subset of `CodeGenerationExperiment` for auto-evaluation: one randomly chosen model per screen (seed=42). Folder name: `{screen_id}_{model_key}/`. Contains the same structure as `EvaluatorModelDataset` examples (`Before/`, `After/`, `Task.txt`, `html_diff.txt`, `step1_spec.txt`) plus `eval_result.json` with the auto-evaluator verdict.

---

## MUD_GenreUI Dataset Pipeline (`MUD_Dataset_Utils/`)

1. **HTML generation** (`MUD_generate_html.py`) — Gemini 2.5 Pro reconstructs each screenshot as a self-contained HTML/CSS file. `max_output_tokens=65536`, `thinking_budget=2048`.
2. **Screenshot rendering** (`MUD_screenshot.py`) — Playwright renders at 390px, full-page.
3. **Visual inspection** (`MUD_inspect.py`) — outputs `review_mud.md`.
4. **Revision generation** (`MUD_generate_revisions.py`):
   - *Filter*: Gemini 2.5 Pro (base) identifies applicable taxonomy categories per screen.
   - *Generate*: fine-tuned VertexAI revision generator produces 3 tasks per applicable category.
   - Supports `--id` for single screen, `--backend gemini` for base model. Resume-safe.
5. **Revision inspection** (`MUD_inspect_revisions.py`) — outputs `review_mud_revisions.md`.
6. **HuggingFace upload** (`MUD_upload_hf.py`) — packages as `data/train.parquet` (one row per screen: image bytes, screenshot bytes, HTML, revision tasks).

---

## 7 Taxonomy Categories (Revision Generator)

From `Taxonomy/RevisionTaxonomy/Results/taxonomy.json`:

1. **Reorganize Information Hierarchy** — changes high-level structure/positioning to guide attention
2. **Refine Layout & Spacing** — adjusts alignment, spacing, sizing for visual balance
3. **Clarify Function & State** — makes an element's purpose or state unambiguous
4. **Add or Surface Functionality** — introduces or surfaces a capability/control
5. **Simplify & Reduce Clutter** — reduces cognitive load by removing/consolidating elements
6. **Strengthen Visual Consistency** — aligns styling/terminology with UI conventions
7. **Improve Readability & Accessibility** — enhances legibility and contrast

---

## Evaluation Pipeline (Two Stages)

The default evaluator model is `gemini-3.1-pro-preview` for both stages.

### Stage 1 — Code Analysis (`Evaluator/step1.py`)

**Inputs:** revision task + Before screenshot (image) + full Before HTML source + unified HTML diff (Before → After, computed by `Util/html_diff.py` via `difflib.unified_diff`)

**Output:** structured code analysis report with four sections:
1. **Task-Relevant Changes** — diff hunks implementing the task, with expected visual effects
2. **Unrelated or Potentially Problematic Changes** — off-task modifications and their likely visual/functional impact
3. **Completeness Check** — every distinct requirement enumerated individually, checked against the diff; also flags multi-instance tasks (e.g. "each card"), move tasks (addition + removal required), and named deliverables
4. **Visual Verification Notes** — 2–4 specific things the visual evaluator should confirm in the After screenshot

Stage 1 is evidence-only: all findings are phrased as observations ("the diff shows…"). It never issues a verdict. An anti-hallucination constraint requires every quoted code snippet to be copied verbatim from the diff.

Results cached per-folder as `step1_spec.txt`.

### Stage 2 — Visual Evaluation (`Evaluator/step2.py`)

**Inputs:** revision task + Stage 1 code analysis (as supplementary context, not binding verdict) + Before screenshot + After screenshot

**Output:** 5-criterion rubric + binary OVERALL + COMMENT

The Stage 1 analysis directs visual attention but screenshots are the ground truth. Key prompt engineering rules:
- Verify every Completeness Check item visually — do not trust code analysis alone
- Repeating-element tasks must be confirmed on all instances visible in Before
- Distinguish omission (not implementing) from reversal (actively worsening)
- Regressions require concrete evidence from code analysis or screenshots — layout reflow is not a regression
- PARTIAL PASS on Requirement Fulfillment + any other criterion below PASS → lean toward overall FAIL

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

## LLM Backend Abstraction (`Util/backends.py`)

All backends share: `backend.generate(prompt: str, images: list[bytes]) -> str`

```python
from backends import get_backend

backend = get_backend("gemini")
backend = get_backend("gemini", "gemini-3.1-pro-preview")
backend = get_backend("anthropic", "claude-opus-4-7")
backend = get_backend("vertexai")   # uses VERTEXAI_GENERATOR_ENDPOINT_ID
```

---

## Dataset Building (`DatasetBuilder/`)

### Evaluator dataset

```bash
# Compute html_diff.txt for all EvaluatorModelDataset examples
python DatasetBuilder/EvaluatorModel/cache_html_diffs.py [--force]

# Fill Stage 1 specs
python DatasetBuilder/EvaluatorModel/fill_step1.py [--force]
```

### Revision generator dataset

```bash
# Build RevisionGeneratorModelDataset/All/ from train.jsonl + GCS screenshots
python DatasetBuilder/RevisionGeneratorModel/build_from_jsonl.py [--force]

# Find examples with no taxonomy assignment
python DatasetBuilder/RevisionGeneratorModel/check_missing.py

# Build SFT JSONL from RevisionGeneratorModelDataset
python FineTuning/RevisionGenerator/build_dataset.py

# Upload screenshots to GCS
python FineTuning/upload_assets.py --bucket <bucket> --dataset Datasets/EvaluatorModelDataset

# Inspect training examples
python FineTuning/RevisionGenerator/inspect_dataset.py --n 10 > review.md

# Estimate training cost
python FineTuning/count_tokens.py --dataset FineTuning/RevisionGenerator/train.jsonl --epochs 40
```

---

## Evaluator Testing (`Testing/Evaluator/`)

```bash
# Full pipeline run against EvaluatorModelDataset
python Testing/Evaluator/run.py --backend gemini [--resume]

# Rerun only previously wrong examples
python Testing/Evaluator/run.py --rerun-failed Testing/Evaluator/Results/gemini-3.1-pro-preview.json

# Custom run name or dataset
python Testing/Evaluator/run.py --run-name my-run --dataset Datasets/CodeGenEvalSample

# Inspect results (wrong predictions first, with Stage 1 output in collapsible sections)
python Testing/Evaluator/inspect_results.py Testing/Evaluator/Results/gemini-3.1-pro-preview.json > review.md
```

Output JSON: `{ run_name, backend, model, dataset, timestamp, examples: [{folder, ground_truth, gt_criteria, predicted, pred_criteria, comment, response}], metrics: {accuracy, macro_f1, per_class, confusion_matrix} }`

---

## Important Design Decisions

- **HTML diff over browser DOM diff**: Stage 1 uses `difflib.unified_diff` on raw HTML source rather than browser-computed style diffs. This is lighter, portable, and avoids the complexity of matching computed CSS properties across DOM mutations.
- **Stage 1 as code analysis, not visual guide**: Stage 1 explicitly reasons about the diff to surface evidence and flag issues. It is not a visual attention guide — it produces a structured checklist that Stage 2 uses as supplementary context.
- **Stage 1 anti-hallucination**: Every code snippet quoted in Stage 1 must be copied verbatim from the diff. The model is prohibited from reconstructing hunks not present in the diff.
- **Screenshots as ground truth in Stage 2**: The Stage 1 code analysis supplements but never overrides screenshot evidence. If the After screenshot contradicts what the code suggests, the screenshot wins.
- **No evaluator fine-tuning**: Prompt engineering on Gemini 2.5 Pro / gemini-3.1-pro-preview was found to match or exceed the fine-tuned model performance. Fine-tuning for the evaluator has been abandoned.
- **Per-variant Stage 1**: Since the HTML diff differs per model variant, Stage 1 is computed independently for each `Participant_X_CaseStudy-Y.Z-MODEL` folder (no cross-model deduplication).
- **Evaluator dataset is flat**: `EvaluatorModelDataset/` has no Train/Test subdirectory split. The 119 examples (after filtering ambiguous cases) are used directly for prompt engineering.
- **Rubric output format**: 5 criteria (Requirement Fulfillment, Consistency, Visual & Usability, Minimality, No Regressions), each PASS / PARTIAL PASS / FAIL. Binary OVERALL PASS / FAIL only (no PARTIAL PASS allowed at overall level).
- **CodeGenerationExperiment uses search-replace**: Models are given the Before HTML and a revision task and must return `<<<FIND>>>...<<<REPLACE>>>...<<<END>>>` blocks. This avoids full-HTML regeneration and makes diffs tractable.

---

## File Layout Quick Reference

```
Evaluator/step1_prompt.txt                          # Stage 1 prompt (code analysis)
Evaluator/step2_prompt.txt                          # Stage 2 rubric evaluation prompt
Taxonomy/RevisionTaxonomy/Results/taxonomy.json     # 7 revision categories
Datasets/EvaluatorModelDataset/                     # 119 labeled evaluator examples (flat)
Datasets/RevisionGeneratorModelDataset/All/         # revision generator training examples
Datasets/MUD_GenreUI/revisions.json                 # 477 generated revision tasks
Datasets/CodeGenerationExperiment/                  # 100 screens × 3 models
Datasets/CodeGenEvalSample/                         # sampled auto-evaluation subset
FineTuning/RevisionGenerator/train.jsonl            # SFT training data (152 examples)
Testing/Evaluator/Results/                          # evaluator run metrics (JSON)
Util/backends.py                                    # all LLM backend logic
Util/html_diff.py                                   # unified HTML diff utility
```
