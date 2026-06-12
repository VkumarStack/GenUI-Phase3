# DatasetBuilder/

One-off helpers that **prepared and cleaned up the dataset folder structures** for
the two trained/engineered components — the **revision-generator fine-tuning** data
and the **auto-evaluator prompt-engineering** data. They are not part of the runtime
pipelines.

Only `EvaluatorModel/` remains (the revision-generator helper, which backfilled
taxonomy labels on the now-removed `RawDataset`, was deleted). Its two scripts are
still useful for prepping *new* evaluator examples (e.g., when the peer adds more
human-graded data), since they just populate the per-example artifacts the
evaluator expects.

---

## EvaluatorModel/ — prep `Datasets/EvaluatorModelDataset/`

Each example folder there has `Task.txt`, `Before/{index.html,screenshot.png}`,
`After/{index.html,screenshot.png}`, and `RubricEvaluation.json` (the human label).
These scripts fill the two cached artifacts the auto-evaluator reads:

```bash
# Cache html_diff.txt (Stage 1 input) for every example
python DatasetBuilder/EvaluatorModel/cache_html_diffs.py [--force]

# Fill step1_spec.txt (Stage 1 code analysis) for every example
python DatasetBuilder/EvaluatorModel/fill_step1.py [--force]
```

Both default to `Datasets/EvaluatorModelDataset` and accept `--dataset PATH`.
`fill_step1.py` makes an LLM call per example (default `gemini-3.1-pro-preview`);
`cache_html_diffs.py` is local (no API). Run `cache_html_diffs.py` before
`fill_step1.py`. To prep a freshly collected set of evaluator examples, point both
at that directory.

## Note: re-fine-tuning the revision generator needs taxonomy categories

The revision generator is conditioned on a taxonomy **category** (it maps
*category + screenshot → revision task*). Every training example must therefore
carry its category — in `RevisionGeneratorModelDataset/All/Example-NNN/` this is
the `label` in `meta.json` and the `Category:`/`Description:` lines in `prompt.txt`.
If the peer adds new examples and wants to re-fine-tune, those examples must be
assigned a category first (see `Taxonomy/RevisionTaxonomy/assign.py`) before
building the SFT data — otherwise the conditioning the model was trained on is
missing. (The old `check_missing.py` automated this backfill for `RawDataset`; it
was removed, so category assignment is now a manual step via the Taxonomy tools.)
