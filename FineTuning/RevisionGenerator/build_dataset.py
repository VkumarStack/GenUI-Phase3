"""
Build Vertex AI SFT training JSONL for the revision generator model.

Each training example pairs:
  Input  — revision type (category name + description) + Before screenshot (GCS URI)
  Output — the target revision task text

Reads GCS URIs from the shared manifest produced by FineTuning/upload_assets.py.
Resolves the source RawDataset folder for each example via meta.json.

Running:
    python FineTuning/RevisionGenerator/build_dataset.py
    python FineTuning/RevisionGenerator/build_dataset.py \\
        --dataset Datasets/RevisionGeneratorModelDataset/Train \\
        --manifest FineTuning/manifest.json \\
        --output FineTuning/RevisionGenerator/train.jsonl
"""

import argparse
import json
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
_DATASET = _ROOT / "Datasets" / "RevisionGeneratorModelDataset" / "Train"
_MANIFEST = _ROOT / "FineTuning" / "manifest.json"
_OUTPUT = Path(__file__).parent / "train.jsonl"

# Static system instruction: scope + task structure + output format.
# The revision TYPE (category) is injected per-example in the user turn.
_SYSTEM_INSTRUCTION = (
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

    "EACH TASK MUST CONTAIN ALL THREE OF THE FOLLOWING:\n"
    "  (a) Motivation: Why is this change needed? Explain what is currently "
    "suboptimal or what goal the revision serves, framed in terms of the revision "
    "type specified in the prompt.\n"
    "  (b) Precise component identification: Name the specific component(s) to be "
    "changed and describe their current appearance and location in the screenshot "
    "(e.g. 'the dark blue primary action button labeled \"Continue\" in the bottom "
    "center of the screen').\n"
    "  (c) Unambiguous change description: Describe exactly what the component "
    "should look like or do after the revision. Leave no room for interpretation — "
    "if a color is changing, say which color; if text is moving, say where it "
    "should end up.\n\n"

    "OUTPUT FORMAT:\n"
    "Return a single revision task as a short, self-contained paragraph of two to "
    "four sentences. No preamble, headers, or closing remarks — only the task text."
)


def load_example(example_dir: Path, manifest: dict) -> dict | None:
    """Load one example. Returns None if any required file is missing."""
    name = example_dir.name

    meta_path   = example_dir / "meta.json"
    prompt_path = example_dir / "prompt.txt"
    task_path   = example_dir / "task.txt"

    for p in [meta_path, prompt_path, task_path]:
        if not p.exists():
            print(f"  [SKIP] {name}: missing {p.name}")
            return None

    meta = json.loads(meta_path.read_text())
    source = meta.get("source_folder") or meta.get("source")
    if not source:
        print(f"  [SKIP] {name}: meta.json missing 'source_folder'")
        return None

    if source not in manifest:
        print(f"  [SKIP] {name}: source '{source}' not in manifest — run upload_assets.py")
        return None

    uris = manifest[source]
    if "before" not in uris:
        print(f"  [SKIP] {name}: manifest missing 'before' URI for {source}")
        return None

    # prompt.txt format: "Category: <name>\nDescription: <desc>"
    prompt_lines = prompt_path.read_text().strip().splitlines()
    category_name = prompt_lines[0].removeprefix("Category:").strip() if prompt_lines else ""
    category_desc = prompt_lines[1].removeprefix("Description:").strip() if len(prompt_lines) > 1 else ""

    return {
        "name":          name,
        "category_name": category_name,
        "category_desc": category_desc,
        "task":          task_path.read_text().strip(),
        "before_uri":    uris["before"],
    }


def build_training_example(ex: dict) -> dict:
    """Format one example in the Vertex AI SFT GenerateContent format."""
    user_parts = [
        {
            "text": (
                f"REVISION TYPE — your task must belong to this category:\n"
                f"  {ex['category_name']}: {ex['category_desc']}\n\n"
                f"Generate the revision task for the UI shown in the screenshot."
            )
        },
        {"fileData": {"fileUri": ex["before_uri"], "mimeType": "image/png"}},
    ]
    return {
        "systemInstruction": {"parts": [{"text": _SYSTEM_INSTRUCTION}]},
        "contents": [
            {"role": "user",  "parts": user_parts},
            {"role": "model", "parts": [{"text": ex["task"]}]},
        ],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Build Vertex AI SFT JSONL for the revision generator model."
    )
    parser.add_argument("--dataset",  default=str(_DATASET),  metavar="PATH",
                        help=f"RevisionGeneratorModelDataset/Train directory (default: {_DATASET}).")
    parser.add_argument("--manifest", default=str(_MANIFEST), metavar="PATH",
                        help=f"GCS URI manifest from upload_assets.py (default: {_MANIFEST}).")
    parser.add_argument("--output",   default=str(_OUTPUT),   metavar="PATH",
                        help=f"Output JSONL path (default: {_OUTPUT}).")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    example_dirs = sorted(d for d in Path(args.dataset).iterdir() if d.is_dir())

    records = []
    for example_dir in example_dirs:
        ex = load_example(example_dir, manifest)
        if ex is None:
            continue
        records.append(build_training_example(ex))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")

    print(f"\nWrote {len(records)} training example(s) to {output_path}")


if __name__ == "__main__":
    main()
