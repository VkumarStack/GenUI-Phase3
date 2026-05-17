"""
Upload Before/After screenshots from Datasets/RawDataset/ to Google Cloud Storage.

The manifest is keyed by RawDataset folder name so both the revision generator
and evaluator build_dataset.py scripts can resolve GCS URIs from their examples'
meta.json source fields.

For each example folder, uploads:
    Before/screenshot.png  →  gs://<bucket>/<prefix>/<folder>/before.png
    After/screenshot.png   →  gs://<bucket>/<prefix>/<folder>/after.png

Skips folders whose URIs are already present in the manifest unless --force.

Authentication: uses Application Default Credentials (gcloud auth
application-default login). No .env file required.

Running:
    python FineTuning/upload_assets.py --bucket your-bucket-name

    # Custom dataset path or prefix
    python FineTuning/upload_assets.py --bucket your-bucket-name \\
        --dataset Datasets/RawDataset --prefix sft-assets

    # Single folder (for testing)
    python FineTuning/upload_assets.py --bucket your-bucket-name \\
        --example Datasets/RawDataset/Participant_2_CaseStudy-1.1-CLAUDE

    # Reupload everything
    python FineTuning/upload_assets.py --bucket your-bucket-name --force
"""

import argparse
import json
from pathlib import Path

from google.cloud import storage

_ROOT = Path(__file__).parent.parent
_DATASET = _ROOT / "Datasets" / "RawDataset"
_MANIFEST = Path(__file__).parent / "manifest.json"


def upload_example(example_dir: Path, bucket: storage.Bucket, prefix: str) -> dict:
    """Upload before and after screenshots for one example. Returns their GCS URIs."""
    name = example_dir.name
    uris = {}
    for variant, rel_path in [
        ("before", "Before/screenshot.png"),
        ("after",  "After/screenshot.png"),
    ]:
        local = example_dir / rel_path
        if not local.exists():
            print(f"    [SKIP] {local.relative_to(_ROOT)} not found")
            continue
        blob_name = f"{prefix}/{name}/{variant}.png"
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(str(local), content_type="image/png")
        uri = f"gs://{bucket.name}/{blob_name}"
        uris[variant] = uri
        print(f"    {local.relative_to(_ROOT)} → {uri}")
    return uris


def main():
    parser = argparse.ArgumentParser(
        description="Upload RawDataset screenshots to GCS for SFT fine-tuning."
    )

    target = parser.add_mutually_exclusive_group()
    target.add_argument("--example", metavar="PATH",
                        help="Upload a single example folder (for testing).")
    target.add_argument("--dataset", default=str(_DATASET), metavar="PATH",
                        help=f"RawDataset directory to upload from (default: {_DATASET}).")

    parser.add_argument("--bucket",   required=True, help="GCS bucket name (no gs:// prefix).")
    parser.add_argument("--prefix",   default="sft-assets", help="Path prefix inside the bucket.")
    parser.add_argument("--manifest", default=str(_MANIFEST),
                        help=f"Output manifest path (default: {_MANIFEST}).")
    parser.add_argument("--force", action="store_true",
                        help="Re-upload even if already present in the manifest.")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    manifest: dict = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        print(f"Loaded existing manifest: {len(manifest)} entries")

    if args.example:
        example_dirs = [Path(args.example)]
    else:
        dataset = Path(args.dataset)
        example_dirs = sorted(d for d in dataset.iterdir() if d.is_dir())

    client = storage.Client()
    bucket = client.bucket(args.bucket)
    uploaded = skipped = 0

    for example_dir in example_dirs:
        name = example_dir.name
        if name in manifest and not args.force:
            skipped += 1
            continue
        print(f"\n{name}")
        uris = upload_example(example_dir, bucket, args.prefix)
        if uris:
            manifest[name] = uris
            uploaded += 1

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nUploaded: {uploaded}  Skipped (already in manifest): {skipped}")
    print(f"Manifest written to {manifest_path}  ({len(manifest)} total entries)")


if __name__ == "__main__":
    main()
