# GenUI — Automated UI Revision Generation & Evaluation

This project supports two automated pipelines for UI revision research:

1. **Revision Generation** — given a Before screenshot, generates plausible revision tasks using a VLM, conditioned on a revision taxonomy.
2. **Evaluation** — given a Before/After UI pair and a revision task, determines whether the task was correctly implemented using a two-step pipeline: first reasoning about what should change, then verifying against the rendered screenshots.

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
```

---

## Directory Structure

```
Datasets/
    RawDataset/           # labeled expert evaluation data (Before/After + task + verdict)
    EvaluatorModelDataset/
        Train/            # evaluator model training examples
        Test/             # evaluator model test examples
    RevisionGeneratorModelDataset/
        Train/            # revision generator training examples
        Test/             # revision generator test examples
Examples/
    RevisionExamples/     # hand-crafted examples for testing
    CaseStudyExamples/    # examples imported from Phase 2 zips

RevisionGeneration/
    generate.py           # generate revision tasks from Before screenshots
    generate_core.py      # core generation logic

Taxonomy/
    RevisionTaxonomy/
        label.py              # Phase 1: VLM-label each unique revision example
        consolidate.py        # Phase 2: merge labels into final taxonomy
        assign.py             # Assign new examples to existing taxonomy categories
        Results/
            taxonomy.json
            taxonomy.md
    EvaluationTaxonomy/
        collect.py            # parse Output.txt files into raw_data.json
        label.py              # Phase 1: VLM-label pass/fail reasons with before/after context
        consolidate.py        # Phase 2: merge into pass taxonomy + fail taxonomy
        Results/
            pass_taxonomy.json
            fail_taxonomy.json
            taxonomy.md

Evaluator/
    step1.py              # Step 1 core: generate expected-change spec (single example / testing)
    step1_prompt.txt      # editable prompt template for Step 1
    step1_results.json    # cached specs keyed by unique example key
    step2.py              # Step 2: pass/partial/fail verdict from spec + screenshots + DOM diff
    step2_prompt.txt      # editable prompt template for Step 2
    step2_results.json    # verdict output

DatasetBuilder/
    EvaluatorModel/
        cache_dom_diffs.py  # compute and cache dom_diff.txt for all RawDataset examples
        fill_step1.py       # find and fill missing Step 1 specs in Evaluator/step1_results.json
        split.py            # stratified train/test split (group-level, verdict-balanced)
        split_summary.json
    RevisionGeneratorModel/
        split.py            # stratified train/test split for revision generator model
        check_missing.py    # find and label examples missing Taxonomy.txt
        split_summary.json

Util/
    backends.py           # LLM backend implementations (Gemini, VertexAI, Anthropic, OpenAI)
    dom_diff.py           # semantic DOM + CSS diff between Before/After HTML files
    screenshot.py         # render HTML examples to screenshots
    diff.py               # generate unified code diffs for examples
    import_case_study.py  # import a Phase 2 zip into CaseStudyExamples/
    .env                  # API keys (not committed)

DEPRECATED/               # old evaluation approach kept for reference only
```

Each example directory follows this layout:

```
ExampleName/
    Task.txt
    Before/
        index.html
        screenshot.png
    After/
        index.html
        screenshot.png
```

---

## Util Scripts

### `screenshot.py`

Renders HTML files to `screenshot.png` for one example or an entire directory.

```bash
python Util/screenshot.py --example Examples/RevisionExamples/Example1
python Util/screenshot.py --dir Examples/RevisionExamples --viewport 1280x800
python Util/screenshot.py --dir Examples/CaseStudyExamples --viewport 375x812 --full-page
```

### `diff.py`

Generates `After/diff.txt` for one example or an entire directory.

```bash
python Util/diff.py --example Examples/RevisionExamples/Example1
python Util/diff.py --dir Examples/RevisionExamples
```

### `import_case_study.py`

Imports a zip exported from Phase 2 into an output directory. Automatically renders screenshots and generates diffs.

```bash
python Util/import_case_study.py path/to/study.zip --output-dir Examples/CaseStudyExamples
python Util/import_case_study.py path/to/study.zip --output-dir Examples/CaseStudyExamples --viewport 375x812 --full-page
```

---

## Revision Generation

Generates one task per taxonomy category by default (7 tasks per screenshot). Use `--category` to target a single category and `--count` to generate multiple tasks per category.

```bash
# Generate one task per taxonomy category for one example
python RevisionGeneration/generate.py --example Examples/CaseStudyExamples/task-10.1-claude

# Generate for every example in a directory
python RevisionGeneration/generate.py --dir Examples/CaseStudyExamples

# Target a specific taxonomy category
python RevisionGeneration/generate.py --example ... --category "Clarify Function & State"

# Generate multiple tasks per category
python RevisionGeneration/generate.py --example ... --count 3

# Save each task as Task.txt + Category.txt + screenshot.png under GeneratedRevisions/
python RevisionGeneration/generate.py --dir Examples/CaseStudyExamples --save
```

---

## Evaluation Pipeline

### Step 1 — Expected-change specification

Fill missing specs for all RawDataset examples (run before split or step2):

```bash
python DatasetBuilder/EvaluatorModel/fill_step1.py
python DatasetBuilder/EvaluatorModel/fill_step1.py --resume
```

Output: `Evaluator/step1_results.json`

Test a single example:

```bash
python Evaluator/step1.py --example Datasets/RawDataset/Participant_2_CaseStudy-1.1-CLAUDE
```

### Step 2 — Pass / Partial / Fail verdict

```bash
# Run over all Datasets/RawDataset examples
python Evaluator/step2.py

# Single example
python Evaluator/step2.py --example Datasets/RawDataset/Participant_2_CaseStudy-1.1-CLAUDE

# Resume interrupted run
python Evaluator/step2.py --resume
```

Output: `Evaluator/step2_results.json`

---

## Supported Backends

| Backend | Default Model | Notes |
|---|---|---|
| `gemini` | `gemini-2.5-pro` | Requires `GOOGLE_API_KEY` in `Util/.env` |
| `vertexai` | _(endpoint required)_ | Requires `VERTEXAI_PROJECT` + `VERTEXAI_LOCATION`; use for fine-tuned models |
| `anthropic` | `claude-sonnet-4-6` | Requires `ANTHROPIC_API_KEY` in `Util/.env` |
| `openai` | `gpt-4o` | Requires `OPENAI_API_KEY` in `Util/.env` |
