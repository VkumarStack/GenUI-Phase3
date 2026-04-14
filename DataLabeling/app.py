"""
Data labeling server for UI revision examples.

Serves before/after screenshots, diffs, and tasks for each example under
Examples/FineTuningExamples/, and handles reading/writing Output.txt files.

Usage:
    python DataLabeling/app.py
    python DataLabeling/app.py --examples-dir Examples/FineTuningExamples --port 5000
"""

import argparse
import re
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

app = Flask(__name__, template_folder="templates")
EXAMPLES_DIR: Path = None


def get_example_dirs() -> list[Path]:
    return sorted(d for d in EXAMPLES_DIR.iterdir() if d.is_dir())


def parse_output(text: str) -> dict:
    """Parse an existing Output.txt into verdict, code_reasoning, image_reasoning."""
    lines = text.strip().splitlines()
    verdict = ""
    code_reasoning = ""
    image_reasoning = ""

    if lines:
        first = lines[0].strip().upper()
        if first in ("PASS", "FAIL"):
            verdict = first

    # Locate each section label (no DOTALL — just find the label positions).
    code_match  = re.search(r"Code Reasoning:\s*",  text, re.IGNORECASE)
    image_match = re.search(r"Image Reasoning:\s*", text, re.IGNORECASE)

    if code_match and image_match:
        code_reasoning  = text[code_match.end():image_match.start()].strip()
        image_reasoning = text[image_match.end():].strip()
    elif code_match:
        code_reasoning  = text[code_match.end():].strip()
    elif image_match:
        image_reasoning = text[image_match.end():].strip()

    # Fallback: old single "Reasoning:" field — load into code_reasoning.
    if not code_reasoning and not image_reasoning:
        old_match = re.search(r"Reasoning:\s*", text, re.IGNORECASE)
        if old_match:
            code_reasoning = text[old_match.end():].strip()

    return {"verdict": verdict, "code_reasoning": code_reasoning, "image_reasoning": image_reasoning}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/examples")
def list_examples():
    result = []
    for d in get_example_dirs():
        output_path = d / "Output.txt"
        labeled = output_path.exists() and output_path.read_text().strip() != ""
        result.append({"name": d.name, "labeled": labeled})
    return jsonify(result)


@app.route("/api/example/<name>")
def get_example(name: str):
    example_dir = EXAMPLES_DIR / name
    if not example_dir.is_dir():
        abort(404)

    task_path   = example_dir / "Task.txt"
    diff_path   = example_dir / "After" / "diff.txt"
    output_path = example_dir / "Output.txt"

    task = task_path.read_text().strip() if task_path.exists() else ""
    diff = diff_path.read_text()         if diff_path.exists() else ""

    output_data = {"verdict": "", "code_reasoning": "", "image_reasoning": ""}
    if output_path.exists():
        output_data = parse_output(output_path.read_text())

    return jsonify({
        "name":            name,
        "task":            task,
        "diff":            diff,
        "verdict":         output_data["verdict"],
        "code_reasoning":  output_data["code_reasoning"],
        "image_reasoning": output_data["image_reasoning"],
    })


@app.route("/api/example/<name>/image/<variant>")
def get_image(name: str, variant: str):
    if variant not in ("before", "after"):
        abort(400)
    subdir = "Before" if variant == "before" else "After"
    img_path = EXAMPLES_DIR / name / subdir / "screenshot.png"
    if not img_path.exists():
        abort(404)
    return send_file(img_path, mimetype="image/png")


@app.route("/api/example/<name>/save", methods=["POST"])
def save_example(name: str):
    example_dir = EXAMPLES_DIR / name
    if not example_dir.is_dir():
        abort(404)

    data           = request.get_json()
    verdict        = data.get("verdict", "").strip().upper()
    code_reasoning = data.get("code_reasoning", "").strip()
    image_reasoning = data.get("image_reasoning", "").strip()

    if verdict not in ("PASS", "FAIL"):
        return jsonify({"error": "verdict must be PASS or FAIL"}), 400

    output = f"{verdict}\n\nCode Reasoning: {code_reasoning}\n\nImage Reasoning: {image_reasoning}\n"
    (example_dir / "Output.txt").write_text(output)
    return jsonify({"ok": True})


def main():
    parser = argparse.ArgumentParser(description="Data labeling server.")
    parser.add_argument("--examples-dir", default="Examples/FineTuningExamples",
                        help="Path to the examples directory.")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    global EXAMPLES_DIR
    EXAMPLES_DIR = Path(args.examples_dir).resolve()
    if not EXAMPLES_DIR.is_dir():
        raise SystemExit(f"Error: examples directory not found: {EXAMPLES_DIR}")

    print(f"Serving examples from: {EXAMPLES_DIR}")
    print(f"Open http://localhost:{args.port} in your browser\n")
    app.run(debug=False, port=args.port)


if __name__ == "__main__":
    main()
