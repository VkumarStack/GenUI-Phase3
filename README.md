# GenUI — Phase 3: Automated UI Revision Evaluation

This project automatically evaluates **n → n+1 UI revisions** using vision-language
models (VLMs). Given a before/after UI pair and a revision task, the pipeline
determines whether the task was correctly implemented - replacing the manual review
done by UI designers in earlier phases.

The evaluation uses a two-step approach: the model first reasons about the code to
form a concrete visual expectation, then verifies that expectation against the
rendered screenshots. This outperforms open-ended image comparison on subtle visual
changes (e.g. color, spacing, border radius).

---

## Setup

```bash
conda create -n GenUI python=3.11
conda activate GenUI
pip install -r requirements.txt
playwright install chromium
```

For cloud-based models, create `Evaluation/.env` with the relevant key(s):

```
GOOGLE_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
```

---

## Directory Structure

```
Examples/
    RevisionExamples/   # hand-crafted examples for testing
    CaseStudyExamples/  # examples imported from Phase 2 zips
Evaluation/
    evaluate.py         # main evaluation entry point
    eval_core.py        # prompt building and evaluation pipeline
    backends.py         # LLM backend implementations
    .env                # API keys (not committed)
Util/
    import_case_study.py  # import a Phase 2 zip into CaseStudyExamples/
    screenshot.py         # render HTML examples to screenshots
    diff.py               # generate code diffs for examples
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
        diff.txt
```

---

## Util Scripts

### `import_case_study.py`

Imports a zip exported from Phase 2 of this project into an output directory.
Automatically renders screenshots and generates diffs.

```bash
python Util/import_case_study.py path/to/study.zip --output-dir Examples/CaseStudyExamples
python Util/import_case_study.py path/to/study.zip --output-dir Examples/CaseStudyExamples --viewport 375x812 --full-page
python Util/import_case_study.py path/to/study.zip --output-dir Examples/CaseStudyExamples --dry-run
```

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

---

## Evaluation

```bash
# Evaluate all examples in a directory (Gemini, default)
python Evaluation/evaluate.py --dir Examples/CaseStudyExamples

# Evaluate a single example
python Evaluation/evaluate.py --example Examples/RevisionExamples/Example1

# Use a different backend or model
python Evaluation/evaluate.py --dir Examples/CaseStudyExamples --backend ollama
python Evaluation/evaluate.py --dir Examples/CaseStudyExamples --backend hf --model Qwen/Qwen2.5-VL-7B-Instruct

# Use code diffs instead of full before/after code
python Evaluation/evaluate.py --dir Examples/CaseStudyExamples --diff
```

Supported backends:

| Backend | Default Model | Notes |
|---|---|---|
| `gemini` | `gemini-2.5-pro` | Requires `GOOGLE_API_KEY` in `.env` |
| `anthropic` | `claude-sonnet-4-6` | Requires `ANTHROPIC_API_KEY` in `.env` |
| `ollama` | `qwen2.5vl:7b` | Requires Ollama running locally |
| `hf` | `Qwen/Qwen2.5-VL-7B-Instruct` | Runs locally via HuggingFace; GPU recommended |
