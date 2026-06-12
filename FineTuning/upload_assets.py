"""
Upload revision-generator Before screenshots to Google Cloud Storage for SFT.

The revision generator is conditioned on the Before screenshot only. This reads
`Datasets/RevisionGeneratorModelDataset/All/` (each `Example-NNN/` has
`screenshot.png` + a `meta.json` carrying its `source_folder`), uploads each
unique source's screenshot to:

    gs://<bucket>/<prefix>/<source_folder>/before.png

and writes a manifest keyed by `source_folder`:

    { "<source_folder>": { "before": "gs://..." } }

`FineTuning/RevisionGenerator/build_dataset.py` resolves each example's image via
`manifest[source_folder]["before"]`, so the manifest must be keyed by source
folder (not by `Example-NNN`). Multiple `Example-NNN/` folders share one
`source_folder` (one per taxonomy label); each source is uploaded once.

Auth: Application Default Credentials (`gcloud auth application-default login`).
No `.env` required.

Running:
    python FineTuning/upload_assets.py --bucket genui-sft
    python FineTuning/upload_assets.py --bucket genui-sft --force          # re-upload all
    python FineTuning/upload_assets.py --bucket genui-sft \\
        --example Datasets/RevisionGeneratorModelDataset/All/Example-000    # single folder test
    python FineTuning/upload_assets.py --bucket genui-sft \\
        --manifest /tmp/test_manifest.json                                  # don't touch the real manifest
"""

import argparse
import json
from pathlib import Path

from google.cloud import storage

_ROOT     = Path(__file__).parent.parent
_DATASET  = _ROOT / "Datasets" / "RevisionGeneratorModelDataset" / "All"
_MANIFEST = Path(__file__).parent / "manifest.json"


def _source_and_image(example_dir: Path) -> tuple[str | None, Path | None]:
    """Return (source_folder, screenshot_path) for an Example-NNN folder, or (None, None)."""
    meta = example_dir / "meta.json"
    shot = example_dir / "screenshot.png"
    if not meta.exists() or not shot.exists():
        return None, None
    source = json.loads(meta.read_text()).get("source_folder")
    return source, shot


def upload_before(source: str, image_path: Path, bucket: storage.Bucket, prefix: str) -> str:
    """Upload one Before screenshot and return its GCS URI."""
    blob_name = f"{prefix}/{source}/before.png"
    bucket.blob(blob_name).upload_from_filename(str(image_path), content_type="image/png")
    return f"gs://{bucket.name}/{blob_name}"


def main():
    parser = argparse.ArgumentParser(
        description="Upload revision-generator Before screenshots to GCS for SFT fine-tuning."
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--example", metavar="PATH",
                        help="Upload a single Example-NNN folder (for testing).")
    target.add_argument("--dataset", default=str(_DATASET), metavar="PATH",
                        help=f"RevisionGeneratorModelDataset/All directory (default: {_DATASET}).")

    parser.add_argument("--bucket",   required=True, help="GCS bucket name (no gs:// prefix).")
    parser.add_argument("--prefix",   default="sft-assets", help="Path prefix inside the bucket.")
    parser.add_argument("--manifest", default=str(_MANIFEST),
                        help=f"Output manifest path (default: {_MANIFEST}).")
    parser.add_argument("--force", action="store_true",
                        help="Re-upload even if the source is already in the manifest.")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    manifest: dict = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        print(f"Loaded existing manifest: {len(manifest)} entries")

    if args.example:
        example_dirs = [Path(args.example)]
    else:
        example_dirs = sorted(d for d in Path(args.dataset).iterdir() if d.is_dir())

    client = storage.Client()
    bucket = client.bucket(args.bucket)
    uploaded = skipped = missing = 0
    seen: set[str] = set()

    for example_dir in example_dirs:
        source, shot = _source_and_image(example_dir)
        if not source or shot is None:
            print(f"  [SKIP] {example_dir.name}: missing meta.json/source_folder or screenshot.png")
            missing += 1
            continue
        if source in seen:
            continue                       # already handled this source this run
        seen.add(source)
        if source in manifest and not args.force:
            skipped += 1
            continue

        uri = upload_before(source, shot, bucket, args.prefix)
        manifest[source] = {"before": uri}
        uploaded += 1
        print(f"  {source}  →  {uri}")

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nUploaded: {uploaded}  Skipped (already in manifest): {skipped}  Bad folders: {missing}")
    print(f"Manifest written to {manifest_path}  ({len(manifest)} total entries)")


if __name__ == "__main__":
    main()
