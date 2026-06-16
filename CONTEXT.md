# GenUI — Project Context

Feed this file at the start of a new chat to restore full project context.
Last updated: 2026-06-12.

> Each top-level directory has its own `README.md` with script-level detail; this
> file is the conceptual reference. `README.md` (root) is the directory map.

---

## What This Project Is

A research platform for studying automated UI revision. Three pieces:

1. **Revision Generator** — Before screenshot + taxonomy category → a concrete revision task (what to change and why). Fine-tuned on Vertex AI (Gemini SFT).
2. **Evaluator** — revision task + Before/After screenshot pair + HTML diff → a 5-criterion rubric verdict (each PASS / PARTIAL PASS / FAIL) plus a binary OVERALL (PASS / FAIL) and a comment. Prompt-engineered (no fine-tuning).
3. **Code Generation experiment** — measures how well general LLMs implement revision tasks, scored by the evaluator.

---

## Tech Stack

- Python 3.11, Playwright (headless Chromium for screenshots)
- LLM backends: Gemini (general default `gemini-2.5-pro`; evaluator default `gemini-3.1-pro-preview`), Vertex AI SFT endpoints, Anthropic Claude, OpenAI GPT, and OpenAI-compatible providers (Together, DeepSeek, Groq, OpenRouter — used by the code-gen experiment)
- Fine-tuning: Vertex AI Supervised Fine-Tuning (JSONL, GCS image URIs) — revision generator only
- HTML diff: `difflib.unified_diff` on raw HTML source (replaces browser-computed DOM diffs)
- All API keys in `Util/.env` (not committed)

---

## Key Environment Variables (`Util/.env`)

```
GOOGLE_API_KEY
ANTHROPIC_API_KEY
OPENAI_API_KEY
TOGETHER_API_KEY                 # code-gen experiment (OpenAI-compatible)
DEEPSEEK_API_KEY                 # code-gen experiment
GROQ_API_KEY                     # optional
OPENROUTER_API_KEY               # optional
VERTEXAI_PROJECT
VERTEXAI_LOCATION
VERTEXAI_GENERATOR_ENDPOINT_ID   # fine-tuned revision generator endpoint
```

---

## Datasets

See `Datasets/README.md` for the producer→consumer map of all of these.

### EvaluatorModelDataset (`Datasets/EvaluatorModelDataset/`)

~117 expert-labeled examples used for evaluator prompt engineering and testing. Flat directory — no Train/Test splits. Each folder is named `Participant_X_CaseStudy-Y.Z-MODEL`:

- `Before/index.html` + `Before/screenshot.png`, `After/index.html` + `After/screenshot.png`
- `Task.txt` — the revision instruction
- `html_diff.txt` — cached unified Before→After HTML diff
- `step1_spec.txt` — cached Stage 1 code analysis
- `RubricEvaluation.json` — ground-truth rubric verdict:

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

Criterion values: `"pass"`, `"fail"`, `"partial"`, `"na"`. Cases humans found ambiguous are held aside in `Datasets/AmbiguousEvaluatorData/` (reference only; no script reads it).

**Naming**: `CaseStudy-Y.Z` — Y is the unique screen, Z the participant's variant index; `MODEL` ∈ {`CLAUDE`, `GEMINI`, `OPENAI`}.

### RevisionGeneratorModelDataset (`Datasets/RevisionGeneratorModelDataset/All/`)

Training data for the revision generator SFT. Flat `Example-NNN/` folders:

- `screenshot.png` — Before screenshot
- `meta.json` — `{ "example_key", "source_folder", "label", "gcs_uri" }` (`label` = taxonomy category)

80 unique case studies × ~1.6 taxonomy labels = 127 examples (matches `train.jsonl`). Consumed by `FineTuning/` (build the SFT JSONL, upload Before images to GCS).

### MUD_GenreUI (`Datasets/MUD_GenreUI/`)

100-screen mobile UI benchmark — the core screens used to generate revision tasks and to drive the code-gen experiment:

- `images/` — original app screenshots
- `html/` — reconstructed HTML/CSS (Gemini 2.5 Pro)
- `screenshots/` — Playwright renders (390px wide, full-page)
- `metadata/`, `results_final_100.csv` — per-screen source metadata
- `revisions.json` — `{ "<id>": { "applicable_categories": [...], "tasks": { "<category>": ["task1", ...] } } }`

Published to HuggingFace at `VkumarStack/MUD_GenreUI`. The task count grows with `--tasks-per-category`.

