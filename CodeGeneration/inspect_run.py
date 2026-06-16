"""
Render a CodeGenerationExperiment run as a Markdown inspection report.

For each sampled screen, shows the task, and for each model: its status, the
Before/After screenshots, and the HTML diff (the same unified diff the auto-
evaluator's Stage 1 sees) inside a collapsible, default-hidden section.

Usage:
    python CodeGeneration/inspect_run.py \\
        --run CodeGeneration/Results/run_0_30screens.json
    python CodeGeneration/inspect_run.py --run ... --out report.md
"""

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "Util"))
from html_diff import html_diff as compute_html_diff

_SOURCE      = _ROOT / "Datasets" / "CodeGenerationExperiment"
_RESULTS_DIR = Path(__file__).parent / "Results"


def _img(md_dir: Path, path: Path, alt: str) -> str:
    """Return a Markdown image tag with a path relative to the report, or a note."""
    if not path.exists():
        return f"_({alt} unavailable)_"
    rel = os.path.relpath(path, md_dir)
    return f"![{alt}]({rel})"


def _model_section(md_dir: Path, screen_dir: Path, model_key: str,
                   status: str, n_attempts: int) -> str:
    before_html = screen_dir / "Before" / "index.html"
    before_shot = screen_dir / "Before" / "screenshot.png"
    after_html  = screen_dir / model_key / "index.html"
    after_shot  = screen_dir / model_key / "screenshot.png"

    lines = [f"### {model_key} — {status} ({n_attempts} attempt(s))", ""]

    # Before / After screenshots side by side
    lines += [
        "| Before | After |",
        "|:---:|:---:|",
        f"| {_img(md_dir, before_shot, 'Before')} | {_img(md_dir, after_shot, 'After')} |",
        "",
    ]

    # HTML diff (same as Stage 1 of the auto-evaluator) — collapsible, hidden by default
    if before_html.exists() and after_html.exists():
        diff = compute_html_diff(before_html, after_html).strip() or "(no differences)"
    else:
        diff = "(diff unavailable — missing Before or model index.html)"

    lines += [
        "<details><summary>HTML diff (Stage 1 input)</summary>",
        "",
        "```diff",
        diff,
        "```",
        "",
        "</details>",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a CodeGenerationExperiment run as a Markdown report.")
    parser.add_argument("--run", required=True, metavar="PATH",
                        help="Path to a run results JSON from build_dataset.py.")
    parser.add_argument("--out", default=None, metavar="PATH",
                        help="Output Markdown path (default: Results/inspect_{run_name}.md).")
    args = parser.parse_args()

    run_meta = json.loads(Path(args.run).read_text(encoding="utf-8"))
    run_name = run_meta["run_name"]
    sampled  = run_meta["sampled"]
    models   = run_meta["models"]

    # Status per (screen, model) from the run outputs
    status_map = {
        (o["screen_id"], o["model_key"]): (o.get("status", "?"), o.get("n_attempts", 0))
        for o in run_meta.get("outputs", [])
    }

    out_path = Path(args.out) if args.out else _RESULTS_DIR / f"inspect_{run_name}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    md_dir = out_path.parent

    parts = [f"# Inspection: {run_name}", ""]

    for entry in sampled:
        sid        = entry["screen_id"]
        category   = entry.get("category", "")
        task       = entry.get("task", "")
        screen_dir = _SOURCE / sid

        parts += [f"## Screen {sid} — {category}", "", f"**Task:** {task}", ""]

        for model_key in models:
            status, n_attempts = status_map.get((sid, model_key), ("?", 0))
            parts.append(_model_section(md_dir, screen_dir, model_key, status, n_attempts))

    out_path.write_text("\n".join(parts), encoding="utf-8")
    try:
        shown = out_path.relative_to(_ROOT)
    except ValueError:
        shown = out_path
    print(f"Wrote {shown}")


if __name__ == "__main__":
    main()
