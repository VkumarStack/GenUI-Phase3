"""
Evaluate UI revision examples with a VLM backend.

Backends:
  gemini  — Gemini 2.5 Pro via Google AI Studio (default)
  ollama  — Local model via Ollama daemon
  hf      — HuggingFace transformers (Kaggle / GPU)

Running:
    evaluate.py
    evaluate.py --backend ollama
    evaluate.py --backend hf --model Qwen/Qwen2.5-VL-7B-Instruct
    evaluate.py --diff
    evaluate.py --example RevisionExamples/Example2
"""

import argparse
from pathlib import Path

from dotenv import load_dotenv

from backends import get_backend

load_dotenv()

EXAMPLES_DIR = Path(__file__).parent / "RevisionExamples"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend",
        choices=["gemini", "ollama", "hf"],
        default="gemini",
        help="Which model backend to use (default: gemini)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name override. Omit to use the backend's default.",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="Provide the code diff instead of full before/after code.",
    )
    parser.add_argument(
        "--example",
        default=None,
        help="Path to a single example directory to evaluate (default: run all).",
    )
    args = parser.parse_args()

    # Backend init happens once here (model loading for HF can take a minute).
    backend = get_backend(args.backend, args.model)
    model_name = backend.model_name if hasattr(backend, "model_name") else args.model
    code_mode = "diff" if args.diff else "full code"
    print(f"Backend: {args.backend}  |  Model: {model_name}  |  Code mode: {code_mode}")

    if args.example:
        example_path = Path(args.example)
        # Allow either a full path or a bare name like "Example2".
        if not example_path.is_absolute():
            example_path = Path(__file__).parent / example_path
        example_dirs = [example_path]
    else:
        example_dirs = sorted(d for d in EXAMPLES_DIR.iterdir() if d.is_dir())

    for example_dir in example_dirs:
        print(f"\n{'='*60}")
        print(f"Example: {example_dir.name}")
        print(f"Task:    {(example_dir / 'Task.txt').read_text().strip()}")
        print("-" * 60)

        result = backend.evaluate(example_dir, use_diff=args.diff)

        print(f"Verdict: {result['verdict']}")
        print(f"\nModel response:\n{result['response']}")


if __name__ == "__main__":
    main()
