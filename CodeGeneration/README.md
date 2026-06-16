# CodeGeneration/

The **code generation experiment**: given a MUD screen and one designer-style
revision task, can a model implement the change correctly? Each of 10 models
rewrites the screen's HTML, the result is rendered, and the auto-evaluator scores
whether the revision satisfies the task. This measures model capability on the
same revision tasks the rest of the project generates and evaluates.

Two datasets are produced (both under `Datasets/`, documented in
`Datasets/README.md`):

- **`CodeGenerationExperiment/`** — the raw generations (per screen, one folder
  per model variant).
- **`CodeGenEvalSample/`** — the auto-evaluator's verdict for every
  (screen, model) pair.

---

## Pipeline

```
Datasets/MUD_GenreUI/         build_dataset.py        Datasets/
  screens + revision tasks  ───────────────────────►  CodeGenerationExperiment/
                              (sample task, generate,        │
                               render Before/After)          │  build_eval_sample.py
                                                             ▼  (html_diff → step1 → step2)
                                                       Datasets/CodeGenEvalSample/
                                                       + Results/eval_{run}.json
```

| Script | Role |
|---|---|
| `build_dataset.py` | Sample a task per screen, generate each model's revised HTML, render screenshots. Writes `Datasets/CodeGenerationExperiment/` and `Results/{run_name}.json`. |
| `build_eval_sample.py` | Run the two-stage auto-evaluator over a run's outputs. Writes `Datasets/CodeGenEvalSample/` and `Results/eval_{run_name}.json` (per-model accuracy). |
| `inspect_run.py` | Render a run as a Markdown report (task + Before/After screenshots + HTML diff per model) for eyeballing. |
| `generate_full.py` | Full-HTML generation: the model returns the COMPLETE updated document; retried on invalid HTML. The default generation mode. |
| `generate_core.py` | Search-and-replace generation: the model returns `<<<FIND>>>/<<<REPLACE>>>` edit blocks applied verbatim. Used by `--search-replace` and the fallback. |

All read API keys from `Util/.env`. Generation and evaluation are both
network-bound and run across a thread pool (`--workers`); Playwright rendering
stays sequential.

---

## Model registry

Defined in `MODELS` at the top of `build_dataset.py` — `model_key →
(backend, model_id, supports_vision)`. Five "small" and five "large" models:

| Small | Large |
|---|---|
| claude-haiku-4-5 | claude-sonnet-4-5 |
| gemini-2.5-flash | gemini-2.5-pro |
| gpt-4.1-mini | gpt-4.1 |
| deepseek-v3 *(no vision)* | llama-3.3-70b *(no vision)* |
| qwen3.5-9b | qwen3.5-397b |

**Vision ablation (on by default):** every vision-capable model is *also* run
text-only as a `{model_key}-novision` variant, so a run has up to 18 variants.
The vision variants receive the Before screenshot as image input; the `-novision`
variants and the no-vision models see only the HTML. Disable with
`--no-vision-ablation`.

To add/remove a model, edit `MODELS` (and ensure its backend + API key exist —
see `Util/backends.py`).

---

## Building a run

```bash
# Default: 10 screens (seed 0), all 10 models + vision ablation, full-HTML
python CodeGeneration/build_dataset.py

# Larger run
python CodeGeneration/build_dataset.py --screens 50 --seed 0 --workers 12

# Every screen in the dataset
python CodeGeneration/build_dataset.py --all

# Subset of models / specific screens
python CodeGeneration/build_dataset.py --models claude-haiku-4-5 gpt-4.1-mini
python CodeGeneration/build_dataset.py --screen-ids 12356 --force
```

Key flags:

| Flag | Effect |
|---|---|
| `--screens N` / `--all` | Number of screens to sample (random, seeded) / use all. |
| `--seed N` | Sampling seed (default 0) — same seed picks the same screens + tasks. |
| `--screen-ids ID ...` | Build only these screen ids (overrides `--screens`). |
| `--models KEY ...` | Restrict to a subset of the registry. |
| `--no-vision-ablation` | Skip the `-novision` variants. |
| `--workers N` | Parallel generation workers (default 8). |
| `--run-name NAME` | Output run name (default `run_{seed}_{screens}screens`). |
| `--force` | Regenerate even where outputs already exist (otherwise existing variants are skipped). |
| `--search-replace` | Use search-and-replace generation **instead of** full-HTML. Intended as a rerun (without `--force`) to fill in variants that full-HTML left invalid. |
| `--fallback-search-replace` | On a full-HTML build, if a variant fails to produce valid HTML, retry it once with search-and-replace and keep that result if it succeeds. |
| `--fallback-retries N` | Retries for the search-and-replace fallback (default 3). |

