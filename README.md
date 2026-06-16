# GenUI — Automated UI Revision Generation & Evaluation

This project supports two automated pipelines for UI revision research:

1. **Revision Generation** — given a Before screenshot and a taxonomy category, generates a plausible revision task using a fine-tuned VLM conditioned on a 7-category revision taxonomy.
2. **Evaluation** — given a Before/After UI pair and a revision task, determines whether the task was correctly implemented using a two-stage pipeline (code analysis → visual rubric verdict).

A third experiment, **Code Generation**, measures how well general LLMs implement those revision tasks, scored by the same auto-evaluator.

> **Per-directory READMEs are the detailed source of truth.** Each top-level
> directory has its own `README.md` describing its scripts, flags, and data
> formats. This file is the map; `CONTEXT.md` is the conceptual reference.

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
# Core
GOOGLE_API_KEY=...            # Gemini (evaluator + MUD pipeline)
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...

# OpenAI-compatible providers (used by the code-generation experiment)
TOGETHER_API_KEY=...
DEEPSEEK_API_KEY=...
GROQ_API_KEY=...              # optional
OPENROUTER_API_KEY=...        # optional

# Vertex AI (fine-tuned revision generator) — also: gcloud auth application-default login
VERTEXAI_PROJECT=...
VERTEXAI_LOCATION=us-central1
VERTEXAI_GENERATOR_ENDPOINT_ID=...
```

---

## Directory Structure

Every directory below contains its own `README.md` with the details.

```
Datasets/                           # see Datasets/README.md for the full map
    MUD_GenreUI/                    # 100-screen mobile UI benchmark (the core screens)
    CodeGenerationExperiment/       # code-gen outputs: per screen, one folder per model variant
    CodeGenEvalSample/              # auto-evaluator verdicts for the code-gen outputs
    ValidationData/                 # user-study screens, for human↔auto agreement (Validation/)
    EvaluatorModelDataset/          # expert-labeled examples (evaluator working/test set)
    AmbiguousEvaluatorData/         # case studies humans found ambiguous (reference only)
    RevisionGeneratorModelDataset/  # SFT training examples for the revision generator

MUD_Dataset_Utils/                  # build the MUD_GenreUI dataset (image → HTML → screenshot → revisions → HF)
RevisionGeneration/                 # generate revision tasks from a Before screenshot
Taxonomy/                           # derive the revision + evaluation taxonomies
Evaluator/                          # the two-stage auto-evaluator (step1 → step2)
CodeGeneration/                     # the code-generation experiment (build → eval → inspect)
Validation/                         # auto-evaluator agreement vs. live study participants
Testing/                            # auto-evaluator accuracy vs. labeled ground truth
FineTuning/                         # build + cost the revision generator's SFT dataset (Vertex AI)
DatasetBuilder/                     # cache html_diff.txt / step1_spec.txt for EvaluatorModelDataset
Util/                               # LLM backends, HTML diff, screenshot rendering, .env
Paper/                              # ACM-format capstone paper
Deprecated/                         # old approaches kept for reference
```

---

## Supported Backends

`Util/backends.py` — all share `backend.generate(prompt, images, max_tokens) -> str`.

| Backend | Default model | Notes |
|---|---|---|
| `gemini` | `gemini-2.5-pro` | `GOOGLE_API_KEY`. The evaluator overrides this to `gemini-3.1-pro-preview`. |
| `vertexai` | _(endpoint required)_ | `VERTEXAI_PROJECT` + `VERTEXAI_LOCATION` + an endpoint id. |
| `anthropic` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `openai` | `gpt-4o` | `OPENAI_API_KEY` |
| OpenAI-compatible | _(model required)_ | `together`, `deepseek`, `groq`, `openrouter` — share one client; each needs its `*_API_KEY`. |

Adding a provider requires editing `backends.py` (no config/plugin mechanism) —
see `Util/README.md`.

---

## Pipelines at a glance

### MUD dataset (`MUD_Dataset_Utils/`)
Real mobile screenshot → reconstructed HTML (Gemini) → Playwright render →
applicable taxonomy categories + generated revision tasks → published to
HuggingFace. Resume-safe; grow it by dropping new `{id}.png` into
`Datasets/MUD_GenreUI/images/` and re-running. **Reconstructed HTML should be
eyeballed in a browser before use.** Tasks-per-category is configurable
(`--tasks-per-category`, default 3).

### Revision generation (`RevisionGeneration/`)
`generate.py` takes a Before screenshot + taxonomy category and produces a
revision task, using the fine-tuned Vertex AI generator (`--backend vertexai`)
or base Gemini (`--backend gemini`).

### Evaluation — two stages (`Evaluator/`)
Default model `gemini-3.1-pro-preview` for both stages.

- **Stage 1 — Code Analysis** (`step1.py`): task + full Before HTML + unified
  HTML diff (Before→After) + Before screenshot → a structured, evidence-only code
  report (no verdict). Cached as `step1_spec.txt`.
- **Stage 2 — Rubric Verdict** (`step2.py`): task + Stage 1 analysis + Before/After
  screenshots → a 5-criterion rubric plus a binary OVERALL PASS/FAIL. `--no-step1`
  is the ablation (passes the raw diff instead of the Stage 1 analysis).

Rubric output:

```
REQUIREMENT FULFILLMENT: PASS / PARTIAL PASS / FAIL
CONSISTENCY:             PASS / PARTIAL PASS / FAIL
VISUAL & USABILITY:      PASS / PARTIAL PASS / FAIL
MINIMALITY:              PASS / PARTIAL PASS / FAIL
NO REGRESSIONS:          PASS / PARTIAL PASS / FAIL

