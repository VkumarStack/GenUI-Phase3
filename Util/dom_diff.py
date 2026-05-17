"""
Prototype: semantic DOM diff between Before and After HTML files.

Produces two diff sections:
  1. CSS rule changes  — parsed from <style> blocks, diffed property-by-property
  2. DOM structure changes — body serialized to indented lines, diffed with LCS

The combined output is formatted for direct use as LLM evaluator context.

Running:
    python Util/dom_diff.py --example Datasets/RawDataset/Participant_2_CaseStudy-1.1-CLAUDE
    python Util/dom_diff.py --before path/to/before.html --after path/to/after.html
    python Util/dom_diff.py --example ... --save   # write diff.txt alongside the HTML files
"""

import argparse
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
    after_html = after_path.read_text(encoding="utf-8", errors="replace")

    css_lines = _diff_css(before_html, after_html)
    dom_lines = _diff_dom(before_html, after_html)

    sections = []

    sections.append("=== CSS Rule Changes ===")
    sections.append("\n".join(css_lines) if css_lines else "  (none)")

    sections.append("\n=== DOM Structure Changes ===")
    sections.append("\n".join(dom_lines) if dom_lines else "  (none)")

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
