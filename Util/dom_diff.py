"""
Semantic DOM diff between Before and After HTML files.

Produces three diff sections:
  1. CSS rule changes      — parsed from <style> blocks, diffed property-by-property
  2. Computed style changes — Playwright-rendered computed styles per element, diffed
  3. DOM structure changes  — body serialized to indented lines, diffed with LCS

Section 2 reflects what a developer sees in DevTools "Computed" tab: the final
resolved value after the full CSS cascade, not just what was declared. This is the
authoritative signal for subtle changes (spacing, font size, colour) that may not
be visible in screenshots.

Running:
    python Util/dom_diff.py --example Datasets/RawDataset/Participant_2_CaseStudy-1.1-CLAUDE
    python Util/dom_diff.py --before path/to/before.html --after path/to/after.html
    python Util/dom_diff.py --example ... --save   # write diff.txt alongside the HTML files
"""

import argparse
import asyncio
import difflib
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# CSS parsing and diffing
# ---------------------------------------------------------------------------

def _parse_css(css_text: str) -> dict[str, dict[str, str]]:
    """Parse CSS text into {selector: {property: value}}. Handles simple rules only."""
    rules: dict[str, dict[str, str]] = {}
    css_text = re.sub(r"/\*.*?\*/", "", css_text, flags=re.DOTALL)
    for m in re.finditer(r"([^{@][^{]*)\{([^}]*)\}", css_text):
        selector = " ".join(m.group(1).split())
        props: dict[str, str] = {}
        for p in re.finditer(r"([\w-]+)\s*:\s*([^;]+)", m.group(2)):
            props[p.group(1).strip()] = p.group(2).strip().rstrip(";")
        if props:
            rules.setdefault(selector, {}).update(props)
    return rules


