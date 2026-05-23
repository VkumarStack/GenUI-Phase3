"""
Generates a Markdown file pairing each MUD screenshot with its revision tasks
for quick visual inspection.

Usage:
    python MUD_Dataset_Utils/MUD_inspect_revisions.py [--output review_mud_revisions.md]
"""

import argparse
import json
from pathlib import Path

ROOT        = Path(__file__).parent.parent
DATASET_DIR = ROOT / "Datasets/MUD_GenreUI"
SCREENSHOTS = DATASET_DIR / "screenshots"
REVISIONS   = DATASET_DIR / "revisions.json"
DEFAULT_OUT = ROOT / "review_mud_revisions.md"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    out_path = Path(args.output)

    revisions = json.loads(REVISIONS.read_text())
    out_dir = out_path.parent.resolve()

    lines = [f"# MUD Revision Review ({len(revisions)} screens)\n"]

    for id_, entry in sorted(revisions.items(), key=lambda x: int(x[0])):
        png = SCREENSHOTS / f"{id_}.png"
        rel = png.resolve().relative_to(out_dir) if png.exists() else None

        lines.append(f"---\n\n## Screen {id_}\n")

        if rel:
            lines.append(f"![{id_}]({rel})\n")
        else:
            lines.append(f"*(screenshot not found: {png})*\n")

        if "error" in entry:
            lines.append(f"> **Error:** {entry['error']}\n")
            continue

        applicable = entry.get("applicable_categories", [])
        tasks = entry.get("tasks", {})

        if not applicable:
            lines.append("*No applicable categories.*\n")
            continue

        for category in applicable:
            lines.append(f"### {category}\n")
            cat_tasks = tasks.get(category, [])
            if cat_tasks:
                for i, task in enumerate(cat_tasks, 1):
                    lines.append(f"{i}. {task}\n")
            else:
                lines.append("*No tasks generated.*\n")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Written: {out_path}  ({len(revisions)} screens)")


if __name__ == "__main__":
    main()
