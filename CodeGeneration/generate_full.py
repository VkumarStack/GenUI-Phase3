"""
Full-HTML code generation for the CodeGeneration experiment.

The model is asked to output the entire updated HTML document (rather than the
search-and-replace edits in generate_core.py). If the returned document does not
parse as a complete HTML file, the call is retried up to max_retries times.
Reuses the read-only `extract_html` helper from generate_core.
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).parent))
from generate_core import extract_html  # read-only reuse

if TYPE_CHECKING:
    from backends import Backend

# Output token budget. Full-HTML generation must emit the entire document, so
# the default per-backend caps (4,096 for Anthropic/OpenAI) are too small and
# truncate longer pages. This raises the ceiling for all providers; DeepSeek
# clamps to its own ~8K maximum, and Gemini stays within its 65K native limit.
_MAX_OUTPUT_TOKENS = 32000


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_FULL_PROMPT = """\
You are a senior UI engineer applying a targeted fix to a mobile HTML UI.

Implement the designer-reported issue below by editing the page and returning the full result.

Designer issue:
{prompt}

Rules:
- Output the COMPLETE, updated HTML document and NOTHING else: no prose, no explanation, no markdown code fences.
- Begin your output at <!DOCTYPE html> (or <html>) and end it at </html>.
- Keep everything not related to the issue exactly as it appears in the original.
- Keep the page a single self-contained file with inline <style>, matching the original structure.
- Target phone viewport: {css_width}x{css_height} CSS px.

Before HTML:
{before_code}"""


def build_full_prompt(
    prompt: str,
    before_code: str,
    css_width: int = 375,
    css_height: int = 812,
) -> str:
    return _FULL_PROMPT.format(
        prompt=prompt or "(no issue provided)",
        before_code=before_code or "(not provided)",
        css_width=css_width,
        css_height=css_height,
    )


# ---------------------------------------------------------------------------
# HTML validity ("does it compile")
# ---------------------------------------------------------------------------

def is_valid_html(html: str) -> bool:
    """A pragmatic completeness check for a self-contained HTML document.

    Browsers are lenient, so "compiles" is interpreted structurally: the output
    must contain an <html> ... </html> wrapper, a closing </body>, and enough
    content that it is not a truncated stub or a refusal/prose response.
    """
    h = (html or "").lower()
    return (
        "<html" in h
        and "</html>" in h
        and "</body>" in h
        and len(html.strip()) > 200
    )


# ---------------------------------------------------------------------------
# Core generation with retry on invalid HTML
# ---------------------------------------------------------------------------

def generate_full_html(
    prompt: str,
    before_code: str,
    backend: "Backend",
    screenshot_bytes: bytes | None = None,
    css_width: int = 375,
    css_height: int = 812,
    max_retries: int = 3,
) -> dict:
    """Ask *backend* to rewrite *before_code* implementing *prompt*.

    Retries up to *max_retries* times whenever the extracted HTML does not
    pass `is_valid_html`. Returns:

        {
            "html":       str,   # most recent extracted HTML (valid if success)
            "success":    bool,  # True if a valid complete document was produced
            "n_attempts": int,
            "attempts": [
                {"response": str, "valid": bool, "length": int},
                ...
            ],
        }

    Pass *screenshot_bytes* (PNG of the Before screenshot) to enable vision
    conditioning on models that support it.
    """
    full_prompt = build_full_prompt(prompt, before_code, css_width, css_height)
    images      = [screenshot_bytes] if screenshot_bytes else None

    attempts: list[dict] = []
    best_html = ""
    success   = False

    for _ in range(max(1, max_retries)):
        raw   = backend.generate(full_prompt, images=images, max_tokens=_MAX_OUTPUT_TOKENS)
        html  = extract_html(raw)
        valid = is_valid_html(html)
        attempts.append({"response": raw, "valid": valid, "length": len(html)})
        best_html = html  # keep the most recent extraction for inspection
        if valid:
            success = True
            break

    return {
        "html":       best_html,
        "success":    success,
        "n_attempts": len(attempts),
        "attempts":   attempts,
    }
