"""
Evaluate UI revision examples with a VLM backend.

Backends:
  gemini    — Gemini 2.5 Pro via Google AI Studio (default)
  anthropic — Claude via Anthropic API
  ollama    — Local model via Ollama daemon
  hf        — HuggingFace transformers (Kaggle / GPU)

Running:
    evaluate.py --example path/to/Example1
    evaluate.py --dir path/to/Examples/RevisionExamples
    evaluate.py --dir path/to/Examples/CaseStudyExamples --backend ollama
    evaluate.py --example path/to/Example1 --diff
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the same directory as this script (Evaluation/.env).
load_dotenv(Path(__file__).parent / ".env")

# Allow imports from the same directory regardless of invocation location.
sys.path.insert(0, str(Path(__file__).parent))
from backends import get_backend
from eval_core import evaluate


def main():
    parser = argparse.ArgumentParser(description="Evaluate UI revision examples with a VLM.")

    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--example", metavar="PATH", help="Path to a single example directory.")
    target.add_argument("--dir",     metavar="PATH", help="Path to a directory of examples.")

    parser.add_argument("--backend", choices=["gemini", "anthropic", "ollama", "hf"], default="gemini",
                        help="Model backend to use (default: gemini).")
    parser.add_argument("--model", default=None,
                        help="Model name override. Omit to use the backend's default.")
    parser.add_argument("--diff", action="store_true",
                        help="Pass the code diff instead of full before/after code.")
    args = parser.parse_args()

    backend = get_backend(args.backend, args.model)
    code_mode = "diff" if args.diff else "full code"
    print(f"Backend: {args.backend}  |  Model: {backend.model}  |  Code mode: {code_mode}")

    if args.example:
        example_dirs = [Path(args.example)]
    else:
        example_dirs = sorted(d for d in Path(args.dir).iterdir() if d.is_dir())

    for example_dir in example_dirs:
        print(f"\n{'='*60}")
        print(f"Example: {example_dir.name}")
        print(f"Task:    {(example_dir / 'Task.txt').read_text().strip()}")
        print("-" * 60)

        result = evaluate(example_dir, backend, use_diff=args.diff)

        print(f"Verdict: {result['verdict']}")
        print(f"\nModel response:\n{result['response']}")


if __name__ == "__main__":
    main()
