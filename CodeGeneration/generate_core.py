"""
Core logic for applying LLM-generated UI changes to an HTML file.

The model is asked to return edit blocks in the format:
    <<<FIND>>>
    exact original text
    <<<REPLACE>>>
    replacement text
    <<<END>>>

Each block is applied to the source HTML as a verbatim search-and-replace.
If no edit blocks are found the raw response is treated as a full HTML document
and returned directly (fallback path).

Ported from genui-plusplus/server/core.js.
"""

import re
import warnings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backends import Backend

# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE = """\
You are a senior UI engineer applying a targeted fix to a mobile HTML UI.

Your task: implement the designer-reported issue below as a minimal, surgical set of edits.

Designer issue:
{prompt}

Rules:
- Output ONLY edit blocks in the exact format shown below. No prose, no full HTML, nothing else.
- Each block contains the verbatim substring to find and what to replace it with.
- Copy ALL attribute values (src, href, class, style, etc.) character-for-character from the original — never retype or paraphrase them.
- Make as few blocks as needed. Do not reformat or restructure code outside the changed region.
- The FIND text must appear verbatim in the Before HTML or the edit will silently fail.
- If you need to change multiple disjoint regions, emit one block per region.
- Target phone viewport: {css_width}x{css_height} CSS px.

Block format:
<<<FIND>>>
exact original text (may be multiline)
<<<REPLACE>>>
replacement text
<<<END>>>

Before HTML:
{before_code}"""


def build_prompt(
    prompt: str,
    before_code: str,
    css_width: int = 375,
    css_height: int = 812,
) -> str:
    return _PROMPT_TEMPLATE.format(
        prompt=prompt or "(no issue provided)",
        before_code=before_code or "(not provided)",
        css_width=css_width,
        css_height=css_height,
    )


# ---------------------------------------------------------------------------
# Edit-block parsing
# ---------------------------------------------------------------------------

_BLOCK_RE = re.compile(
    r"<<<FIND>>>\r?\n([\s\S]*?)\r?\n<<<REPLACE>>>\r?\n([\s\S]*?)\r?\n<<<END>>>",
)


def parse_edit_blocks(raw: str) -> list[dict]:
    """Return a list of {'find': str, 'replace': str} dicts parsed from *raw*."""
    return [
        {"find": m.group(1), "replace": m.group(2)}
        for m in _BLOCK_RE.finditer(raw)
    ]


# ---------------------------------------------------------------------------
# Edit application
# ---------------------------------------------------------------------------

def _reindent_find(find: str, html: str) -> str | None:
    """If the model stripped leading indentation from *find*, re-add it to match *html*.

    Returns the re-indented string, or None if re-indentation is unnecessary
    or impossible.
    """
    lines = find.split("\n")
    if len(lines) < 2:
        return None

    first_nonempty = next((l for l in lines if l.strip()), None)
    if not first_nonempty:
        return None

    idx = html.find(first_nonempty.strip())
    if idx == -1:
        return None

    line_start = idx
    while line_start > 0 and html[line_start - 1] != "\n":
        line_start -= 1

    indent_match = re.match(r"^[\t ]*", html[line_start:idx])
    indent = indent_match.group(0) if indent_match else ""
    if not indent:
        return None

    reindented = "\n".join(
        (indent + l.lstrip()) if l.strip() else l
        for l in lines
    )
    return None if reindented == find else reindented


def apply_edits(html: str, blocks: list[dict]) -> str:
    """Apply each search-replace block to *html* in order and return the result."""
    result = html
    for block in blocks:
        find, replace = block["find"], block["replace"]
        if find in result:
            result = result.replace(find, replace, 1)
        else:
            reindented = _reindent_find(find, result)
            if reindented and reindented in result:
                warnings.warn(
                    f"[apply_edits] matched after re-indent: {find[:60]!r}",
                    stacklevel=2,
                )
                result = result.replace(reindented, replace, 1)
            else:
                warnings.warn(
                    f"[apply_edits] no match for: {find[:80]!r}",
                    stacklevel=2,
                )
    return result


# ---------------------------------------------------------------------------
# HTML extraction (fallback)
# ---------------------------------------------------------------------------

def extract_html(text: str) -> str:
    """Extract an HTML document from *text* when no edit blocks were produced."""
    if not text:
        return ""

    fenced = re.search(r"```html\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()

    lower = text.lower()
    doctype_start = lower.find("<!doctype html")
    if doctype_start != -1:
        return text[doctype_start:].strip()

    html_start = text.find("<html")
    if html_start != -1:
        return text[html_start:].strip()

    return text.strip()


def is_complete_html(html: str) -> bool:
    h = (html or "").lower()
    return "</body>" in h and "</html>" in h


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def generate_ui_change(
    prompt: str,
    before_code: str,
    backend: "Backend",
    css_width: int = 375,
    css_height: int = 812,
) -> str:
    """Call *backend* to apply a UI change described by *prompt* to *before_code*.

    Returns the modified HTML string.  If the model emits edit blocks they are
    applied surgically; otherwise the full response is treated as replacement HTML.
    """
    full_prompt = build_prompt(prompt, before_code, css_width, css_height)
    raw = backend.generate(full_prompt)

    blocks = parse_edit_blocks(raw)
    if blocks:
        return apply_edits(before_code, blocks)

    warnings.warn(
        "[generate_ui_change] no edit blocks found — falling back to full-HTML extraction",
        stacklevel=2,
    )
    return extract_html(raw)