OVERALL: PASS / FAIL
COMMENT: <1–3 sentence rationale>
```

### Code generation experiment (`CodeGeneration/`)
10 models (5 small / 5 large) implement one sampled revision task per MUD screen,
with a vision ablation (`{model}-novision` text-only variants, on by default).
Default generation is **full-HTML** (the model returns the whole updated
document, retried on invalid HTML); `--search-replace` / `--fallback-search-replace`
switch to or fall back on edit-block generation. Then `build_eval_sample.py` runs
the auto-evaluator over the outputs. See `CodeGeneration/README.md`.

### Validation & testing the evaluator (`Validation/`, `Testing/`)
- `Testing/` scores the evaluator's PASS/FAIL accuracy against the human labels in
  `EvaluatorModelDataset` (default model `gemini-3.1-pro-preview`; `--dataset` for
  another labeled set in the same folder format).
- `Validation/` scores the evaluator's agreement with live user-study gradings
  (from a Supabase export CSV), per participant.

---

## Supporting scripts

### Caching evaluator inputs (`DatasetBuilder/EvaluatorModel/`)
```bash
python DatasetBuilder/EvaluatorModel/cache_html_diffs.py [--force]   # html_diff.txt
python DatasetBuilder/EvaluatorModel/fill_step1.py [--force]         # step1_spec.txt
```

### Revision generator fine-tuning (`FineTuning/`)
```bash
python FineTuning/upload_assets.py --bucket genui-sft        # Before images → GCS + manifest.json
python FineTuning/RevisionGenerator/build_dataset.py         # → RevisionGenerator/train.jsonl
python FineTuning/count_tokens.py --epochs 40                # estimate tuning token cost
```
Tuning itself is run through the Vertex AI console (upload `train.jsonl`). See
`FineTuning/README.md`.

### Util (`Util/`)
```bash
python Util/screenshot.py --example Datasets/EvaluatorModelDataset/Participant_2_CaseStudy-1.1-CLAUDE
python Util/screenshot.py --dir Datasets/EvaluatorModelDataset --viewport 375x812
```
`html_diff.py` provides the unified Before→After HTML diff used by Stage 1.
