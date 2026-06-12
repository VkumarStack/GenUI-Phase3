# RevisionGeneration/

Generates UI **revision tasks** from a Before screenshot, conditioned on a
taxonomy category. This is the inference side of the fine-tuned revision
generator (taxonomy category + screenshot → revision task).

| File | Purpose |
|---|---|
| `generate_core.py` | The shared prompt + parsing logic (no I/O / CLI). |
| `generate.py` | CLI wrapper over `generate_core` for ad-hoc generation. |

`generate_core.py` is the **single source of truth for the generation prompt**.
`MUD_Dataset_Utils/MUD_generate_revisions.py` (the batch pipeline that builds
`Datasets/MUD_GenreUI/revisions.json`) imports `build_prompt` and `parse_tasks`
from here rather than duplicating them — keep the prompt in this one place.

## `generate_core.py`

```python
from generate_core import build_prompt, parse_tasks, generate_tasks

# High-level: read a screenshot path and return tasks
tasks = generate_tasks(screenshot_path, backend, category, count=1)

# Lower-level pieces (used by the MUD batch run, which already has image bytes):
prompt = build_prompt(category, count)        # count==1 -> single task; >1 -> numbered list
tasks  = parse_tasks(model_response, count)
```

`category` is a dict with `name` + `description` (an entry from
`Taxonomy/RevisionTaxonomy/Results/taxonomy.json`). The prompt enforces a
three-part task (motivation, precise component identification, unambiguous change)
and the n→n+1 scope guideline.

## `generate.py` (CLI)

```bash
# One task per taxonomy category (7) for one example
python RevisionGeneration/generate.py --example path/to/example

# Every example in a directory
python RevisionGeneration/generate.py --dir path/to/examples

# A single category, multiple tasks
python RevisionGeneration/generate.py --example ... --category "Clarify Function & State" --count 3

# Use the fine-tuned revision generator on Vertex AI (reads VERTEXAI_GENERATOR_ENDPOINT_ID)
python RevisionGeneration/generate.py --example ... --backend vertexai

# Save Task.txt + Category.txt + screenshot.png under GeneratedRevisions/
python RevisionGeneration/generate.py --dir ... --save
```

The screenshot is resolved as `<example>/Before/screenshot.png` or
`<example>/screenshot.png`. Default backend is `gemini`; use `--backend vertexai`
for the fine-tuned generator.