### CodeGenerationExperiment (`Datasets/CodeGenerationExperiment/`)

Code-gen outputs: one folder per MUD screen, each with `Task.txt`, `category.txt`, `Before/`, and one subfolder per **model variant** — 10 models plus their `-novision` ablation variants (up to 18), each with `index.html` (+ `screenshot.png` when valid). Default generation is **full-HTML** (whole updated document, retried on invalid HTML); search-and-replace is available as an alternate/fallback mode. Built by `CodeGeneration/build_dataset.py`.

### CodeGenEvalSample (`Datasets/CodeGenEvalSample/`)

Auto-evaluator verdicts for the code-gen outputs — every (screen, model) pair from a run, folder `{screen_id}_{model_key}/`. Same structure as an `EvaluatorModelDataset` example (`Before/`, `After/`, `Task.txt`, `html_diff.txt`, `step1_spec.txt`) plus `eval_result.json`. Built by `CodeGeneration/build_eval_sample.py`.

### ValidationData (`Datasets/ValidationData/`)

User-study screens rendered for the human↔auto agreement study (`Validation/`). Per-screen folders mirror `CodeGenerationExperiment` (`Before/` + `claude-haiku-4-5/`, `gemini-2.5-flash/`, `gpt-4.1-mini/`). Built by `Validation/build_validation_data.py`.

---

## MUD_GenreUI Dataset Pipeline (`MUD_Dataset_Utils/`)

1. **HTML generation** (`MUD_generate_html.py`) — Gemini 2.5 Pro reconstructs each screenshot as a self-contained HTML/CSS file.
2. **Screenshot rendering** (`MUD_screenshot.py`) — Playwright, 390px wide, full-page.
3. **Revision generation** (`MUD_generate_revisions.py`):
   - *Filter*: Gemini 2.5 Pro (base) identifies applicable taxonomy categories per screen.
   - *Generate*: fine-tuned VertexAI revision generator produces N tasks per applicable category (`--tasks-per-category`, default 3).
   - Supports `--id` for a single screen, `--backend gemini` for the base model. Resume-safe.
4. **HuggingFace upload** (`MUD_upload_hf.py`) — packages as `data/train.parquet` (one row per screen: image bytes, screenshot bytes, HTML, revision tasks).

Reconstructed HTML is imperfect and **should be reviewed in a browser** before downstream use.

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

Default evaluator model `gemini-3.1-pro-preview` for both stages.

### Stage 1 — Code Analysis (`Evaluator/step1.py`)

**Inputs:** revision task + Before screenshot + full Before HTML + unified HTML diff (Before→After, via `Util/html_diff.py`).

**Output:** structured code analysis with four sections:
1. **Task-Relevant Changes** — diff hunks implementing the task, with expected visual effects
2. **Unrelated or Potentially Problematic Changes** — off-task modifications and likely impact
3. **Completeness Check** — every requirement enumerated and checked against the diff; flags multi-instance tasks, move tasks (add + remove), named deliverables
4. **Visual Verification Notes** — 2–4 things to confirm in the After screenshot

Evidence-only — never a verdict. Anti-hallucination: quoted code must be copied verbatim from the diff. Cached as `step1_spec.txt`.

### Stage 2 — Visual Evaluation (`Evaluator/step2.py`)

**Inputs:** revision task + Stage 1 analysis (supplementary, not binding) + Before + After screenshots.

**Output:** 5-criterion rubric + binary OVERALL + COMMENT. Screenshots are the ground truth; the Stage 1 analysis directs attention only. `--no-step1` ablation uses `step2_prompt_no_step1.txt` (raw diff instead of the analysis).

```
REQUIREMENT FULFILLMENT: PASS / PARTIAL PASS / FAIL
CONSISTENCY:             PASS / PARTIAL PASS / FAIL
VISUAL & USABILITY:      PASS / PARTIAL PASS / FAIL
MINIMALITY:              PASS / PARTIAL PASS / FAIL
NO REGRESSIONS:          PASS / PARTIAL PASS / FAIL

OVERALL: PASS / FAIL
COMMENT: <1–3 sentence rationale>
```

Experiments report 3 of the 5 criteria (Requirement Fulfillment, Consistency, No Regressions); the evaluator still emits all 5.

---

## LLM Backend Abstraction (`Util/backends.py`)

All backends share `backend.generate(prompt: str, images: list[bytes], max_tokens=...) -> str`.

