"""
Phase 2 — VLM-based labeling of pass and fail reasons.

For each entry in raw_data.json, sends the Before screenshot, After screenshot,
task text, and the expert's reason to Gemini and asks for 1–2 free-text category
labels. The screenshots ground thin reasons ("Did exactly what I said") in what
actually happened visually.

Produces two output files:
  EvaluationTaxonomy/pass_raw_labels.json
  EvaluationTaxonomy/fail_raw_labels.json

Running:
    python EvaluationTaxonomy/label.py                    # both pass + fail
    python EvaluationTaxonomy/label.py --type pass        # only pass reasons
    python EvaluationTaxonomy/label.py --type fail        # only fail reasons
    python EvaluationTaxonomy/label.py --resume           # skip already-labeled
    python EvaluationTaxonomy/label.py --model gemini-2.5-flash
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

_DATASET = _ROOT / "Datasets" / "EvaluatorModelDataset"
_RAW_DATA = Path(__file__).parent / "raw_data.json"
_PASS_LABELS = Path(__file__).parent / "pass_raw_labels.json"
_FAIL_LABELS = Path(__file__).parent / "fail_raw_labels.json"
_DEFAULT_MODEL = "gemini-2.5-pro"

_PASS_PROMPT = """\
You are categorizing why a UI/UX expert considered this revision to be a success (PASS or partial PASS).

The expert's pass reason was:
"{reason}"

Using the task description, the Before screenshot, and the After screenshot as grounding context, \
assign 1–2 short labels that describe the *type* of success this represents — what quality of the \
revision earned the pass.

Granularity guidance:
- Too specific (avoid): restating the task itself
- Too vague (avoid): "Good output", "Correct"
- Good examples: "Faithful task execution", "Sound visual judgment",
  "Design language preserved", "Complete and precise implementation",
  "Appropriate scope — no unnecessary changes"

Return JSON only, no explanation:
{{"labels": ["label1", "label2"]}}"""

_FAIL_PROMPT = """\
You are categorizing why a UI/UX expert considered this revision to be a failure (FAIL or partial FAIL).

The expert's fail reason was:
"{reason}"

Using the task description, the Before screenshot, and the After screenshot as grounding context, \
assign 1–2 short labels that describe the *type* of failure this represents — what specifically \
went wrong.

Granularity guidance:
- Too specific (avoid): restating the specific element that failed
- Too vague (avoid): "Wrong output", "Bad implementation"
- Good examples: "No implementation / no change made", "Incomplete implementation",
  "Design pattern inconsistency", "Unintended visual regression",
  "Misinterpretation of task scope", "Partial coverage — missed instances"

Return JSON only, no explanation:
{{"labels": ["label1", "label2"]}}"""


def _parse_labels(response: str) -> list[str]:
    text = re.sub(r"```(?:json)?|```", "", response).strip()
    return [str(l).strip() for l in json.loads(text)["labels"]]


def _label_entries(
    entries: dict[str, dict],
    reason_key: str,
    prompt_template: str,
    output_file: Path,
    backend: GeminiBackend,
    dataset: Path,
    resume: bool,
) -> None:
    existing: dict = {}
    if resume and output_file.exists():
        existing = json.loads(output_file.read_text())
        skipped = sum(1 for k in entries if k in existing)
        print(f"  Resuming: {skipped} already labeled, {len(entries) - skipped} remaining")

    results = dict(existing)
    n = len(entries)

    for i, (folder_name, entry) in enumerate(sorted(entries.items()), start=1):
        if resume and folder_name in existing:
            continue

        reason = entry.get(reason_key)
        if not reason:
            continue

        folder = dataset / folder_name
        before = folder / "Before" / "screenshot.png"
        after = folder / "After" / "screenshot.png"
        task = (folder / "Task.txt").read_text().strip() if (folder / "Task.txt").exists() else ""

        if not before.exists() or not after.exists():
            print(f"  [{i}/{n}] SKIP {folder_name}: missing screenshot(s)")
            continue

        prompt = prompt_template.format(reason=reason)
        images = [before.read_bytes(), after.read_bytes()]

        print(f"  [{i}/{n}] {folder_name} ... ", end="", flush=True)
        try:
            response = backend.generate(prompt, images=images)
            labels = _parse_labels(response)
            print(labels)
            results[folder_name] = {
                "task": task,
                "verdict": entry["verdict"],
                "reason": reason,
                "labels": labels,
                "raw_response": response,
            }
        except Exception as e:
            print(f"ERROR: {e}")
            results[folder_name] = {
                "task": task,
                "verdict": entry["verdict"],
                "reason": reason,
                "labels": [],
                "raw_response": str(e),
                "error": True,
            }

        output_file.write_text(json.dumps(results, indent=2))

    print(f"  Saved → {output_file.relative_to(_ROOT)}")


def main():
    parser = argparse.ArgumentParser(description="Phase 2: VLM-label pass/fail reasons.")
    parser.add_argument("--type", choices=["pass", "fail", "both"], default="both",
                        help="Which reason type to label (default: both).")
    parser.add_argument("--model", default=_DEFAULT_MODEL,
                        help=f"Gemini model (default: {_DEFAULT_MODEL}).")
    parser.add_argument("--resume", action="store_true",
                        help="Skip entries already present in the output files.")
    parser.add_argument("--dataset", default=str(_DATASET), metavar="PATH")
    args = parser.parse_args()

    if not _RAW_DATA.exists():
        raise SystemExit("raw_data.json not found — run collect.py first.")

    raw: dict = json.loads(_RAW_DATA.read_text())
    dataset = Path(args.dataset)
    backend = GeminiBackend(args.model)

    if args.type in ("pass", "both"):
        pass_entries = {k: v for k, v in raw.items() if v.get("pass_reason")}
        print(f"\nLabeling {len(pass_entries)} pass reasons...")
        _label_entries(pass_entries, "pass_reason", _PASS_PROMPT,
                       _PASS_LABELS, backend, dataset, args.resume)

    if args.type in ("fail", "both"):
        fail_entries = {k: v for k, v in raw.items() if v.get("fail_reason")}
        print(f"\nLabeling {len(fail_entries)} fail reasons...")
        _label_entries(fail_entries, "fail_reason", _FAIL_PROMPT,
                       _FAIL_LABELS, backend, dataset, args.resume)


if __name__ == "__main__":
    main()
