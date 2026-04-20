"""
One-off comparison of two results JSON files.

Outputs:
  <stem_a>_vs_<stem_b>_both_wrong.md   — examples both models got wrong
  <stem_a>_vs_<stem_b>_differed.md     — examples where predictions disagreed

Usage:
    python Util/compare_results.py Results/ensemble.json Results/gemini_finetuned.json
"""

import argparse
import json
from pathlib import Path


def load_by_name(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text())
    return {e["name"]: e for e in data["examples"]}


def render_example_pair(name: str, ea: dict, eb: dict, label_a: str, label_b: str) -> list[str]:
    lines = []
    gt = ea.get("ground_truth", "?")
    lines.append(f"## {name}")
    lines.append(f"**Ground truth:** {gt}")
    lines.append("")
    lines.append(f"**{label_a}** predicted: {ea.get('prediction', '?')}")
    lines.append("")
    lines.append(ea.get("raw_output", "").strip())
    lines.append("")
    lines.append(f"**{label_b}** predicted: {eb.get('prediction', '?')}")
    lines.append("")
    lines.append(eb.get("raw_output", "").strip())
    lines.append("")
    lines.append("---")
    lines.append("")
    return lines


def render_report(title: str, label_a: str, label_b: str, pairs: list[tuple[str, dict, dict]]) -> str:
    lines = [f"# {title}", ""]
    lines.append(f"**{label_a}** vs **{label_b}**  ")
    lines.append(f"**Count:** {len(pairs)}")
    lines.append("")
    lines.append("---")
    lines.append("")
    for name, ea, eb in pairs:
        lines.extend(render_example_pair(name, ea, eb, label_a, label_b))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Compare two results JSON files.")
    parser.add_argument("file_a", metavar="FILE_A")
    parser.add_argument("file_b", metavar="FILE_B")
    args = parser.parse_args()

    path_a, path_b = Path(args.file_a), Path(args.file_b)
    label_a = path_a.stem
    label_b = path_b.stem

    examples_a = load_by_name(path_a)
    examples_b = load_by_name(path_b)

    shared_names = sorted(set(examples_a) & set(examples_b))

    both_wrong = []
    differed   = []

    for name in shared_names:
        ea, eb = examples_a[name], examples_b[name]
        wrong_a = not ea.get("correct", True)
        wrong_b = not eb.get("correct", True)
        if wrong_a and wrong_b:
            both_wrong.append((name, ea, eb))
        elif ea.get("prediction") != eb.get("prediction"):
            differed.append((name, ea, eb))

    out_dir = path_a.parent
    stem = f"{label_a}_vs_{label_b}"

    both_wrong_path = out_dir / f"{stem}_both_wrong.md"
    differed_path   = out_dir / f"{stem}_differed.md"

    both_wrong_path.write_text(
        render_report("Both Models Wrong", label_a, label_b, both_wrong)
    )
    differed_path.write_text(
        render_report("Differing Predictions", label_a, label_b, differed)
    )

    print(f"Both wrong ({len(both_wrong)}):        {both_wrong_path}")
    print(f"Differing predictions ({len(differed)}): {differed_path}")


if __name__ == "__main__":
    main()