```python
from backends import get_backend

backend = get_backend("gemini")                          # gemini-2.5-pro
backend = get_backend("gemini", "gemini-3.1-pro-preview")
backend = get_backend("anthropic", "claude-sonnet-4-6")
backend = get_backend("vertexai")                        # VERTEXAI_GENERATOR_ENDPOINT_ID
backend = get_backend("together", "Qwen/Qwen3.5-397B-A17B")  # OpenAI-compatible (model required)
```

Adding a provider requires editing `backends.py` — no plugin/config mechanism.

---

## Supporting scripts

### Cache evaluator inputs (`DatasetBuilder/EvaluatorModel/`)
```bash
python DatasetBuilder/EvaluatorModel/cache_html_diffs.py [--force]
python DatasetBuilder/EvaluatorModel/fill_step1.py [--force]
```

### Revision generator SFT (`FineTuning/`)
```bash
python FineTuning/upload_assets.py --bucket genui-sft     # Before images → GCS + manifest.json
python FineTuning/RevisionGenerator/build_dataset.py      # → train.jsonl (127 examples)
python FineTuning/count_tokens.py --epochs 40             # token-cost estimate
```
Tuning runs through the Vertex AI console (upload `train.jsonl`).

### Evaluator testing (`Testing/Evaluator/`)
```bash
python Testing/Evaluator/run.py --backend gemini [--resume]    # default gemini-3.1-pro-preview
python Testing/Evaluator/run.py --rerun-failed Testing/Evaluator/Results/gemini-3.1-pro-preview.json
python Testing/Evaluator/inspect_results.py <results.json> > review.md
```
Output JSON: `{ run_name, backend, model, dataset, timestamp, examples: [...], metrics: {accuracy, macro_f1, per_class, confusion_matrix} }`.

### Evaluator validation (`Validation/`)
```bash
python Validation/build_validation_data.py                 # render ValidationData from study screens
python Validation/validate.py [--participants p_... ...]   # auto-vs-human agreement
```

---

## Important Design Decisions

- **HTML diff over browser DOM diff**: Stage 1 uses `difflib.unified_diff` on raw HTML source — lighter, portable, no computed-CSS matching.
- **Stage 1 as code analysis, not visual guide**: Stage 1 reasons about the diff to surface evidence and flag issues, producing a checklist Stage 2 uses as supplementary context.
- **Stage 1 anti-hallucination**: every quoted snippet must be verbatim from the diff.
- **Screenshots as ground truth in Stage 2**: if the After screenshot contradicts the code analysis, the screenshot wins.
- **No evaluator fine-tuning**: prompt engineering on Gemini matched/exceeded the fine-tuned model; evaluator fine-tuning was abandoned.
- **Per-variant Stage 1**: the HTML diff differs per model variant, so Stage 1 is computed independently per `*-MODEL` folder.
- **Evaluator dataset is flat**: no Train/Test split; the labeled examples are used directly for prompt engineering, with ambiguous cases held aside.
- **Rubric output format**: 5 criteria, each PASS / PARTIAL PASS / FAIL; binary OVERALL only.
- **Code-gen experiment defaults to full-HTML generation**: models return the complete updated document (retried on invalid HTML), with search-and-replace edit blocks (`<<<FIND>>>…<<<REPLACE>>>…<<<END>>>`) available as an alternate mode and as a fallback. A vision ablation runs each vision-capable model text-only as a `{model}-novision` variant.

---

## File Layout Quick Reference

```
Evaluator/step1_prompt.txt                          # Stage 1 prompt (code analysis)
Evaluator/step2_prompt.txt                          # Stage 2 rubric prompt (+ _no_step1 variant)
Taxonomy/RevisionTaxonomy/Results/taxonomy.json     # 7 revision categories
Datasets/EvaluatorModelDataset/                     # labeled evaluator examples (flat)
Datasets/RevisionGeneratorModelDataset/All/         # revision generator training examples
Datasets/MUD_GenreUI/revisions.json                 # generated revision tasks per screen
Datasets/CodeGenerationExperiment/                  # code-gen outputs (10 models + vision ablation)
Datasets/CodeGenEvalSample/                          # auto-evaluation of those outputs
Datasets/ValidationData/                            # user-study agreement screens
FineTuning/RevisionGenerator/train.jsonl            # SFT training data (127 examples)
Testing/Evaluator/Results/                          # evaluator run metrics (JSON)
Util/backends.py                                    # all LLM backend logic
Util/html_diff.py                                   # unified HTML diff utility
```
