# Evaluator/

The **auto-evaluator**: given a revision task and a Before→After UI change, decide
whether the revision succeeded. It runs in two stages and outputs a rubric verdict
(five criteria, each PASS / PARTIAL PASS / FAIL) plus a binary **OVERALL** PASS/FAIL
and a short comment.

| File | Purpose |
|---|---|
| `step1.py` / `step1_prompt.txt` | Stage 1 — code analysis over the HTML diff. |
| `step2.py` / `step2_prompt.txt` | Stage 2 — visual rubric verdict from screenshots + Stage 1. |
| `step2_prompt_no_step1.txt` | Stage 2 prompt variant for the `--no-step1` ablation (raw diff, no Stage 1). |

Default model for both stages: **`gemini-3.1-pro-preview`**.

---

## Why two stages

The two stages exist to combine the model's *code* reasoning and its *visual*
reasoning without letting one dominate the other.

**Stage 1 (code analysis)** reads the task, the Before HTML, and the unified
Before→After **HTML diff**, and produces a structured report: which diff hunks
implement the task, which changes look unrelated/risky, a per-requirement
completeness check, and a short list of things to verify visually. Its purpose is
to **condition Stage 2's visual attention** — to point it at *what to look for* —
**not to pre-decide the verdict**. It is deliberately phrased as observations
("the diff shows…"), never conclusions.

The reason this helps: the **code change signal is more reliable than pixels** for
small, hard-to-see edits (a few px of padding, a subtle color or font tweak, a text
correction). For those, the diff is near-ground-truth, so Stage 1 acts as a
**crutch** that lets Stage 2 trust a change happened even when it is invisible at
screenshot resolution. Stage 2 still owns the final call and treats the screenshot
as ground truth for anything actually visible.

**Stage 2 (visual evaluation)** takes the task, the Stage 1 analysis (as
supplementary context), and the Before/After **screenshots**, and assigns the
rubric + overall verdict.

The `--no-step1` ablation skips Stage 1 and feeds the raw HTML diff straight into
Stage 2 (via `step2_prompt_no_step1.txt`); it exists to measure how much the
dedicated code-analysis step contributes.

---

## Running

Stage 1 caches its output as `step1_spec.txt` inside each example folder; Stage 2
reads it. An example folder must contain `Task.txt`, `Before/{index.html,screenshot.png}`,
`After/{index.html,screenshot.png}`, and (ideally) a cached `html_diff.txt`.

```bash
# Stage 1 on a single example (prints the code analysis)
python Evaluator/step1.py --example Datasets/EvaluatorModelDataset/<folder>

# Stage 2 over a dataset (default: Datasets/EvaluatorModelDataset)
python Evaluator/step2.py
python Evaluator/step2.py --example Datasets/EvaluatorModelDataset/<folder>
python Evaluator/step2.py --no-step1     # ablation: raw diff, no Stage 1
python Evaluator/step2.py --resume

# Bulk-fill Stage 1 specs for a dataset (used before evaluation):
python DatasetBuilder/EvaluatorModel/fill_step1.py [--force]
```

To score a dataset against human labels and get accuracy/F1, use
`Testing/Evaluator/run.py` (it calls Stage 2 internally). Other entry points
(`CodeGeneration/.../build_eval_sample.py`, `Validation/auto_evaluator.py`) assemble
the Before/After folder themselves and call the same two stages.

---

## Tuning the evaluator

- **If it hallucinates** (reports changes that aren't real), the lever is **Stage 1**
  (`step1_prompt.txt`). The diff is the reliable anchor — Stage 1 has an explicit
  rule to quote only hunks present in the diff. Tighten that grounding there before
  touching Stage 2.

- **If it is too lenient / too strict**, the lever is **Stage 2** (`step2_prompt.txt`).
  The current bar for an overall PASS is: the revision completes **all major parts**
  of the task (a single minor missing detail can still pass) **and** introduces **no
  major regression** that makes the UI unusable (unreadable text, broken or
  overlapping layout, a removed key element). Shift this by editing the
  "OVERALL VERDICT GUIDANCE" block and the per-criterion FAIL/PARTIAL thresholds.
  Prompt changes here were driven by inspecting wrong cases via
  `Testing/Evaluator/inspect_results.py` — repeat that loop when retuning.

### The rubric is 5 criteria today; dropping 2 is a peer decision
The rubric currently scores five criteria: Requirement Fulfillment, Consistency,
**Visual & Usability**, **Minimality**, and No New Regressions. There has been
discussion of removing **Visual & Usability** and **Minimality** to focus on the
three that matter most for this task (Requirement Fulfillment, Consistency, No New
Regressions) — the experiment/reporting code already only summarizes those three.
This has intentionally **not** been done; if you choose to, edit the two Stage 2
prompts (rubric sections + output format) and the `_CRITERION_PATTERN` / `criteria_map`
in `step2.py`. The overall PASS/FAIL — the only thing the accuracy metrics use — is
unaffected by which criteria are listed.
