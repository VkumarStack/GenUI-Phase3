"""
Core logic for generating UI revision tasks from a Before screenshot.

Revision tasks are conditioned on a specific taxonomy category so each generated
task belongs to a well-defined revision type. The taxonomy is defined in
Taxonomy/RevisionTaxonomy/Results/taxonomy.json.
"""

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backends import Backend

_SYSTEM_BASE = (
    "You are a UI/UX product expert generating revision task specifications for "
    "software engineers. You will be shown a screenshot of a mobile or web UI and "
    "asked to generate a concrete revision task.\n\n"

    "SCOPE GUIDELINES:\n"
    "Each task should be a minor, targeted revision — roughly one incremental step "
    "above the current state of the UI (think n → n+1, not n → n+10). A good task "
    "touches one to three components. Avoid:\n"
    "  • Trivially cosmetic changes (e.g. shifting one element by a pixel).\n"
    "  • Sweeping redesigns that restructure the entire layout or replace multiple "
    "sections of the page at once.\n\n"

    "REVISION TYPE — your task must belong to this category:\n"
    "  {category_name}: {category_description}\n\n"

    "EACH TASK MUST CONTAIN ALL THREE OF THE FOLLOWING:\n"
    "  (a) Motivation: Why is this change needed? Explain what is currently "
    "suboptimal or what goal the revision serves, framed in terms of the revision "
    "type above.\n"
    "  (b) Precise component identification: Name the specific component(s) to be "
    "changed and describe their current appearance and location in the screenshot "
    "(e.g. 'the dark blue primary action button labeled \"Continue\" in the bottom "
    "center of the screen', or 'the row of three icon buttons in the top-right "
    "corner of the navigation bar').\n"
    "  (c) Unambiguous change description: Describe exactly what the component "
    "should look like or do after the revision. Leave no room for interpretation — "
    "if a color is changing, say which color; if text is moving, say where it "
    "should end up.\n\n"

    "EXAMPLE OUTPUT (category: Clarify Function & State):\n"
    "The \"Continue\" button is fully green and active even though no departure "
    "point has been selected yet. This could lead to errors if the user taps "
    "Continue without selecting anything. Set the Continue button to a "
    "disabled/muted state by using a faint green at 20% opacity instead of the "
    "full green.\n\n"
)

_FORMAT_SINGLE = (
    "OUTPUT FORMAT:\n"
    "Return a single revision task as a short, self-contained paragraph of two to "
    "four sentences. No preamble, headers, or closing remarks — only the task text."
)

_FORMAT_MULTI = (
    "OUTPUT FORMAT:\n"
    "Return exactly {count} numbered tasks. Each task is a short, self-contained "
    "paragraph of two to four sentences. Use this format:\n"
    "1. <task text>\n"
    "2. <task text>\n"
    "...\n"
    "Do not include any preamble, section headers, or closing remarks — only the "
    "numbered list."
)


def build_prompt(taxonomy_category: dict, count: int) -> str:
    """Build the revision-generation prompt for a taxonomy category.

    Public so other entry points (e.g. MUD_Dataset_Utils) reuse this exact prompt
    instead of duplicating it. taxonomy_category needs 'name' and 'description';
    count==1 requests a single task, >1 a numbered list.
    """
    base = _SYSTEM_BASE.format(
        category_name=taxonomy_category["name"],
        category_description=taxonomy_category["description"],
    )
    fmt = _FORMAT_SINGLE if count == 1 else _FORMAT_MULTI.format(count=count)
    return base + fmt + "\n\nGenerate the revision task(s) for the UI shown in the screenshot."


def parse_tasks(response_text: str, count: int) -> list[str]:
    """Parse a model response into task strings (single task if count==1, else a numbered list)."""
    if count == 1:
        return [response_text.strip()]
    pattern = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
    splits = pattern.split(response_text)
    return [t.strip() for t in splits if t.strip()]


def generate_tasks(
    screenshot_path: Path,
    backend: "Backend",
    taxonomy_category: dict,
    count: int = 1,
) -> list[str]:
    """Generate revision tasks of a specific taxonomy type for the UI in `screenshot_path`.

    taxonomy_category: dict with 'name' and 'description' keys (from taxonomy.json).
    count: tasks to generate per call (default 1; >1 returns a numbered list).
    """
    prompt = build_prompt(taxonomy_category, count)
    response_text = backend.generate(prompt, images=[screenshot_path.read_bytes()])
    return parse_tasks(response_text, count)
