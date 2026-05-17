"""
Phase 3 — consolidate raw labels into final pass and fail taxonomies.

Reads pass_raw_labels.json and fail_raw_labels.json, sends all labels + reasons
to Gemini in separate text-only calls (one per taxonomy), and asks it to propose
2–4 broader buckets and assign each entry.

Outputs:
  EvaluationTaxonomy/pass_taxonomy.json
  EvaluationTaxonomy/fail_taxonomy.json
  EvaluationTaxonomy/taxonomy.md       — human-readable summary of both

Writes back to Datasets/RawDataset/:
  <folder>/Pass_Taxonomy.txt   (for PASS and PARTIAL entries)
  <folder>/Fail_Taxonomy.txt   (for FAIL and PARTIAL entries)

Running:
    python EvaluationTaxonomy/consolidate.py
    python EvaluationTaxonomy/consolidate.py --model gemini-2.5-flash
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
_PASS_LABELS = Path(__file__).parent / "pass_raw_labels.json"
_FAIL_LABELS = Path(__file__).parent / "fail_raw_labels.json"
_PASS_TAXONOMY = _RESULTS / "pass_taxonomy.json"
_FAIL_TAXONOMY = _RESULTS / "fail_taxonomy.json"
_TAXONOMY_MD = _RESULTS / "taxonomy.md"
_DATASET = _ROOT / "Datasets" / "RawDataset"
_DEFAULT_MODEL = "gemini-2.5-pro"

_CONSOLIDATE_PROMPT = """\
You are a HCI researcher building a taxonomy of {reason_type} reasons from a UI revision study.

Below are {n} expert evaluations. Each entry shows:
- The revision task
- The expert's {reason_type_lower} reason (why the revision {verdict_verb})
- 1–2 preliminary labels assigned in a prior pass

Your job:
1. Propose a taxonomy of 2–4 broader, meaningful categories that cover the full
   range of {reason_type_lower} reasons in this dataset.
2. Assign each entry to one or more categories (multi-label is fine if truly
   applicable, but most entries should get exactly 1 label).

Category design guidance:
- Aim for categories that are conceptually distinct and useful for research analysis
- Cover both the richer justifications AND the thin ones (e.g. "Did exactly what I said"
  is a real signal — it belongs somewhere meaningful, not discarded)
- 2–4 buckets total; err toward fewer, broader buckets given the data quality
{extra_guidance}
---
ENTRIES:
{entries_block}
---

Return JSON only (no markdown fences, no explanation):
{{
  "categories": [
    {{"name": "Category Name", "description": "One sentence."}}
  ],
  "assignments": {{
    "FOLDER_NAME": ["Category Name"]
  }}
}}"""

_PASS_EXTRA = """\
- Background: expert designers evaluated AI-generated UI revisions as PASS, FAIL, or PARTIAL PASS.
  Pass reasons explain what the AI did well. Common themes seen in the data include faithful
  execution of the task, good visual judgment, and preservation of design consistency.
"""

_FAIL_EXTRA = """\
- Background: expert designers evaluated AI-generated UI revisions as PASS, FAIL, or PARTIAL PASS.
  Fail reasons explain what went wrong. Common themes include no change made, incomplete coverage
  of the task, design pattern violations, and unintended visual regressions.
