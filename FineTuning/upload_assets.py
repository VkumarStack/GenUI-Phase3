"""
Upload Before/After screenshots for SFT examples to Google Cloud Storage.

For each example directory, uploads:
    Before/screenshot.png  →  gs://<bucket>/<prefix>/<example>/before.png
    After/screenshot.png   →  gs://<bucket>/<prefix>/<example>/after.png

Outputs a JSON manifest mapping example names to their GCS URIs, which
build_dataset.py reads when constructing training pairs.

Authentication: uses Application Default Credentials (gcloud auth
application-default login). No .env file required.

Usage:
    python FineTuning/upload_assets.py \\
        --dir Examples/CaseStudyExamples \\
        --bucket your-bucket-name \\
        --prefix sft-assets \\
        --manifest FineTuning/manifest.json

    python FineTuning/upload_assets.py \\
        --example Examples/CaseStudyExamples/task-8-gemini \\
        --bucket your-bucket-name \\
        --manifest FineTuning/manifest.json
"""

import argparse
import json
from pathlib import Path

from google.cloud import storage


def upload_example(example_dir: Path, bucket: storage.Bucket, prefix: str) -> dict:
    """Upload before/after screenshots for one example. Returns their GCS URIs."""
    name = example_dir.name
    uris = {}
    for variant, filename in [("before", "Before/screenshot.png"), ("after", "After/screenshot.png")]:
        local_path = example_dir / filename
        if not local_path.exists():
            print(f"  [SKIP] {local_path} not found")
            continue
        blob_name = f"{prefix}/{name}/{variant}.png"
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(str(local_path), content_type="image/png")
        uri = f"gs://{bucket.name}/{blob_name}"
        uris[variant] = uri
        print(f"  Uploaded {local_path} → {uri}")
    return uris


def main():
    parser = argparse.ArgumentParser(description="Upload SFT screenshots to GCS.")

    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--example", metavar="PATH", help="Path to a single example directory.")
    target.add_argument("--dir",     metavar="PATH", help="Path to a directory of examples.")

    parser.add_argument("--bucket",   required=True, help="GCS bucket name (no gs:// prefix).")
    parser.add_argument("--prefix",   default="sft-assets", help="Path prefix inside the bucket.")
    parser.add_argument("--manifest", default="FineTuning/manifest.json",
                        help="Output JSON manifest path (default: FineTuning/manifest.json).")
    args = parser.parse_args()

    client = storage.Client()
    bucket = client.bucket(args.bucket)

    if args.example:
        example_dirs = [Path(args.example)]
    else:
        example_dirs = sorted(d for d in Path(args.dir).iterdir() if d.is_dir())

    manifest = {}
    for example_dir in example_dirs:
        print(f"\nExample: {example_dir.name}")
        uris = upload_example(example_dir, bucket, args.prefix)
        if uris:
            manifest[example_dir.name] = uris

    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nManifest written to {manifest_path}  ({len(manifest)} example(s))")


if __name__ == "__main__":
    main()
