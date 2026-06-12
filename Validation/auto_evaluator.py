"""
Run the two-stage auto-evaluator on a ValidationData (screen, model) pair and
cache the result in place.

The screen layout is:
    Datasets/ValidationData/{screen_id}/
        Task.txt
        Before/index.html, Before/screenshot.png
        {model_key}/index.html, {model_key}/screenshot.png   (the "After")

Caches are written next to the model output so they are reused on later runs:
    {model_key}/html_diff.txt      — unified Before->After HTML diff (Stage 1 input)
    {model_key}/step1_spec.txt     — Stage 1 code analysis
    {model_key}/auto_eval.json     — Stage 2 rubric verdict (the cached result)

step1/step2 expect a folder with the Before/ + After/ convention, so each
evaluation is assembled in a throwaway temp directory; only the cache artifacts
above are persisted under ValidationData.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "Util"))
sys.path.insert(0, str(_ROOT / "Evaluator"))

from html_diff import html_diff as compute_html_diff
from step1 import run_one as step1_run_one
from step2 import _run_one as step2_run_one

_DATA = _ROOT / "Datasets" / "ValidationData"


def evaluate_screen(screen_id: str, model_key: str, backend, force: bool = False) -> dict:
    """Evaluate one ValidationData (screen, model) pair, caching artifacts in the model folder.

    Returns the cached result dict (or an {"error": ...} dict if inputs are missing).
    """
    screen_dir = _DATA / screen_id
    model_dir  = screen_dir / model_key
    cache_file = model_dir / "auto_eval.json"

    if cache_file.exists() and not force:
        return json.loads(cache_file.read_text(encoding="utf-8"))

    task_file   = screen_dir / "Task.txt"
    before_html = screen_dir / "Before" / "index.html"
    before_shot = screen_dir / "Before" / "screenshot.png"
    after_html  = model_dir / "index.html"
    after_shot  = model_dir / "screenshot.png"

    for p in (task_file, before_html, before_shot, after_html, after_shot):
        if not p.exists():
            return {"screen_id": screen_id, "model_key": model_key,
                    "error": f"missing input: {p.relative_to(_ROOT)}"}

    diff_cache = model_dir / "html_diff.txt"
    spec_cache = model_dir / "step1_spec.txt"

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "Before").mkdir()
        (work / "After").mkdir()
        shutil.copy2(task_file,   work / "Task.txt")
        shutil.copy2(before_html, work / "Before" / "index.html")
        shutil.copy2(before_shot, work / "Before" / "screenshot.png")
        shutil.copy2(after_html,  work / "After" / "index.html")
        shutil.copy2(after_shot,  work / "After" / "screenshot.png")

        # Stage 1 input: unified HTML diff (cached).
        if diff_cache.exists() and not force:
            diff_text = diff_cache.read_text(encoding="utf-8")
        else:
            diff_text = compute_html_diff(before_html, after_html)
            diff_cache.write_text(diff_text, encoding="utf-8")
        (work / "html_diff.txt").write_text(diff_text, encoding="utf-8")

        # Stage 1: code analysis (cached).
        if spec_cache.exists() and not force:
            spec = spec_cache.read_text(encoding="utf-8")
        else:
            s1 = step1_run_one(work, backend)
            if "error" in s1:
                return {"screen_id": screen_id, "model_key": model_key,
                        "error": f"step1: {s1['error']}"}
            spec = s1["code_analysis"]
            spec_cache.write_text(spec, encoding="utf-8")
        (work / "step1_spec.txt").write_text(spec, encoding="utf-8")

        # Stage 2: rubric verdict.
        s2 = step2_run_one(work, backend)

    if "error" in s2:
        return {"screen_id": screen_id, "model_key": model_key, "error": f"step2: {s2['error']}"}

    result = {
        "screen_id":  screen_id,
        "model_key":  model_key,
        "overall":    s2.get("overall"),
        "criteria":   s2.get("criteria"),
        "comment":    s2.get("comment"),
        "response":   s2.get("response"),
        "eval_model": getattr(backend, "model", None),
    }
    cache_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