"""


def _build_entries_block(raw: dict) -> str:
    lines = []
    for key, entry in sorted(raw.items()):
        if entry.get("error") or not entry.get("labels"):
            continue
        labels_str = ", ".join(entry["labels"])
        task_short = entry.get("task", "")[:100]
        lines.append(
            f"[{key}]\n"
            f"Task: {task_short}\n"
            f"Reason: {entry['reason']}\n"
            f"Preliminary labels: {labels_str}\n"
        )
    return "\n".join(lines)


def _parse_response(response: str) -> dict:
    text = re.sub(r"```(?:json)?|```", "", response).strip()
    return json.loads(text)


def _consolidate(raw: dict, reason_type: str, verdict_verb: str,
                 extra: str, backend: GeminiBackend) -> dict:
    valid = {k: v for k, v in raw.items() if not v.get("error") and v.get("labels")}
    entries_block = _build_entries_block(valid)
    prompt = _CONSOLIDATE_PROMPT.format(
        reason_type=reason_type,
        reason_type_lower=reason_type.lower(),
        verdict_verb=verdict_verb,
        n=len(valid),
        extra_guidance=extra,
        entries_block=entries_block,
    )
    print(f"  Sending {len(valid)} entries to model...")
    response = backend.generate(prompt)
    return _parse_response(response)


def _render_markdown(pass_tax: dict, fail_tax: dict) -> str:
    lines = ["# Evaluation Reason Taxonomy\n"]

    for label, tax in [("Pass", pass_tax), ("Fail", fail_tax)]:
        counts = {c["name"]: 0 for c in tax["categories"]}
        for cats in tax["assignments"].values():
            for c in cats:
                if c in counts:
                    counts[c] += 1

        lines.append(f"## {label} Taxonomy ({len(tax['categories'])} categories)\n")
        for cat in tax["categories"]:
            name = cat["name"]
            lines.append(f"### {name} ({counts.get(name, 0)} entries)")
            lines.append(f"{cat['description']}\n")

    return "\n".join(lines) + "\n"


def _write_back(pass_tax: dict, fail_tax: dict) -> tuple[int, int]:
    written_pass = written_fail = 0
    for folder_name, cats in pass_tax["assignments"].items():
        dest = _DATASET / folder_name / "Pass_Taxonomy.txt"
        if dest.parent.exists():
            dest.write_text("\n".join(cats) + "\n")
            written_pass += 1
    for folder_name, cats in fail_tax["assignments"].items():
        dest = _DATASET / folder_name / "Fail_Taxonomy.txt"
        if dest.parent.exists():
            dest.write_text("\n".join(cats) + "\n")
            written_fail += 1
    return written_pass, written_fail


def main():
    parser = argparse.ArgumentParser(description="Phase 3: consolidate labels into taxonomies.")
    parser.add_argument("--model", default=_DEFAULT_MODEL,
                        help=f"Gemini model (default: {_DEFAULT_MODEL}).")
    args = parser.parse_args()

    for f in (_PASS_LABELS, _FAIL_LABELS):
        if not f.exists():
            raise SystemExit(f"{f.name} not found — run label.py first.")

    pass_raw = json.loads(_PASS_LABELS.read_text())
    fail_raw = json.loads(_FAIL_LABELS.read_text())

    backend = GeminiBackend(args.model)

    print("Consolidating pass taxonomy...")
    pass_tax = _consolidate(pass_raw, "Pass", "succeeded", _PASS_EXTRA, backend)
    _PASS_TAXONOMY.write_text(json.dumps(pass_tax, indent=2))
    print(f"  Saved {_PASS_TAXONOMY.relative_to(_ROOT)}")

    print("Consolidating fail taxonomy...")
    fail_tax = _consolidate(fail_raw, "Fail", "failed", _FAIL_EXTRA, backend)
    _FAIL_TAXONOMY.write_text(json.dumps(fail_tax, indent=2))
    print(f"  Saved {_FAIL_TAXONOMY.relative_to(_ROOT)}")

    _TAXONOMY_MD.write_text(_render_markdown(pass_tax, fail_tax))
    print(f"  Saved {_TAXONOMY_MD.relative_to(_ROOT)}")

    written_pass, written_fail = _write_back(pass_tax, fail_tax)
    print(f"\nWrote Pass_Taxonomy.txt to {written_pass} folders.")
    print(f"Wrote Fail_Taxonomy.txt  to {written_fail} folders.")

    print("\nPass categories:")
    for cat in pass_tax["categories"]:
        n = sum(1 for c in pass_tax["assignments"].values() if cat["name"] in c)
        print(f"  {cat['name']} — {n} entries")
    print("\nFail categories:")
    for cat in fail_tax["categories"]:
        n = sum(1 for c in fail_tax["assignments"].values() if cat["name"] in c)
        print(f"  {cat['name']} — {n} entries")


if __name__ == "__main__":
    main()