def _diff_css(before_html: str, after_html: str) -> list[str]:
    """Return diff lines for CSS rule changes between two HTML documents."""
    def extract_css(html: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        return "\n".join(tag.get_text() for tag in soup.find_all("style"))

    before = _parse_css(extract_css(before_html))
    after = _parse_css(extract_css(after_html))

    lines = []
    for sel in sorted(set(before) | set(after)):
        b_props = before.get(sel, {})
        a_props = after.get(sel, {})
        if b_props == a_props:
            continue
        prop_lines = []
        for prop in sorted(set(b_props) | set(a_props)):
            bv, av = b_props.get(prop), a_props.get(prop)
            if bv == av:
                continue
            if bv is None:
                prop_lines.append(f"    + {prop}: {av}")
            elif av is None:
                prop_lines.append(f"    - {prop}: {bv}")
            else:
                prop_lines.append(f"    ~ {prop}: {bv}  →  {av}")
        if prop_lines:
            lines.append(f"  [{sel}]")
            lines.extend(prop_lines)
    return lines


# ---------------------------------------------------------------------------
# Computed style diffing via Playwright
# ---------------------------------------------------------------------------

# Properties to track — mirrors the "Computed" panel in DevTools.
# Covers layout, typography, colour, and appearance; excludes animation
# and low-signal properties to keep output concise.
_COMPUTED_PROPS: list[str] = [
    # Layout / box model
    "display", "position", "top", "right", "bottom", "left", "z-index",
    "width", "height", "min-width", "max-width", "min-height", "max-height",
    "margin-top", "margin-right", "margin-bottom", "margin-left",
    "padding-top", "padding-right", "padding-bottom", "padding-left",
    "box-sizing", "overflow", "overflow-x", "overflow-y", "float", "visibility", "opacity",
    # Flexbox / grid
    "flex-direction", "flex-wrap", "flex-grow", "flex-shrink", "flex-basis",
    "align-items", "align-self", "align-content", "justify-content", "justify-items",
    "gap", "row-gap", "column-gap",
    # Typography
    "font-size", "font-weight", "font-family", "font-style",
    "line-height", "letter-spacing", "word-spacing",
    "text-align", "text-decoration", "text-transform", "text-overflow", "white-space",
    "color",
    # Appearance
    "background-color",
    "border-top-width", "border-right-width", "border-bottom-width", "border-left-width",
    "border-top-color", "border-right-color", "border-bottom-color", "border-left-color",
    "border-top-style", "border-right-style", "border-bottom-style", "border-left-style",
    "border-top-left-radius", "border-top-right-radius",
    "border-bottom-left-radius", "border-bottom-right-radius",
    "box-shadow", "outline", "transform",
]

# ── CSS-rule diff JS ──────────────────────────────────────────────────────────
# Queries elements matching changed CSS selectors.
# Uses class-based paths so element identity is semantically meaningful.
# Returns {classPath: {property: computedValue}}.
_CSS_COMPUTED_JS = """
(data) => {
    const { props, selectors } = data;
    const SKIP = new Set(['SCRIPT','STYLE','HEAD','META','LINK','TITLE']);

    function getClassPath(el) {
        const parts = [];
        let cur = el;
        while (cur && cur.tagName && cur.tagName !== 'HTML') {
            if (cur.tagName === 'BODY') { parts.unshift('body'); break; }
            let part = cur.tagName.toLowerCase();
            if (cur.id) {
                part += '#' + cur.id;
            } else {
                const cls = Array.from(cur.classList).slice(0, 4);
                if (cls.length) part += '.' + cls.join('.');
            }
            if (cur.parentElement) {
                const sib = Array.from(cur.parentElement.children)
                    .filter(s => s.tagName === cur.tagName);
                if (sib.length > 1) part += '[' + sib.indexOf(cur) + ']';
            }
            parts.unshift(part);
            cur = cur.parentElement;
        }
        return parts.length > 0 ? parts.join(' > ') : null;
    }

    const matched = new Set();
    for (const sel of selectors) {
        try {
            document.querySelectorAll(sel).forEach(el => {
                if (!SKIP.has(el.tagName)) matched.add(el);
            });
        } catch(e) {}
    }

    const result = {};
    matched.forEach(el => {
        const path = getClassPath(el);
        if (!path) return;
        const cs = window.getComputedStyle(el);
        const styles = {};
        for (const p of props) styles[p] = cs.getPropertyValue(p).trim();
        result[path] = styles;
    });
    return result;
}
"""

# ── Inline-style diff JS ──────────────────────────────────────────────────────
# Uses position-only paths (tag + sibling index, no classes) so elements can be
# matched across Before/After even when their class list changes alongside the
# inline style (e.g. style="color:red" removed and class="text-gray-700" added).

def _make_position_js(query: str) -> str:
    """Return JS that queries `query` and keys results by position-only paths."""
    return f"""
(props) => {{
    const SKIP = new Set(['SCRIPT','STYLE','HEAD','META','LINK','TITLE']);

    function getPositionPath(el) {{
        const parts = [];
        let cur = el;
        while (cur && cur.tagName && cur.tagName !== 'HTML') {{
            if (cur.tagName === 'BODY') {{ parts.unshift('body'); break; }}
            let part = cur.tagName.toLowerCase();
            if (cur.id) part += '#' + cur.id;   // ids are stable; classes are not
            if (cur.parentElement) {{
                const sib = Array.from(cur.parentElement.children)
                    .filter(s => s.tagName === cur.tagName);
                if (sib.length > 1) part += '[' + sib.indexOf(cur) + ']';
            }}
            parts.unshift(part);
            cur = cur.parentElement;
        }}
        return parts.length > 0 ? parts.join(' > ') : null;
    }}

    const result = {{}};
    document.querySelectorAll({query!r}).forEach(el => {{
        if (SKIP.has(el.tagName)) return;
        const path = getPositionPath(el);
        if (!path) return;
        const cs = window.getComputedStyle(el);
        const styles = {{}};
        for (const p of props) styles[p] = cs.getPropertyValue(p).trim();
        result[path] = styles;
    }});
    return result;
}}
"""

_INLINE_STYLED_JS  = _make_position_js("[style]")  # only elements with inline style
_ALL_POSITIONS_JS  = _make_position_js("*")         # all elements (for cross-lookup)


# ── Playwright helpers ────────────────────────────────────────────────────────

async def _run_page(html_path: Path, js: str, arg) -> dict:
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(html_path.resolve().as_uri())
        await page.wait_for_load_state("networkidle")
        result = await page.evaluate(js, arg)
        await browser.close()
        return result


# ── CSS-rule computed diff ────────────────────────────────────────────────────

def _diff_computed_css(before_path: Path, after_path: Path,
                       changed_selectors: list[str]) -> list[str]:
    """Computed style diff for elements directly matching changed CSS selectors."""
    if not changed_selectors:
        return []

    async def _run():
        return await asyncio.gather(
            _run_page(before_path, _CSS_COMPUTED_JS,
                      {"props": _COMPUTED_PROPS, "selectors": changed_selectors}),
            _run_page(after_path,  _CSS_COMPUTED_JS,
                      {"props": _COMPUTED_PROPS, "selectors": changed_selectors}),
        )

    before, after = asyncio.run(_run())
    return _format_diff(before, after)


# ── Inline-style computed diff ────────────────────────────────────────────────

def _diff_computed_inline(before_path: Path, after_path: Path) -> list[str]:
    """Computed style diff for elements whose inline style= attribute changed.

    Uses position-only paths so elements are matched even when their class list
    changes at the same time as the inline style (a common pattern when swapping
    from an explicit style to a utility class, or vice-versa).

    Strategy:
      1. Query [style] elements in Before and After with position paths.
      2. For paths that appear in Before but not After (style removed), look them
         up in a full all-elements position scan of After.
      3. For paths that appear in After but not Before (style added), look them
         up in a full all-elements position scan of Before.
    """
    async def _run():
        # Step 1: [style] elements from both sides in parallel.
        before_styled, after_styled = await asyncio.gather(
            _run_page(before_path, _INLINE_STYLED_JS, _COMPUTED_PROPS),
            _run_page(after_path,  _INLINE_STYLED_JS, _COMPUTED_PROPS),
        )

        need_after_all = set(before_styled) - set(after_styled)  # style removed
        need_before_all = set(after_styled) - set(before_styled)  # style added

        before_all = after_all = {}

        # Step 2: only launch all-elements scans when cross-lookup is needed.
        if need_after_all and need_before_all:
            before_all, after_all = await asyncio.gather(
                _run_page(before_path, _ALL_POSITIONS_JS, _COMPUTED_PROPS),
                _run_page(after_path,  _ALL_POSITIONS_JS, _COMPUTED_PROPS),
            )
        elif need_after_all:
            after_all = await _run_page(after_path, _ALL_POSITIONS_JS, _COMPUTED_PROPS)
        elif need_before_all:
            before_all = await _run_page(before_path, _ALL_POSITIONS_JS, _COMPUTED_PROPS)

        return before_styled, after_styled, before_all, after_all

    before_styled, after_styled, before_all, after_all = asyncio.run(_run())

    # Build unified before/after maps: prefer styled query, fall back to all-positions.
    all_paths = set(before_styled) | set(after_styled)
    merged_before = {p: before_styled.get(p) or before_all.get(p) for p in all_paths}
    merged_after  = {p: after_styled.get(p)  or after_all.get(p)  for p in all_paths}

    return _format_diff(
        {p: v for p, v in merged_before.items() if v},
        {p: v for p, v in merged_after.items()  if v},
    )


# ── Shared formatter ──────────────────────────────────────────────────────────

def _format_diff(before: dict, after: dict) -> list[str]:
    lines = []
    for path in sorted(set(before) & set(after)):
        b, a = before[path], after[path]
        changed = [(p, b[p], a[p]) for p in _COMPUTED_PROPS if b.get(p) != a.get(p)]
        if not changed:
            continue
        label = " > ".join(path.split(" > ")[-3:])
        lines.append(f"  [{label}]")
        for prop, bv, av in changed:
            lines.append(f"    ~ {prop}: {bv}  →  {av}")
    return lines


# ── Public computed diff entry point ─────────────────────────────────────────

def _diff_computed(before_path: Path, after_path: Path,
                   changed_selectors: list[str],
                   has_inline_changes: bool) -> list[str]:
    lines = _diff_computed_css(before_path, after_path, changed_selectors)
    if has_inline_changes:
        inline_lines = _diff_computed_inline(before_path, after_path)
        # Append; de-duplicate identical label blocks that appear in both.
        existing_labels = {l for l in lines if l.startswith("  [")}
        lines += [l for l in inline_lines if not (l.startswith("  [") and l in existing_labels)]
    return lines


# ---------------------------------------------------------------------------
# DOM serialization and diffing
# ---------------------------------------------------------------------------

_SKIP_TAGS = {"script", "style", "head", "meta", "link", "title"}
_SHOW_ATTRS = {"id", "class", "type", "href", "src", "placeholder", "role",
               "aria-label", "aria-hidden", "disabled", "checked", "value"}


def _serialize_node(node, indent: int = 0) -> list[str]:
    """Recursively serialize a BS4 node to indented lines for diffing."""
    prefix = "  " * indent
    lines = []

    if isinstance(node, NavigableString):
        text = str(node).strip()
        if text:
            lines.append(f'{prefix}"{text[:80]}"')
        return lines

    if not isinstance(node, Tag) or node.name in _SKIP_TAGS:
        return lines

    # Build compact open-tag representation
    parts = [node.name]
    attrs = node.attrs or {}

    if "id" in attrs:
        parts.append(f"#{attrs['id']}")
    if "class" in attrs:
        cls = attrs["class"] if isinstance(attrs["class"], list) else attrs["class"].split()
        parts.append("." + ".".join(cls[:3]))  # first 3 classes max

    # Selected semantic attributes
    for key in sorted(_SHOW_ATTRS - {"id", "class"}):
        if key in attrs:
            val = str(attrs[key])[:50]
            parts.append(f'{key}="{val}"')

    # Inline style (abbreviated)
    if "style" in attrs:
        style = str(attrs["style"])
        style_short = style[:60] + ("…" if len(style) > 60 else "")
        parts.append(f'style="{style_short}"')

    lines.append(f"{prefix}<{' '.join(parts)}>")

    for child in node.children:
        lines.extend(_serialize_node(child, indent + 1))

    return lines


def _serialize_body(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    body = soup.find("body")
    if body is None:
        return []
    lines = []
    for child in body.children:
        lines.extend(_serialize_node(child))
    return lines


def _diff_dom(before_html: str, after_html: str, context: int = 3) -> list[str]:
    """Return unified diff lines for DOM structural changes."""
    before_lines = _serialize_body(before_html)
    after_lines = _serialize_body(after_html)

    raw = list(difflib.unified_diff(
        before_lines, after_lines,
        fromfile="Before", tofile="After",
        lineterm="", n=context,
    ))
    # Skip the file header lines (---, +++)
    return [l for l in raw if not l.startswith("---") and not l.startswith("+++")]


# ---------------------------------------------------------------------------
# Public diff entry point
# ---------------------------------------------------------------------------

def dom_diff(before_path: Path, after_path: Path) -> str:
    """Return a formatted DOM+CSS diff string for the two HTML files."""
    before_html = before_path.read_text(encoding="utf-8", errors="replace")
    after_html  = after_path.read_text(encoding="utf-8", errors="replace")

    css_lines = _diff_css(before_html, after_html)
    dom_lines = _diff_dom(before_html, after_html)

    # Selectors whose CSS rules changed — used to scope the computed diff to
    # directly-targeted elements only (avoids cascaded layout noise).
    changed_selectors = [
        line.strip()[1:-1]
        for line in css_lines
        if line.startswith("  [")
    ]

    # Detect inline style changes in the DOM structural diff so we can run the
    # position-path computed diff for those elements as well.
    has_inline_changes = any(
        "style=" in line
        for line in dom_lines
        if line and line[0] in ("+", "-") and not line.startswith(("---", "+++"))
    )

    try:
        computed_lines = _diff_computed(before_path, after_path,
                                        changed_selectors, has_inline_changes)
    except Exception as e:
        computed_lines = [f"  (unavailable — {e})"]

    no_computed_reason = (
        "  (none)"
        if (changed_selectors or has_inline_changes)
        else "  (none — no CSS rule or inline style changes)"
    )

    sections = [
        "=== CSS Rule Changes ===",
        "\n".join(css_lines) if css_lines else "  (none)",

        "\n=== Computed Style Changes (browser-rendered) ===",
        "\n".join(computed_lines) if computed_lines else no_computed_reason,

        "\n=== DOM Structure Changes ===",
        "\n".join(dom_lines) if dom_lines else "  (none)",
    ]

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Semantic DOM diff between Before/After HTML files.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--example", metavar="PATH",
                       help="Path to an example folder containing Before/ and After/ subdirs.")
    group.add_argument("--before", metavar="PATH",
                       help="Path to the Before HTML file directly.")
    parser.add_argument("--after", metavar="PATH",
                        help="Path to the After HTML file (required when using --before).")
    parser.add_argument("--save", action="store_true",
                        help="Write diff.txt into the example folder alongside the HTML files.")
    args = parser.parse_args()

    if args.example:
        example_dir = Path(args.example)
        before_path = example_dir / "Before" / "index.html"
        after_path = example_dir / "After" / "index.html"
    else:
        before_path = Path(args.before)
        after_path = Path(args.after) if args.after else None
        if after_path is None:
            raise SystemExit("--after is required when using --before")

    for p in (before_path, after_path):
        if not p.exists():
            raise SystemExit(f"File not found: {p}")

    result = dom_diff(before_path, after_path)
    print(result)

    if args.save and args.example:
        out = Path(args.example) / "dom_diff.txt"
        out.write_text(result)
        print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
