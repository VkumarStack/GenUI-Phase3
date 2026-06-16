# Validation/

Measures how well the **auto-evaluator agrees with real user-study participants**.
Where `Testing/` scores the evaluator against a fixed labelled dataset, this
directory scores it against the live gradings collected in the **iteration-3
validation study**: for every (screen, model) a participant graded, it runs the
auto-evaluator and compares verdicts on the overall PASS/FAIL plus three rubric
criteria (Requirement Fulfillment, Consistency, No Regressions).

| Script | Role |
|---|---|
| `build_validation_data.py` | Build `Datasets/ValidationData/` from the study's screen HTML — renders Before + each model's After at 375×812 so all screenshots come from the same engine. Mirrors the `CodeGenerationExperiment` folder layout. |
| `auto_evaluator.py` | Run the two-stage auto-evaluator on one `ValidationData/{screen}/{model}` pair, caching `html_diff.txt` / `step1_spec.txt` / `auto_eval.json` in place. (Imported by `validate.py`; not a CLI.) |
| `validate.py` | Read human gradings from the study CSV, run the auto-evaluator on each graded pair, and report human↔auto agreement (overall + per-criterion, with confusion matrices and a disagreement list). Writes `Results/validation_{tag}.json`. |

The three study providers map to model folders:
`claude → claude-haiku-4-5`, `gemini → gemini-2.5-flash`, `openai → gpt-4.1-mini`.

---

## Inputs

Two pieces, both from the user-study system (a **separate Supabase project**):

1. **`iteration3_case_evaluations_rows.csv`** — the per-case human gradings,
   exported from Supabase. Columns used: `participant_id`, `screen_id`,
   `prompt_text`, `provider_rubrics` (a JSON blob of each provider's
   `overallEvaluation` + `criteria`).
2. **The screen HTML** (`iteration-3-screens/cge/{screen_id}/`: before HTML +
   each provider's generated output + `revision_prompt.txt`) — the source
   `build_validation_data.py` renders into `Datasets/ValidationData/`.

---

## Running

```bash
# 1. Build the rendered dataset from the study screens
python Validation/build_validation_data.py            # --force to re-render

# 2. Score auto-evaluator vs. human gradings (default: the primary participant)
python Validation/validate.py
python Validation/validate.py --participants p_a3c3baaa-... p_fd383f2e-...   # several at once
python Validation/validate.py --force --workers 8
```

The auto-evaluator defaults to `gemini-3.1-pro-preview` (`--eval-backend` /
`--eval-model` to change). Auto-evaluations are cached per pair under
`ValidationData/`, so re-runs only recompute with `--force`.

**Participant selection matters.** `validate.py` only scores the participant IDs
in `--participants` (default: the single primary participant
`p_a3c3baaa-...`). The CSV contains several participants with very different
grading volumes, so *which* IDs you include determines what's measured — choose
deliberately. A grading is silently excluded when its `prompt_text` no longer
matches the screen's `Task.txt` (`task_mismatch`); the run prints how many were
dropped.

---

## Results

`Results/validation_{tag}.json` holds the agreement metrics and per-record
human/auto verdicts. `tag` is built from the first 8 chars of each participant id
(e.g. `validation_a3c3baaa.json`).
