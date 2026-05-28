"""Temporary script: find all EvaluatorModelDataset folders with an empty
html_diff.txt and regenerate their step1_spec.txt."""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT / "Util"))
sys.path.insert(0, str(_ROOT / "Evaluator"))

from dotenv import load_dotenv
load_dotenv(_ROOT / "Util" / ".env")

from backends import get_backend
from step1 import run_one

_DATASET = _ROOT / "Datasets" / "EvaluatorModelDataset"
_DEFAULT_MODEL = "gemini-3.1-pro-preview"

folders = sorted(f for f in _DATASET.iterdir() if f.is_dir())

targets = [
    f for f in folders
    if (f / "html_diff.txt").exists()
    and not (f / "html_diff.txt").read_text(encoding="utf-8").strip()
]

if not targets:
    print("No folders with empty html_diff.txt found.")
    sys.exit(0)

print(f"Found {len(targets)} folder(s) with empty html_diff.txt:")
for f in targets:
    print(f"  {f.name}")
print()

backend = get_backend("gemini", _DEFAULT_MODEL)
done = errors = 0

for i, folder in enumerate(targets, start=1):
    print(f"[{i}/{len(targets)}] {folder.name} ... ", end="", flush=True)
    try:
        result = run_one(folder, backend)
        if "error" in result:
            print(f"SKIP — {result['error']}")
            errors += 1
            continue
        spec = result["code_analysis"]
        (folder / "step1_spec.txt").write_text(spec, encoding="utf-8")
        print(spec.splitlines()[0][:80])
        done += 1
    except Exception as e:
        print(f"ERROR: {e}")
        errors += 1

print(f"\nDone. Written: {done}  Errors: {errors}")
