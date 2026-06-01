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


def _normalize_ws(s: str) -> str:
    """Collapse all runs of whitespace (including newlines) to a single space."""
    return re.sub(r"\s+", " ", s).strip()


def _find_normalized(find: str, html: str) -> tuple[int, int] | None:
    """Locate *find* in *html* using whitespace-normalized comparison.

    Returns (start, end) byte offsets into the original *html*, or None.
    We scan the HTML looking for a span whose normalized form matches the
    normalized find string.  This handles models that change indentation or
    collapse/expand whitespace in the FIND block.
    """
    norm_find  = _normalize_ws(find)
    norm_html  = _normalize_ws(html)
    norm_start = norm_html.find(norm_find)
    if norm_start == -1:
        return None

    # Map the normalized position back to a position in the original HTML.
    # Walk both strings simultaneously, skipping over whitespace runs.
    orig_pos = norm_pos = 0
    find_orig_start = None
    norm_find_end   = norm_start + len(norm_find)

    while orig_pos < len(html) and norm_pos <= norm_start:
        if html[orig_pos].isspace():
            # skip whitespace run in original; it became one space in norm
            while orig_pos < len(html) and html[orig_pos].isspace():
                orig_pos += 1
            norm_pos += 1  # consumed the single space in norm
        else:
            if norm_pos == norm_start:
                find_orig_start = orig_pos
            orig_pos += 1
            norm_pos += 1

    if find_orig_start is None:
        return None

    # Now advance orig_pos by the length of find's non-whitespace content
    # to find the end offset.
    norm_consumed = 0
    scan = find_orig_start
    while scan < len(html) and norm_consumed < len(norm_find):
        if html[scan].isspace():
            while scan < len(html) and html[scan].isspace():
                scan += 1
            norm_consumed += 1  # the single space in norm
        else:
            scan      += 1
            norm_consumed += 1

    return (find_orig_start, scan)


def apply_edits(html: str, blocks: list[dict]) -> tuple[str, int, int]:
    """Apply each search-replace block to *html* in order.

    Matching strategy (tried in order until one succeeds):
      1. Verbatim substring match
      2. Re-indented match (model stripped leading whitespace)
      3. Whitespace-normalized match (model changed spacing/indentation)

    Returns (result_html, n_applied, n_failed).
    """
    result = html
    n_applied = n_failed = 0
    for block in blocks:
        find, replace = block["find"], block["replace"]

        # 1. Verbatim
        if find in result:
            result = result.replace(find, replace, 1)
            n_applied += 1
            continue

        # 2. Re-indented
        reindented = _reindent_find(find, result)
        if reindented and reindented in result:
            result = result.replace(reindented, replace, 1)
            n_applied += 1
            continue

        # 3. Whitespace-normalized
        span = _find_normalized(find, result)
        if span:
            start, end = span
            result = result[:start] + replace + result[end:]
            n_applied += 1
            continue

        n_failed += 1

    return result, n_applied, n_failed


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
# Core generation with retry
# ---------------------------------------------------------------------------

def generate_with_result(
    prompt: str,
    before_code: str,
    backend: "Backend",
    screenshot_bytes: bytes | None = None,
    css_width: int = 375,
    css_height: int = 812,
    max_retries: int = 3,
) -> dict:
    """Call *backend* to apply a UI change described by *prompt* to *before_code*.

    Retries up to *max_retries* times if no edit blocks are found or all blocks
    fail to apply.  Returns a result dict:

        {
            "html":         str,   # resulting HTML (before_code if all attempts failed)
            "success":      bool,  # True if at least one block applied on any attempt
            "used_fallback": bool, # True if the last attempt fell back to full-HTML extraction
            "n_attempts":   int,
            "attempts": [
                {
                    "response":  str,
                    "n_blocks":  int,
                    "n_applied": int,
                    "n_failed":  int,
                },
                ...
            ]
        }
    """
    full_prompt = build_prompt(prompt, before_code, css_width, css_height)
    images      = [screenshot_bytes] if screenshot_bytes else None

    attempts: list[dict] = []
    best_html = before_code
    success   = False

    for _ in range(max(1, max_retries)):
        raw    = backend.generate(full_prompt, images=images)
        blocks = parse_edit_blocks(raw)

        if not blocks:
            attempts.append({"response": raw, "n_blocks": 0, "n_applied": 0, "n_failed": 0})
            continue

        result_html, n_applied, n_failed = apply_edits(before_code, blocks)
        attempts.append({
            "response":  raw,
            "n_blocks":  len(blocks),
            "n_applied": n_applied,
            "n_failed":  n_failed,
        })

        if n_applied > 0:
            best_html = _sanitize_html(result_html)
            success   = True
            break

    used_fallback = False
    if not success and attempts:
        # Last-resort: try full-HTML extraction from the final response
        last_raw = attempts[-1]["response"]
        extracted = extract_html(last_raw)
        if is_complete_html(extracted):
            best_html    = _sanitize_html(extracted)
            used_fallback = True

    return {
        "html":          best_html,
        "success":       success,
        "used_fallback": used_fallback,
        "n_attempts":    len(attempts),
        "attempts":      attempts,
    }


# ---------------------------------------------------------------------------
# Output sanitizer
# ---------------------------------------------------------------------------

_MARKER_RE = re.compile(r"^[ \t]*<<<(?:FIND|REPLACE|END)>>>[ \t]*$", re.MULTILINE)


def _sanitize_html(html: str) -> str:
    """Remove any stray <<<FIND>>>, <<<REPLACE>>>, <<<END>>> lines from *html*.

    These markers should never appear in valid HTML.  They end up there when a
    model embeds malformed or nested edit blocks inside a REPLACE section.
    """
    return _MARKER_RE.sub("", html)


# ---------------------------------------------------------------------------
# Convenience wrapper (backward-compatible)
# ---------------------------------------------------------------------------

def generate_ui_change(
    prompt: str,
    before_code: str,
    backend: "Backend",
    screenshot_bytes: bytes | None = None,
    css_width: int = 375,
    css_height: int = 812,
    max_retries: int = 3,
) -> str:
    """Apply a UI change and return the resulting HTML string.

    Pass *screenshot_bytes* (PNG bytes of the Before screenshot) to enable
    vision conditioning on models that support it.
    """
    return generate_with_result(
        prompt, before_code, backend,
        screenshot_bytes=screenshot_bytes,
        css_width=css_width,
        css_height=css_height,
        max_retries=max_retries,
    )["html"]
