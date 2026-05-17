"""
Phase 2 — consolidate raw per-example labels into a final taxonomy.

Reads raw_labels.json produced by label.py, then sends all task texts and their
raw labels to Gemini in one text-only prompt. Gemini proposes 3–8 broader
buckets, merges synonymous labels, and assigns each example to one or more
buckets (multi-label allowed).

Output:
  RevisionTaxonomy/taxonomy.json  — structured data
  RevisionTaxonomy/taxonomy.md    — human-readable summary

Running:
    python RevisionTaxonomy/consolidate.py
    python RevisionTaxonomy/consolidate.py --input path/to/raw_labels.json
    python RevisionTaxonomy/consolidate.py --model gemini-2.5-flash
"""

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent.parent
load_dotenv(_ROOT / "Util" / ".env")

sys.path.insert(0, str(_ROOT / "Util"))
from backends import GeminiBackend

_RESULTS = Path(__file__).parent / "Results"
_DEFAULT_INPUT = Path(__file__).parent / "raw_labels.json"
_OUTPUT_JSON = _RESULTS / "taxonomy.json"
_OUTPUT_MD = _RESULTS / "taxonomy.md"
_DEFAULT_MODEL = "gemini-2.5-pro"

_CONSOLIDATE_PROMPT = """\
You are a HCI researcher building a taxonomy of UI revision task types.

Below is a list of {n} unique revision tasks collected from a user study. \
Each entry shows the participant's task text and 1–3 preliminary labels \
assigned by a VLM in a prior pass.

Your job:
1. Propose a taxonomy of 3–8 broader, mutually meaningful categories that \
   together cover the full range of revision motivations in this dataset.
2. Assign each example to one or more categories (multi-label is fine; \
   most examples should get 1–2 labels).

Category design guidance:
- Aim for conceptually distinct buckets, not a hierarchy
- Categories should be actionable and meaningful to a UI/UX researcher
- Avoid buckets so broad they lose meaning ("Usability", "Visual") — \
  prefer mid-level names like "Clarify Navigation", "Add Missing Affordance", \
  "Reduce Visual Clutter", "Surface Hidden Functionality"
- Background context: a prior survey found participants mostly described their \
  tasks as "New Features" or "UX/UI Usability Issues" — treat these as the \
  top-level poles you are subdividing, not as valid categories themselves

---
EXAMPLES:
{examples_block}
---

Return your answer as JSON with this exact schema (no markdown fences, no explanation):
{{
  "categories": [
    {{
      "name": "Category Name",
      "description": "One sentence describing what revision tasks belong here."
    }}
  ],
  "assignments": {{
    "EXAMPLE_KEY": ["Category Name", ...]
  }}
}}"""


def _build_examples_block(raw: dict) -> str:
    lines = []
    for key, entry in sorted(raw.items()):
        if entry.get("error"):
            continue
        labels_str = ", ".join(entry["labels"]) if entry["labels"] else "(none)"
        lines.append(f"[{key}]\nTask: {entry['task']}\nPreliminary labels: {labels_str}\n")
    return "\n".join(lines)


def _parse_response(response: str) -> dict:
    text = re.sub(r"```(?:json)?|```", "", response).strip()
    return json.loads(text)


def _render_markdown(taxonomy: dict, raw: dict) -> str:
    lines = ["# Revision Task Taxonomy\n"]

    lines.append(f"**{len(taxonomy['categories'])} categories** across "
                 f"**{len(taxonomy['assignments'])} unique examples**\n")

    # Category summaries with example counts
    lines.append("## Categories\n")
    cat_counts = {c["name"]: 0 for c in taxonomy["categories"]}
    for cats in taxonomy["assignments"].values():
        for c in cats:
            if c in cat_counts:
                cat_counts[c] += 1

    for cat in taxonomy["categories"]:
        name = cat["name"]
        lines.append(f"### {name} ({cat_counts.get(name, 0)} examples)")
        lines.append(f"{cat['description']}\n")

    # Per-example assignments
    lines.append("## Example Assignments\n")
    lines.append("| Example | Task | Categories |")
    lines.append("|---------|------|------------|")
    for key in sorted(taxonomy["assignments"]):
        task = raw.get(key, {}).get("task", "")
        # Truncate long tasks for readability
        task_short = task[:80] + "…" if len(task) > 80 else task
        cats = ", ".join(taxonomy["assignments"][key])
        lines.append(f"| {key} | {task_short} | {cats} |")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Phase 2: consolidate labels into a taxonomy.")
    parser.add_argument("--input", default=str(_DEFAULT_INPUT), metavar="PATH",
                        help=f"Path to raw_labels.json (default: {_DEFAULT_INPUT}).")
    parser.add_argument("--model", default=_DEFAULT_MODEL,
                        help=f"Gemini model to use (default: {_DEFAULT_MODEL}).")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Error: {input_path} not found. Run label.py first.")

    raw: dict = json.loads(input_path.read_text())
    valid = {k: v for k, v in raw.items() if not v.get("error") and v.get("labels")}
    print(f"Loaded {len(raw)} examples ({len(valid)} valid, {len(raw) - len(valid)} errored/empty)")

    examples_block = _build_examples_block(valid)
    prompt = _CONSOLIDATE_PROMPT.format(n=len(valid), examples_block=examples_block)

    backend = GeminiBackend(args.model)
    print(f"Sending {len(valid)} examples to {args.model} for consolidation...")
    response = backend.generate(prompt)

    try:
        taxonomy = _parse_response(response)
    except Exception as e:
        raw_out = Path(__file__).parent / "consolidate_raw_response.txt"
        raw_out.write_text(response)
        raise SystemExit(f"Failed to parse model response: {e}\nRaw response saved to {raw_out}")

    _OUTPUT_JSON.write_text(json.dumps(taxonomy, indent=2))
    print(f"Saved {_OUTPUT_JSON.relative_to(_ROOT)}")

    md = _render_markdown(taxonomy, raw)
    _OUTPUT_MD.write_text(md)
    print(f"Saved {_OUTPUT_MD.relative_to(_ROOT)}")

    print(f"\nTaxonomy ({len(taxonomy['categories'])} categories):")
    for cat in taxonomy["categories"]:
        name = cat["name"]
        count = sum(1 for cats in taxonomy["assignments"].values() if name in cats)
        print(f"  {name} — {count} examples")


if __name__ == "__main__":
    main()
