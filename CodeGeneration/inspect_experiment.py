#!/usr/bin/env python3
"""
Inspect CodeGenerationExperiment results: task, before/after screenshots, and HTML diff per model.

Usage:
    python CodeGeneration/inspect_experiment.py                        # latest run
    python CodeGeneration/inspect_experiment.py --run run_0_10screens
    python CodeGeneration/inspect_experiment.py --output my_review.html
    python CodeGeneration/inspect_experiment.py --screens 12356 17816  # subset of screens
"""

import argparse
import difflib
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_RESULTS_DIR = Path(__file__).parent / "Results"
_DATASET_DIR = _ROOT / "Datasets" / "CodeGenerationExperiment"

# ---------------------------------------------------------------------------
# Diff rendering
# ---------------------------------------------------------------------------

def _html_diff(before_html: Path, after_html: Path) -> str:
    if not before_html.exists():
        return "<em>before HTML missing</em>"
    if not after_html.exists():
        return "<em>after HTML missing — generation failed</em>"
    a = before_html.read_text(encoding="utf-8").splitlines()
    b = after_html.read_text(encoding="utf-8").splitlines()
    diff = list(difflib.unified_diff(a, b, fromfile="before/index.html", tofile="after/index.html", lineterm=""))
    if not diff:
        return "<em>No changes (HTML identical to Before)</em>"
    lines = []
    for line in diff:
        esc = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(f'<span class="d-add">{esc}</span>')
        elif line.startswith("-") and not line.startswith("---"):
            lines.append(f'<span class="d-rem">{esc}</span>')
        elif line.startswith("@@"):
            lines.append(f'<span class="d-hunk">{esc}</span>')
        else:
            lines.append(f'<span class="d-ctx">{esc}</span>')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Screenshot <img> tag — relative path from the output HTML file
# ---------------------------------------------------------------------------

def _img(shot: Path, out_dir: Path, alt: str) -> str:
    if not shot.exists():
        return f'<div class="missing-shot">{alt} missing</div>'
    import os
    rel = os.path.relpath(shot, out_dir)
    return (
        f'<a href="{rel}" target="_blank">'
        f'<img src="{rel}" alt="{alt}" loading="lazy"></a>'
    )


# ---------------------------------------------------------------------------
# Per-model status badge
# ---------------------------------------------------------------------------

_STATUS_CLASS = {
    "OK":       "badge-ok",
    "FALLBACK": "badge-warn",
    "INVALID":  "badge-err",
    "ERROR":    "badge-err",
    "SKIP":     "badge-skip",
}

def _status_badge(status: str) -> str:
    cls = _STATUS_CLASS.get(status, "badge-skip")
    return f'<span class="badge {cls}">{status}</span>'


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

_CSS = """\
*, *::before, *::after { box-sizing: border-box; }
body { font-family: system-ui, sans-serif; font-size: 14px; margin: 0; padding: 16px 24px;
       background: #f5f5f5; color: #111; }
h1   { font-size: 18px; margin: 0 0 24px; }
.screen  { background: #fff; border: 1px solid #ddd; border-radius: 8px;
           margin-bottom: 32px; overflow: hidden; }
.screen-header { background: #f0f0f0; border-bottom: 1px solid #ddd;
                 padding: 12px 16px; }
.screen-header h2 { margin: 0 0 4px; font-size: 15px; }
.screen-header .category { font-size: 12px; color: #555; margin: 0 0 8px; }
.screen-header .task { font-size: 13px; line-height: 1.5;
                        white-space: pre-wrap; background: #fff;
                        border: 1px solid #ddd; border-radius: 4px;
                        padding: 8px 10px; margin: 0; }
.models-grid { display: grid;
               grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
               gap: 1px; background: #ddd; }
.model-card  { background: #fff; padding: 12px; }
.model-name  { font-weight: 600; font-size: 13px; margin-bottom: 6px;
               display: flex; align-items: center; gap: 8px; }
.shots       { display: flex; gap: 8px; margin-bottom: 8px; }
.shot-wrap   { flex: 1; min-width: 0; }
.shot-wrap p { margin: 0 0 3px; font-size: 11px; color: #666; text-align: center; }
.shot-wrap img       { width: 100%; border: 1px solid #ccc; border-radius: 3px;
                        display: block; }
.shot-wrap a         { display: block; }
.missing-shot        { display: flex; align-items: center; justify-content: center;
                        height: 80px; border: 1px dashed #ccc; border-radius: 3px;
                        color: #999; font-size: 12px; text-align: center; padding: 4px; }
details  { margin-top: 4px; }
summary  { cursor: pointer; font-size: 12px; color: #555; user-select: none;
           padding: 3px 0; }
summary:hover { color: #000; }
.diff-wrap { overflow-x: auto; margin-top: 4px; }
.diff-wrap pre { margin: 0; font-size: 11px; line-height: 1.45;
                 background: #fafafa; border: 1px solid #e0e0e0;
                 border-radius: 4px; padding: 8px; white-space: pre; }
.diff-wrap pre span { display: block; }
.d-add  { background: #e6ffec; color: #1a7f37; }
.d-rem  { background: #ffebe9; color: #cf222e; }
.d-hunk { background: #f0f8ff; color: #0969da; }
.d-ctx  { color: #444; }
.badge  { display: inline-block; padding: 1px 7px; border-radius: 10px;
          font-size: 11px; font-weight: 600; }
.badge-ok   { background: #dafbe1; color: #1a7f37; }
.badge-warn { background: #fff8c5; color: #9a6700; }
.badge-err  { background: #ffebe9; color: #cf222e; }
.badge-skip { background: #eee;    color: #666; }
"""

_PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<h1>{title}</h1>
{body}
</body>
</html>
"""


def _render_screen(
    screen_id: str,
    category: str,
    task: str,
    model_keys: list[str],
    status_map: dict[str, str],   # model_key -> status string
    screen_dir: Path,
    out_dir: Path,
) -> str:
    before_shot = screen_dir / "Before" / "screenshot.png"
    before_html = screen_dir / "Before" / "index.html"

    cards_html = []
    for mk in model_keys:
        model_dir  = screen_dir / mk
        after_shot = model_dir / "screenshot.png"
        after_html = model_dir / "index.html"
        status     = status_map.get(mk, "UNKNOWN")

        before_tag = f'<div class="shot-wrap"><p>Before</p>{_img(before_shot, out_dir, "Before")}</div>'
        after_tag  = f'<div class="shot-wrap"><p>After</p>{_img(after_shot, out_dir, "After")}</div>'

        diff_content = _html_diff(before_html, after_html)

        card = f"""\
<div class="model-card">
  <div class="model-name">{mk} {_status_badge(status)}</div>
  <div class="shots">
    {before_tag}
    {after_tag}
  </div>
  <details>
    <summary>HTML diff</summary>
    <div class="diff-wrap"><pre>{diff_content}</pre></div>
  </details>
</div>"""
        cards_html.append(card)

    esc_task     = task.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    esc_category = category.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    return f"""\
<div class="screen" id="screen-{screen_id}">
  <div class="screen-header">
    <h2>Screen {screen_id}</h2>
    <p class="category">{esc_category}</p>
    <pre class="task">{esc_task}</pre>
  </div>
  <div class="models-grid">
    {"".join(cards_html)}
  </div>
</div>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _latest_run() -> Path:
    runs = sorted(
        (p for p in _RESULTS_DIR.glob("*.json") if not p.stem.startswith("invalid_")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not runs:
        sys.exit("No run JSON files found in CodeGeneration/Results/")
    return runs[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect CodeGenerationExperiment results as HTML.")
    parser.add_argument("--run", default=None,
                        help="Run name (stem of Results/*.json). Default: most recently modified.")
    parser.add_argument("--output", default=None,
                        help="Output HTML path. Default: CodeGeneration/<run_name>_review.html")
    parser.add_argument("--screens", nargs="+", metavar="ID",
                        help="Restrict to these screen IDs.")
    args = parser.parse_args()

    run_path = (_RESULTS_DIR / f"{args.run}.json") if args.run else _latest_run()
    if not run_path.exists():
        sys.exit(f"Run file not found: {run_path}")

    run = json.loads(run_path.read_text(encoding="utf-8"))
    run_name   = run["run_name"]
    model_keys = run["models"]
    sampled    = run["sampled"]         # [{screen_id, category, task}]

    # Build status lookup: (screen_id, model_key) -> status
    status_map: dict[tuple[str, str], str] = {}
    for rec in run.get("outputs", []):
        status_map[(rec["screen_id"], rec["model_key"])] = rec["status"]

    if args.screens:
        wanted  = set(args.screens)
        sampled = [s for s in sampled if s["screen_id"] in wanted]
        if not sampled:
            sys.exit(f"None of the requested screen IDs are in this run: {args.screens}")

    out_path = Path(args.output) if args.output else (
        Path(__file__).parent / f"{run_name}_review.html"
    )
    out_dir = out_path.parent.resolve()
    out_path = out_dir / out_path.name

    sections = []
    for entry in sampled:
        sid      = entry["screen_id"]
        category = entry["category"]
        task     = entry["task"]
        sm       = {mk: status_map.get((sid, mk), "UNKNOWN") for mk in model_keys}
        screen_dir = _DATASET_DIR / sid
        if not screen_dir.exists():
            print(f"  [skip] Screen {sid}: directory not found")
            continue
        sections.append(_render_screen(sid, category, task, model_keys, sm, screen_dir, out_dir))
        print(f"  Screen {sid} — {len(model_keys)} model(s)")

    title = f"CodeGeneration Experiment — {run_name}"
    html  = _PAGE_TEMPLATE.format(title=title, css=_CSS, body="\n".join(sections))
    out_path.write_text(html, encoding="utf-8")
    print(f"\nWritten: {out_path.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
