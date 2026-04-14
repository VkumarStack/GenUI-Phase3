"""
Submit a Vertex AI supervised fine-tuning job for Gemini.

The training JSONL must be uploaded to GCS before the tuning job can start.
This script handles that upload automatically if you pass a local --dataset path,
or you can point directly at an existing GCS URI with --dataset gs://...

Authentication: Application Default Credentials (gcloud auth application-default login).

Usage:
    # Upload local JSONL and start tuning
    python FineTuning/tune.py \\
        --project your-project-id \\
        --bucket your-bucket-name \\
        --dataset FineTuning/train.jsonl

    # Use a JSONL already in GCS
    python FineTuning/tune.py \\
        --project your-project-id \\
        --dataset gs://your-bucket-name/sft-datasets/train.jsonl

    # Override model, display name, or hyperparameters
    python FineTuning/tune.py \\
        --project your-project-id \\
        --bucket your-bucket-name \\
        --dataset FineTuning/train.jsonl \\
        --model gemini-2.5-pro-002 \\
        --display-name genui-evaluator-v1 \\
        --epochs 3 \\
        --learning-rate-multiplier 1.0
"""

import argparse
import sys
from pathlib import Path


def upload_dataset(local_path: Path, bucket_name: str, prefix: str = "sft-datasets") -> str:
    """Upload a local JSONL file to GCS and return its gs:// URI."""
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob_name = f"{prefix}/{local_path.name}"
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(str(local_path), content_type="application/jsonl")
    uri = f"gs://{bucket_name}/{blob_name}"
    print(f"Uploaded dataset → {uri}")
    return uri


def submit_tuning_job(
    project: str,
    location: str,
    source_model: str,
    train_dataset_uri: str,
    display_name: str,
    epochs: int,
    learning_rate_multiplier: float,
) -> object:
    """Submit the SFT job and return the job object."""
    import vertexai
    from vertexai.tuning import sft

    vertexai.init(project=project, location=location)

    job = sft.train(
        source_model=source_model,
        train_dataset=train_dataset_uri,
        epochs=epochs,
        learning_rate_multiplier=learning_rate_multiplier,
        tuned_model_display_name=display_name,
    )
    return job


def main():
    parser = argparse.ArgumentParser(description="Submit a Vertex AI Gemini SFT job.")

    parser.add_argument("--project",  required=True, help="Google Cloud project ID.")
    parser.add_argument("--location", default="us-central1",
                        help="Vertex AI region (default: us-central1).")
    parser.add_argument("--bucket",   default=None,
                        help="GCS bucket name for dataset upload. Required if --dataset is a local path.")
    parser.add_argument("--dataset",  required=True,
                        help="Local path to train.jsonl OR a gs:// URI if already uploaded.")
    parser.add_argument("--model",    default="gemini-2.5-pro-002",
                        help="Source model ID (default: gemini-2.5-pro-002).")
    parser.add_argument("--display-name", default="genui-evaluator",
                        help="Display name for the tuned model (default: genui-evaluator).")
    parser.add_argument("--epochs",   type=int,   default=3,
                        help="Number of training epochs (default: 3).")
    parser.add_argument("--learning-rate-multiplier", type=float, default=1.0,
                        help="Learning rate multiplier (default: 1.0).")
    args = parser.parse_args()

    # Resolve dataset URI.
    if args.dataset.startswith("gs://"):
        train_uri = args.dataset
    else:
        local_path = Path(args.dataset)
        if not local_path.exists():
            print(f"Error: dataset file not found: {local_path}")
            sys.exit(1)
        if not args.bucket:
            print("Error: --bucket is required when --dataset is a local path.")
            sys.exit(1)
        train_uri = upload_dataset(local_path, args.bucket)

    print(f"\nSubmitting tuning job...")
    print(f"  Project:  {args.project}")
    print(f"  Location: {args.location}")
    print(f"  Model:    {args.model}")
    print(f"  Dataset:  {train_uri}")
    print(f"  Epochs:   {args.epochs}  |  LR multiplier: {args.learning_rate_multiplier}")

    job = submit_tuning_job(
        project=args.project,
        location=args.location,
        source_model=args.model,
        train_dataset_uri=train_uri,
        display_name=args.display_name,
        epochs=args.epochs,
        learning_rate_multiplier=args.learning_rate_multiplier,
    )

    print(f"\nJob submitted.")
    print(f"  Resource name: {job.resource_name}")
    print(f"\nMonitor progress in the Cloud Console:")
    print(f"  https://console.cloud.google.com/vertex-ai/training/custom-jobs?project={args.project}")
    print(f"\nOnce complete, the tuned model will appear in Model Registry under '{args.display_name}'.")


if __name__ == "__main__":
    main()
