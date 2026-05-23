"""
One-off inspection script: generates a Markdown file with all rendered
MUD screenshots and their metadata for quick visual review.

Run AFTER MUD_screenshot.py has produced screenshots.

Usage:
    python MUD_inspect.py [--output review_mud.md]
"""

import argparse
from pathlib import Path
import pandas as pd

ROOT          = Path(__file__).parent.parent  # project root (GenUI/)
DATASET_DIR   = ROOT / "Datasets/MUD_GenreUI"
SCREENSHOTS   = DATASET_DIR / "screenshots"
CSV_PATH      = DATASET_DIR / "results_final_100.csv"
DEFAULT_OUT   = ROOT / "review_mud.md"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    out_path = Path(args.output)

    df = pd.read_csv(CSV_PATH)
    df["id"] = df["id"].astype(str)
    meta = df.set_index("id")

    screenshots = sorted(SCREENSHOTS.glob("*.png"), key=lambda p: int(p.stem))
    if not screenshots:
        raise SystemExit(f"No screenshots found in {SCREENSHOTS}. Run MUD_screenshot.py first.")

    # Use paths relative to the output markdown file
    out_dir = out_path.parent.resolve()

    lines = [f"# MUD HTML Screenshot Review ({len(screenshots)} screens)\n"]

    for png in screenshots:
        id_ = png.stem
        rel = png.resolve().relative_to(out_dir)

        row = meta.loc[id_] if id_ in meta.index else None
        if row is not None:
            label = (
                f"**{row['app_type']}** | {row['intent']} | {row['ui_pattern']} "
                f"| conf={row['confidence']:.2f}"
            )
        else:
            label = "*(no metadata)*"

        lines.append(f"## {id_}\n")
        lines.append(f"{label}\n")
        lines.append(f"![{id_}]({rel})\n")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Written: {out_path}  ({len(screenshots)} entries)")


if __name__ == "__main__":
    main()