A run **without `--force` resumes**: variants that already have an
`index.html` + `screenshot.png` are skipped, so a re-run only fills gaps (useful
after rate-limit/API failures — see below).

Invalid generations (all retries exhausted) are dumped to
`Results/invalid_{run_name}/` for inspection.

---

## Evaluating a run

```bash
python CodeGeneration/build_eval_sample.py \
    --run CodeGeneration/Results/run_0_30screens.json
```

Runs `html_diff → step1 → step2` (the same auto-evaluator used everywhere) on
every (screen, model) pair, copying each into
`Datasets/CodeGenEvalSample/{screen}_{model_key}/` and writing its
`eval_result.json`. The default evaluator model is `gemini-3.1-pro-preview`
(`--backend` / `--model` to change). Already-evaluated pairs are skipped unless
`--force`. The per-model accuracy report prints to the console and is saved to
`Results/eval_{run_name}.json`.

---

## Reading the results

Everything needed to analyse a run is in the two JSON files under `Results/`;
the dataset folders hold the same examples as files.

**`Results/{run_name}.json`** — what was generated:

```jsonc
{
  "run_name": "run_0_30screens",
  "mode": "full_html",            // or "search_replace"
  "fallback_search_replace": false,
  "seed": 0,
  "n_screens": 30,
  "models": ["claude-haiku-4-5", "claude-haiku-4-5-novision", ...],  // all variant keys
  "base_models": ["claude-haiku-4-5", ...],                          // without -novision
  "sampled": [
    {"screen_id": "12356", "category": "...", "task": "..."}         // the task each screen got
  ],
  "outputs": [
    {"screen_id": "12356", "model_key": "claude-haiku-4-5",
     "status": "OK",            // OK | INVALID | ERROR | SKIP
     "n_attempts": 1,
     "method": "full_html",     // full_html | search_replace | search_replace_fallback
     "last_response": "..."}    // raw model text (for failure triage)
  ]
}
```

**`Results/eval_{run_name}.json`** — how it scored:

```jsonc
{
  "eval_model": "gemini-3.1-pro-preview",
  "per_model": {
    "claude-haiku-4-5": {"pass": 23, "fail": 7, "error": 0,
                         "total": 30, "accuracy": 0.7667}   // headline number
  },
  "per_model_criteria": {                                   // PASS/PARTIAL/FAIL split per criterion
    "claude-haiku-4-5": {"requirementFulfillment": {...}, "consistency": {...},
                         "noRegressions": {...}}
  },
  "reported_criteria": ["requirementFulfillment", "consistency", "noRegressions"],
  "examples": [
    {"screen_id": "12356", "model_key": "claude-haiku-4-5",
     "overall": "PASS",
     "criteria": {"requirementFulfillment": "PASS", ...},   // all 5 rubric criteria stored
     "comment": "..."}                                       // evaluator's rationale
  ]
}
```

Notes:
- `accuracy` = `pass / (pass + fail)`; `error` rows (evaluator threw) are excluded
  from the denominator. A generation `status` of `INVALID`/`ERROR` counts as a
  `FAIL` overall (a model that couldn't produce valid HTML failed the task).
- The evaluator stores all 5 rubric criteria per example, but only 3 are reported
  in `per_model_criteria` / the console (Requirement Fulfillment, Consistency, No
  Regressions). See `Evaluator/README.md` for the rubric.

To browse a run visually instead of by JSON:

```bash
python CodeGeneration/inspect_run.py --run CodeGeneration/Results/run_0_30screens.json
# → CodeGeneration/Results/inspect_{run_name}.md  (open in a Markdown preview)
```

---

## Dataset folder layout

`Datasets/CodeGenerationExperiment/{screen_id}/`:

```
Task.txt                 the sampled revision task
category.txt             its taxonomy category
Before/index.html        reconstructed screen HTML (the starting point)
Before/screenshot.png    rendered at 375×812
{model_key}/index.html        the model's revised HTML (present even if invalid)
{model_key}/screenshot.png    rendered After (only when valid HTML was produced)
{model_key}/generation_failed.json   only when all retries failed
```

`Datasets/CodeGenEvalSample/{screen_id}_{model_key}/` adds the evaluator's
working files: `Before/`, `After/`, `html_diff.txt`, `step1_spec.txt`,
`eval_result.json`.
