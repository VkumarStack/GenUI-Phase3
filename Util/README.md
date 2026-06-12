# Util/

Shared infrastructure used across the project. Three modules, no business logic:

| File | Purpose |
|---|---|
| `backends.py` | Unified interface to every LLM provider. |
| `html_diff.py` | Unified diff between two HTML files (the Stage 1 code-change signal). |
| `screenshot.py` | Render HTML to a screenshot via headless Chromium. |
| `.env` | API keys and Vertex AI config (not committed). |

---

## `backends.py` — LLM provider abstraction

Every provider is wrapped in a `Backend` exposing a single method:

```python
backend.generate(prompt: str, images: list[bytes] | None = None,
                 max_tokens: int | None = None) -> str
```

Get one through the factory:

```python
from backends import get_backend

backend = get_backend("gemini")                          # default model
backend = get_backend("gemini", "gemini-3.1-pro-preview") # explicit model
backend = get_backend("anthropic", "claude-haiku-4-5-20251001")
backend = get_backend("together", "Qwen/Qwen3.5-397B-A17B")
backend = get_backend("vertexai")  # fine-tuned generator via endpoint env var
```

**Wired providers:** `gemini`, `vertexai`, `anthropic`, `openai`, and the
OpenAI-compatible group `together`, `deepseek`, `groq`, `openrouter` (all share
`OpenAICompatibleBackend`, distinguished only by base URL + API-key env var in
`_COMPAT_PROVIDERS`).

### ⚠️ Adding a new provider requires editing this file
There is no config-/plugin-based registration — a new model API must be added in
`backends.py`:

- **OpenAI-compatible API** (most providers): add a `(base_url, api_key_env)`
  entry to `_COMPAT_PROVIDERS`, plus a `DEFAULTS` entry if it has a sensible
  default model. Nothing else is needed.
- **Anything else:** subclass `Backend`, implement `generate(...)`, and add a
  branch to `get_backend()`.
- Add the corresponding `*_API_KEY` to `.env`.

Keep this in mind for the larger Code Generation experiment: extending the model
roster means touching `backends.py` (for the provider) and the model registry in
`CodeGeneration/build_dataset.py` (for the specific model IDs).

---

## `.env` (expected keys)

`.env` lives in this folder and is loaded by every entry point via
`python-dotenv`. Only the keys for providers you actually use are required.

```bash
# Core (the default auto-evaluator runs on Gemini)
GOOGLE_API_KEY=...

# Other proprietary providers
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...

# OpenAI-compatible providers (used by the Code Generation experiment)
TOGETHER_API_KEY=...
DEEPSEEK_API_KEY=...
GROQ_API_KEY=...        # optional
OPENROUTER_API_KEY=...  # optional

# Vertex AI — the fine-tuned revision generator
VERTEXAI_PROJECT=your-gcp-project
VERTEXAI_LOCATION=us-central1
VERTEXAI_GENERATOR_ENDPOINT_ID=...   # endpoint id of the tuned generator
```

The `vertexai` backend additionally needs Application Default Credentials:

```bash
gcloud auth application-default login
```

---

## `html_diff.py` — Before→After HTML diff

The auto-evaluator's **Stage 1 reasons over a unified diff of the raw HTML**
(`difflib.unified_diff`, no rendering). This module produces that diff, and
exists so a diff can be generated on demand whenever a cached `html_diff.txt` is
not already present next to an example.

```bash
# From an example folder with Before/index.html + After/index.html
python Util/html_diff.py --example path/to/example --save   # writes html_diff.txt

# From two arbitrary files
python Util/html_diff.py --before a.html --after b.html
```

Programmatic use:

```python
from html_diff import html_diff
diff_text = html_diff(before_path, after_path)   # -> str
```

---

## `screenshot.py` — render HTML to PNG

The auto-evaluator's **Stage 2 judges rendered screenshots**, so every HTML
(before and after) must be rasterized. Rendering uses headless **Chromium
(Playwright) at a mobile viewport, default 375×812**, matching the MUD-derived
mobile screens.

```bash
python Util/screenshot.py --example path/to/example          # Before/ + After/
python Util/screenshot.py --dir path/to/examples
python Util/screenshot.py --dir path/to/examples --viewport 375x812
python Util/screenshot.py --dir path/to/examples --full-page
```

(Requires `playwright install chromium` once.)

### Rendering caveats — worth knowing
- **Full height by default.** Captures are taken at the viewport height; `--full-page`
  captures the entire scrollable page. For very long screens, full-page renders
  become tall images that can be harder for the evaluator to judge accurately and
  may not reflect what a user sees "above the fold."
- **Render parity.** There can be slight spacing/layout differences between the
  screen a participant interacts with on the user-study site and the screenshot
  rendered here (different rendering contexts). This is one source of
  human/auto-evaluator disagreement and something to keep in mind when comparing
  validation results.
