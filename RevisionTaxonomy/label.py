"""
Phase 1 — extract free-text category labels for each unique example.

Each folder in FilteredDataset/ is named Participant_X_CaseStudy-Y.Z-MODEL.
Entries that share the same Participant + CaseStudy prefix represent the same
revision task evaluated against different models; we deduplicate to one
representative per unique task before calling the VLM.

For each unique example the script sends:
  - the Before/screenshot.png
  - the Task.txt text
to Gemini and asks for 1–3 short category labels describing the revision type.

Output: RevisionTaxonomy/raw_labels.json

Running:
    python RevisionTaxonomy/label.py
    python RevisionTaxonomy/label.py --model gemini-2.5-flash   # faster/cheaper
    python RevisionTaxonomy/label.py --dataset path/to/FilteredDataset
"""

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / "Evaluation" / ".env")

sys.path.insert(0, str(_ROOT / "Evaluation"))
from backends import GeminiBackend

_DATASET_DIR = _ROOT / "FilteredDataset"
_OUTPUT_FILE = Path(__file__).parent / "raw_labels.json"
_DEFAULT_MODEL = "gemini-2.5-pro"

_MODEL_SUFFIX = re.compile(r"-(CLAUDE|GEMINI|OPENAI)$")

_LABEL_PROMPT = """\
You are categorizing UI revision tasks for a HCI research study.

A participant was shown a mobile app screenshot and asked to write a revision task \
describing a change they wanted made. Your job is to assign 1–3 short category labels \
that describe *what kind of revision this is at a conceptual level*.

Granularity guidance:
- Too broad (avoid): "New Feature", "UX/UI Usability Issue"
- Too narrow (avoid): restating the specific task itself
- Good examples: "Add missing call-to-action", "Improve visual hierarchy",
  "Reduce information density", "Clarify navigation structure",
  "Surface hidden functionality", "Improve feedback & system status",
  "Strengthen visual consistency"

Revision task:
{task}

Return your answer as JSON with this exact format (no markdown, no explanation):
{{"labels": ["label1", "label2"]}}"""


def _unique_examples(dataset_dir: Path) -> dict[str, Path]:
    """Return {example_key: representative_folder} with one entry per unique task."""
    groups: dict[str, list[Path]] = {}
    for folder in sorted(dataset_dir.iterdir()):
        if not folder.is_dir():
            continue
        key = _MODEL_SUFFIX.sub("", folder.name)
        groups.setdefault(key, []).append(folder)
    # Pick the alphabetically first representative (stable across runs)
    return {key: sorted(folders)[0] for key, folders in groups.items()}


def _parse_labels(response: str) -> list[str]:
    """Extract the labels list from the model's JSON response."""
    # Strip markdown fences if present
    text = re.sub(r"```(?:json)?|```", "", response).strip()
    data = json.loads(text)
    return [str(label).strip() for label in data["labels"]]


def main():
    parser = argparse.ArgumentParser(description="Phase 1: label unique revision examples.")
    parser.add_argument("--dataset", default=str(_DATASET_DIR), metavar="PATH",
                        help=f"Path to FilteredDataset directory (default: {_DATASET_DIR}).")
    parser.add_argument("--model", default=_DEFAULT_MODEL,
                        help=f"Gemini model to use (default: {_DEFAULT_MODEL}).")
    parser.add_argument("--resume", action="store_true",
                        help="Skip examples already present in raw_labels.json.")
    args = parser.parse_args()

    dataset_dir = Path(args.dataset)
    examples = _unique_examples(dataset_dir)
    print(f"Found {len(examples)} unique examples (deduped from {sum(1 for _ in dataset_dir.iterdir() if _.is_dir())} folders)")

    existing: dict = {}
    if args.resume and _OUTPUT_FILE.exists():
        existing = json.loads(_OUTPUT_FILE.read_text())
        print(f"Resuming: {len(existing)} already labeled, {len(examples) - len(existing)} remaining")

    backend = GeminiBackend(args.model)
    results: dict = dict(existing)

    for i, (key, folder) in enumerate(sorted(examples.items()), start=1):
        if args.resume and key in existing:
            continue

        screenshot = folder / "Before" / "screenshot.png"
        task_file = folder / "Task.txt"

        if not screenshot.exists() or not task_file.exists():
            print(f"  [{i}/{len(examples)}] SKIP {key}: missing screenshot or task")
            continue

        task_text = task_file.read_text().strip()
        image_bytes = screenshot.read_bytes()
        prompt = _LABEL_PROMPT.format(task=task_text)

        print(f"  [{i}/{len(examples)}] {key} ... ", end="", flush=True)
        try:
            response = backend.generate(prompt, images=[image_bytes])
            labels = _parse_labels(response)
            print(f"{labels}")
            results[key] = {
                "task": task_text,
                "representative_folder": folder.name,
                "labels": labels,
                "raw_response": response,
            }
        except Exception as e:
            print(f"ERROR: {e}")
            results[key] = {
                "task": task_text,
                "representative_folder": folder.name,
                "labels": [],
                "raw_response": str(e),
                "error": True,
            }

        # Write after each example so progress survives interruptions
        _OUTPUT_FILE.write_text(json.dumps(results, indent=2))

    print(f"\nDone. Results saved to {_OUTPUT_FILE.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
