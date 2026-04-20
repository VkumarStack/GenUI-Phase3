"""
Ensemble evaluation CLI.

Config file format (JSON):
{
    "workers": [
        {"backend": "gemini",    "model": "gemini-2.5-pro"},
        {"backend": "anthropic", "model": "claude-sonnet-4-6"},
        {"backend": "ollama",    "model": "qwen2.5vl:7b"}
    ],
    "aggregator": {"backend": "gemini", "model": "gemini-2.5-pro"}
}

Running:
    ensemble_evaluate.py --config ensemble_config.json --example path/to/Example1
    ensemble_evaluate.py --config ensemble_config.json --dir path/to/Examples/TestExamples
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from backends import get_backend
from ensemble_eval import ensemble_evaluate


def load_config(config_path: Path) -> tuple[list[tuple[str, object]], object]:
    """Parse config JSON and return (worker_backends, aggregator_backend)."""
    cfg = json.loads(config_path.read_text())

    workers = cfg.get("workers")
    if not workers or not isinstance(workers, list):
        raise ValueError("Config must have a non-empty 'workers' list.")

    agg_cfg = cfg.get("aggregator")
    if not agg_cfg:
        raise ValueError("Config must have an 'aggregator' entry.")

    worker_backends = []
    for w in workers:
        backend_name = w["backend"]
        model = w.get("model")
        label = f"{backend_name}/{model or 'default'}"
        worker_backends.append((label, get_backend(backend_name, model)))

    aggregator_backend = get_backend(agg_cfg["backend"], agg_cfg.get("model"))

    return worker_backends, aggregator_backend


def main():
    parser = argparse.ArgumentParser(description="Ensemble evaluation of UI revision examples.")

    parser.add_argument("--config", required=True, metavar="PATH",
                        help="Path to JSON config file specifying worker and aggregator models.")

    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--example", metavar="PATH", help="Path to a single example directory.")
    target.add_argument("--dir",     metavar="PATH", help="Path to a directory of examples.")

    args = parser.parse_args()

    worker_backends, aggregator_backend = load_config(Path(args.config))

    print("Workers:")
    for label, backend in worker_backends:
        print(f"  {label}  (model: {backend.model})")
    print(f"Aggregator: {aggregator_backend.model}\n")

    if args.example:
        example_dirs = [Path(args.example)]
    else:
        example_dirs = sorted(d for d in Path(args.dir).iterdir() if d.is_dir())

    for example_dir in example_dirs:
        print(f"\n{'='*60}")
        print(f"Example: {example_dir.name}")
        print(f"Task:    {(example_dir / 'Task.txt').read_text().strip()}")
        print("-" * 60)

        result = ensemble_evaluate(example_dir, worker_backends, aggregator_backend)

        print("Worker verdicts:")
        for w in result["worker_results"]:
            print(f"  {w['worker_label']}: {w['verdict']}")

        print(f"\nFinal verdict: {result['verdict']}")
        print(f"\nAggregator response:\n{result['aggregator_response']}")


if __name__ == "__main__":
    main()
