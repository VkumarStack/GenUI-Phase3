# GenUI — Handoff

For the rest of the project, three pieces of work are required:

1. **Collect more user-study validation data** and split it into an
   evaluator-tuning set and a held-out test set.
2. **Grow the MUD screen dataset** — more screenshots → reconstructed HTML →
   revision tasks.
3. **Run the code-generation experiment on a larger dataset.**

Each is a section below. Read "Before you start" first — there's a blocker that
affects tasks 2 and (optionally) the generator work.

---

## Before you start

### Environment
- Setup is in `README.md` (conda env, `pip install -r requirements.txt`,
  `playwright install chromium`).
- API keys live in `Util/.env`. You'll need at minimum `GOOGLE_API_KEY` (Gemini —
  the auto-evaluator and the MUD pipeline). For the code-gen experiment you also
  need `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `TOGETHER_API_KEY`, `DEEPSEEK_API_KEY`
  (and optionally `GROQ_API_KEY`, `OPENROUTER_API_KEY`). For the fine-tuned
  revision generator: `VERTEXAI_PROJECT`, `VERTEXAI_LOCATION`,
  `VERTEXAI_GENERATOR_ENDPOINT_ID`, plus `gcloud auth application-default login`.
- The datasets ship as a **zip** alongside the repo (the `Datasets/` folders are
  large and not all tracked in git). Unzip into `Datasets/` before running
  anything that reads them.

### ⚠️ The fine-tuned revision generator is in Vivek's GCP account
The `VERTEXAI_GENERATOR_ENDPOINT_ID` in `.env` points at an endpoint in the
original developer's (Vivek's) GCP account. From any other account it returns
`404 Endpoint ... not found` — this is expected, **not** a decommissioned
endpoint. Everything else runs without it; the revision generator falls back to
base Gemini with `--backend gemini`.

**To use the fine-tuned generator, coordinate with Vivek to transfer the model**
to your GCP account. (Don't follow an improvised transfer procedure — arrange it
with him directly.) Until then, expect base-Gemini revision quality, which is
lower than the fine-tuned model's.

---

## Task 1 — More validation data + tuning the evaluator

**Goal:** gather more user-study gradings, then use them to (a) measure the
auto-evaluator's agreement with humans and (b) tune it, holding out a test set.

Two directories are involved: `Validation/` (agreement vs. live participants) and
`Testing/` (accuracy vs. a fixed labeled set). See their READMEs for command
detail.

### Getting the data in

1. Export the case-evaluations table from Supabase to a CSV in the same shape as
   `Validation/iteration3_case_evaluations_rows.csv` (columns used:
   `participant_id`, `screen_id`, `prompt_text`, `provider_rubrics`). Drop it in
   `Validation/`.
2. Export the matching screen HTML into
   `Validation/iteration-3-screens/cge/{screen_id}/` (before HTML + each provider's
   generated output + `revision_prompt.txt`).
3. `python Validation/build_validation_data.py` renders these into
   `Datasets/ValidationData/`.
4. `python Validation/validate.py` runs the auto-evaluator on each graded pair and
   reports human↔auto agreement.

### ⚠️ Participant selection IS data selection
`validate.py` only scores the participant IDs you pass to `--participants`
(default is the single primary participant `p_a3c3baaa-...`). The CSV mixes
several participants with very uneven grading counts. **The participant filter is
your tuning/holdout split** — e.g. tune the evaluator prompts on some participant
IDs, hold others out as a test set. Be deliberate about which IDs go where.

Also: gradings whose CSV `prompt_text` no longer matches the rendered `Task.txt`
are silently dropped as `task_mismatch` (the count is printed) — watch it.

### Turning a held-out split into a Testing dataset
`Testing/Evaluator/run.py` scores binary PASS/FAIL against `RubricEvaluation.json`
ground truth (default dataset `EvaluatorModelDataset`, default model
`gemini-3.1-pro-preview`). To test on your held-out validation data, assemble it
into the tester's per-example format — `Task.txt`, `Before/screenshot.png` +
`After/screenshot.png`, `RubricEvaluation.json`, plus precomputed `step1_spec.txt`
/ `html_diff.txt` caches (`DatasetBuilder/EvaluatorModel/{cache_html_diffs,fill_step1}.py`) —
and point `run.py` at it with `--dataset PATH`.

### Where to tune the evaluator
- **Hallucinations (inventing changes that aren't real) → Stage 1.** The code diff
  is the grounding signal, consumed in `Evaluator/step1_prompt.txt`. It already has
  an anti-hallucination rule (quote only what's in the diff). Stage 1 should
  *condition* Stage 2's visual attention, not *bias* its verdict.
- **Strictness / leniency → Stage 2 prompting** (`Evaluator/step2_prompt.txt`, and
  the ablation variant `step2_prompt_no_step1.txt`). Current PASS bar: all *major*
  parts of the task done (a minor missing detail can still pass) AND no *major*
  regression that makes the UI unusable. Shift it via the "OVERALL VERDICT
  GUIDANCE" and per-criterion thresholds in that prompt.

### Open decision: 5-criterion rubric → 3
The rubric currently emits 5 criteria but experiments only report 3 (Requirement
Fulfillment, Consistency, No Regressions). We deliberately **left this for you to
decide** rather than pre-empting it. If you choose to drop **Visual & Usability**
and **Minimality** from the auto-evaluator output:
- `Evaluator/step2_prompt.txt` and `step2_prompt_no_step1.txt`: remove those two
  rubric sections, renumber, drop their two lines from the output-format block, and
  change the lone "flag it under Minimality and No Regressions" reference to just
  No Regressions.
- `Evaluator/step2.py`: drop `VISUAL & USABILITY` / `MINIMALITY` from
  `_CRITERION_PATTERN` and the two `criteria_map` entries.
- No change needed: reporting in `CodeGeneration/build_eval_sample.py` and
  `Validation/validate.py` already use only the 3.
- Leave `Testing/Evaluator/inspect_results.py` and the historical
  `RubricEvaluation.json` labels alone — they keep all 5 for displaying human
  ground truth, and only the overall PASS/FAIL drives accuracy.

---

## Task 2 — Grow the MUD screen dataset

**Goal:** more screens in `Datasets/MUD_GenreUI/`, each with reconstructed HTML and
revision tasks. The pipeline (`MUD_Dataset_Utils/`) is incremental and resume-safe.

1. Drop new `{id}.png` originals into `Datasets/MUD_GenreUI/images/`.
2. Re-run in order — each step skips ids it has already processed, so only the new
   screens are touched:
   `MUD_generate_html.py` → `MUD_screenshot.py` → `MUD_generate_revisions.py`.
3. To publish: add the new screens' metadata rows to `results_final_100.csv` (the
   generation steps don't read it, but `MUD_upload_hf.py` iterates it), then run
   `MUD_upload_hf.py`.

### ⚠️ Verify reconstructed HTML in a browser
`MUD_generate_html.py` rebuilds each page from its screenshot with an LLM.
Reconstructions are imperfect and sometimes broken (missing sections, mangled
layout, placeholder icons). A broken before-state contaminates every downstream
revision task *and* every evaluation built on it, so **eyeball the new `html/`
(or the rendered `screenshots/`) before using them.**

### More tasks without more screens
`MUD_generate_revisions.py --tasks-per-category N` (default 3) generates N revision
tasks per applicable taxonomy category. Raise it for a denser task set from the
same screens.

### Generator backend
Revision generation defaults to the fine-tuned Vertex AI model — which needs the
GCP transfer above. Without it, run `MUD_generate_revisions.py --backend gemini`
for base-Gemini tasks.

---

## Task 3 — Larger code-generation experiment

**Goal:** run the experiment (`CodeGeneration/`) over more screens. The flow is two
commands — generate, then auto-evaluate. See `CodeGeneration/README.md` for the
full flag set and the result-JSON structure.

```bash
# 1. Generate: N MUD screens × 10 models (+ vision ablation, ~18 variants/screen)
python CodeGeneration/build_dataset.py --screens N        # or --all
# 2. Evaluate every (screen, model) pair from that run
python CodeGeneration/build_eval_sample.py --run CodeGeneration/Results/{run_name}.json
```

Scaling up is literally "bigger `--screens` (or `--all`)" — nothing else changes.

### It will be slow — manage workers vs. rate limits
A run is `screens × ~18 variants × retries`, each a model call. Raise throughput
with `--workers` (default 8) on **both** scripts. But **watch the API rate
limits**: too many concurrent workers across the model providers will start
returning 429s. If errors climb, lower `--workers`.

### API errors are recoverable — just re-run
Both scripts are resume-safe. `build_dataset.py` (without `--force`) skips variants
that already have valid output; `build_eval_sample.py` skips pairs that already
have `eval_result.json`. So a run that hit transient API / rate-limit failures
**just needs re-running to fill the gaps** — it won't redo completed work. To see
what's outstanding, check `Results/{run_name}.json` → `outputs[].status` for
`ERROR`/`INVALID` (raw failures land in `Results/invalid_{run_name}/`).

You can also let full-HTML failures retry with search-and-replace in the same pass:
`--fallback-search-replace` (default 3 retries, `--fallback-retries N`).

---

## Reference — cross-cutting gotchas

### Adding a new model provider → edit `Util/backends.py`
No plugin/config mechanism. If the provider speaks an OpenAI-compatible API, add a
`(base_url, api_key_env)` entry to `_COMPAT_PROVIDERS` (and a `DEFAULTS` entry if it
has a default model) — it then works through the shared `OpenAICompatibleBackend`.
Otherwise subclass `Backend`, implement `generate(prompt, images, max_tokens)`, and
register it in `get_backend()`. Add the `*_API_KEY` to `Util/.env`. (Currently
wired: gemini, vertexai, anthropic, openai + OpenAI-compatible together/deepseek/
groq/openrouter.)

### Re-fine-tuning the revision generator → categories are mandatory
The generator is category-conditioned (taxonomy category + screenshot → task). If
you ever re-fine-tune it (more data, new base model), **every training example must
carry its taxonomy category** — the `label` in
`Datasets/RevisionGeneratorModelDataset/All/Example-NNN/meta.json`. New examples
must be assigned a category with `Taxonomy/RevisionTaxonomy/assign.py` before
building the SFT JSONL; without it the conditioning signal the model was trained on
is missing. (This check used to be automated by a now-deleted script — it's manual
now.)

### Fine-tuning workflow + cost (`FineTuning/`)
- Tuning runs through the **Vertex AI console**, not a script: upload
  `FineTuning/RevisionGenerator/train.jsonl` as the tuning dataset.
- That JSONL references Before screenshots by **GCS URI**, so
  `FineTuning/upload_assets.py --bucket genui-sft` must have populated the bucket +
  `manifest.json` first (currently covers all 80 source folders).
- Cost: `count_tokens.py` reports ≈98K tokens/epoch for the current 127-example
  data. Vertex AI defaults to a **dynamic epoch count** — pin a fixed `epoch_count`
  (the deployed model used 40) to keep spend predictable, and confirm the current
  per-token tuning price on Google's pricing page (the script's default price is a
  placeholder).

### Screenshot rendering caveats (a source of human/auto disagreement)
- The auto-evaluator uses Chromium (Playwright) renders at a **mobile viewport
  (default 375×812)**; screenshots are required for Stage 2.
- `--full-page` captures the full scrollable height; very long screens produce tall
  images that can degrade the evaluator's visual judgment.
- The locally-rendered screenshot can differ slightly (spacing/layout) from what a
  user saw on the live study site — different rendering context. This is a known
  contributor to human↔auto disagreement.

### Auto-evaluator input contract
- Stage 1 needs the **Before→After HTML diff**; `Util/html_diff.py` generates it
  when no cached `html_diff.txt` is present.
- Stage 2 needs **Before/After screenshots** (`Util/screenshot.py`).
