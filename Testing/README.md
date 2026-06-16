# Testing/

Measures the **auto-evaluator's accuracy against human ground truth**. Where
`Evaluator/` *runs* the two-stage rubric evaluator, this directory *scores how
well it agrees with people*: it runs the evaluator over a labelled dataset and
compares its binary PASS/FAIL verdict to the human label in each example's
`RubricEvaluation.json`.

Everything lives under `Testing/Evaluator/`.

| Script | Role |
|---|---|
| `run.py` | Run the evaluator (Stage 2, with Stage 1 by default) over a dataset and compute PASS/FAIL accuracy, macro-F1, per-class precision/recall, and a confusion matrix vs. ground truth. Writes `Results/{run_name}.json`. |
| `inspect_results.py` | Render a results JSON to Markdown for manual review — **wrong predictions first**, each with the task, Step-1 spec, DOM/HTML diff, Before/After screenshots, and a side-by-side human-vs-predicted rubric table. |

```
Results/            current runs (one JSON per model/ablation)
Results/OldResults/ historical/superseded runs, kept for reference
```

---

## Running

```bash
# Default: gemini-3.1-pro-preview (the production evaluator model) on EvaluatorModelDataset
python Testing/Evaluator/run.py --backend gemini

# Ablation: skip Step 1, pass the raw HTML diff straight to Step 2
python Testing/Evaluator/run.py --backend gemini --no-step1

# Resume an interrupted run / rerun only the wrong examples
python Testing/Evaluator/run.py --backend gemini --resume
python Testing/Evaluator/run.py --rerun-failed Testing/Evaluator/Results/gemini-3.1-pro-preview.json

# Inspect a finished run
python Testing/Evaluator/inspect_results.py Testing/Evaluator/Results/gemini-3.1-pro-preview.json > review.md
```

**Default evaluator model.** With `--backend gemini` and no `--model`, the tester
uses **`gemini-3.1-pro-preview`** — deliberately pinned to match
`Evaluator/step2.py` so the test scores the same model production uses. (Without
this pin it would fall through to `get_backend`'s older gemini default,
`gemini-2.5-pro`.) Override with `--model`.

Key flags: `--model` (override), `--dataset PATH` (see below), `--run-name`,
`--no-step1`, `--resume`, `--rerun-failed RESULTS_JSON`.

Ground truth is read from each example's `RubricEvaluation.json`
(`overallEvaluation` for the binary metric; `criteria` for the per-criterion
display in `inspect_results.py`). Only `overall` PASS/FAIL drives accuracy.

---

## Testing on a new dataset

`run.py` defaults to `Datasets/EvaluatorModelDataset/`, but any dataset can be
scored with **`--dataset PATH`** — *provided it is in the same per-example folder
format the tester expects*:

```
{example}/
    Task.txt                    the revision task
    Before/screenshot.png       inputs to Stage 2 (the model sees these two images)
    After/screenshot.png
    step1_spec.txt              Stage 1 code analysis  (used unless --no-step1)
    html_diff.txt               unified Before→After diff  (used with --no-step1)
    RubricEvaluation.json       human ground truth: overallEvaluation + criteria
```

If `step1_spec.txt` / `html_diff.txt` are absent the evaluator falls back to a
placeholder (degraded — it should be precomputed). The
`DatasetBuilder/EvaluatorModel/` scripts (`cache_html_diffs.py`, `fill_step1.py`)
populate those cache files for a freshly assembled dataset.

So to test on a **new** set of labelled data (e.g. derived from a later
validation study), the steps are: assemble it into the folder format above
(Before/After screenshots + `Task.txt` + `RubricEvaluation.json`), precompute the
`html_diff.txt`/`step1_spec.txt` caches, then point `run.py` at it with
`--dataset`.
