"""
Temporary script: recompute summary.avg_scores for existing comparison result files.

Usage:
    python Testing/RevisionGenerator/add_avg_scores.py Results/gemini_vs_finetuned-v1.json
    python Testing/RevisionGenerator/add_avg_scores.py Results/*.json
"""

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT / "Testing" / "RevisionGenerator"))

from compare import _compute_summary


def fix_file(path: Path) -> None:
    data = json.loads(path.read_text())
    run_a      = data["run_a"]
    run_b      = data["run_b"]
    comparisons = data.get("comparisons", [])

    summary = _compute_summary(comparisons, run_a, run_b)
    data["summary"] = summary

    path.write_text(json.dumps(data, indent=2))

    avg = summary.get("avg_scores", {})
    dims = ["Relevance", "Specificity", "Actionability", "Diversity", "overall"]
    print(f"\n{path.name}")
    print(f"  {'Dimension':<16}  {run_a[:14]:>14}  {run_b[:14]:>14}")
    print(f"  {'─'*16}  {'─'*14}  {'─'*14}")
    for dim in dims:
        va = avg.get(run_a, {}).get(dim)
        vb = avg.get(run_b, {}).get(dim)
        sa = f"{va:.3f}" if va is not None else "—"
        sb = f"{vb:.3f}" if vb is not None else "—"
        label = dim if dim != "overall" else "OVERALL"
        print(f"  {label:<16}  {sa:>14}  {sb:>14}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python add_avg_scores.py <results.json> [...]")
    for arg in sys.argv[1:]:
        for p in sorted(Path(".").glob(arg)) or [Path(arg)]:
            fix_file(p)
