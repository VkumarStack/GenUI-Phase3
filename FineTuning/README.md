# FineTuning/

Builds the supervised fine-tuning (SFT) data for the **revision generator** and
helps estimate its cost. Only the revision generator is fine-tuned — evaluator
fine-tuning was abandoned in favor of prompt engineering.

The fine-tuning itself is **not scripted**: it is run through the **Vertex AI
console** by uploading the generated `train.jsonl`. These scripts only prepare and
cost that file.

| File | Purpose |
|---|---|
| `upload_assets.py` | Upload Before screenshots to GCS (so the JSONL can reference them by URI). |
| `RevisionGenerator/build_dataset.py` | Build `train.jsonl` from the dataset + the GCS manifest. |
| `count_tokens.py` | Count billable tokens and estimate cost. |
| `manifest.json` | `source_folder → {before: gs://…}` URI map produced by `upload_assets.py`. |
| `RevisionGenerator/train.jsonl` | The committed SFT data used for the deployed model. |

---

## Expected training-data structure

The generator learns **`(category + Before screenshot) → revision task`**. Each
training example therefore needs three things:

1. the **Before screenshot** of the screen (the only image; the model is
   conditioned on the before-state, never the after);
2. the **taxonomy category** it is conditioned on — its `name` and `description`;
3. the **label**: the target revision-task text.

These come from `Datasets/RevisionGeneratorModelDataset/All/Example-NNN/`:
`screenshot.png` (Before), `prompt.txt` (`Category:` / `Description:`),
`task.txt` (the label), and `meta.json` (`source_folder`, used to look up the
screenshot's GCS URI in the manifest). `build_dataset.py` emits each as a Vertex
AI SFT record: a system instruction, a user turn (category text + the Before image
as a `fileData` GCS URI), and a model turn (the task text).

> If new examples are added, each must carry a **category** (see
> `Taxonomy/RevisionTaxonomy/assign.py`) — the conditioning the model was trained
> on is otherwise missing.

---

## Workflow

```bash
# 1. Upload the Before screenshots to GCS and (re)build the manifest.
#    The manifest must cover every source_folder in the dataset, or build_dataset
#    will skip those examples.
python FineTuning/upload_assets.py --bucket genui-sft

# 2. Build the SFT JSONL (resolves image URIs from manifest.json).
python FineTuning/RevisionGenerator/build_dataset.py     # -> RevisionGenerator/train.jsonl

# 3. Check the cost before tuning (see below).
python FineTuning/count_tokens.py --dataset FineTuning/RevisionGenerator/train.jsonl --epochs 40

# 4. Fine-tune in the Vertex AI console: create a tuning job for the base model
#    and upload train.jsonl as the training dataset. Make sure step 1 ran first —
#    the JSONL references the images by GCS URI, so the assets must exist in the bucket.
```

---

## Cost — read this before tuning

`count_tokens.py` measures the real token cost (text + images) of `train.jsonl`
via the Gemini `countTokens` API, then multiplies by epochs:

```bash
python FineTuning/count_tokens.py --dataset FineTuning/RevisionGenerator/train.jsonl --epochs 40
```

For the current `train.jsonl` (127 examples) this is **≈98K tokens per epoch** (so
≈3.9M billable tokens at 40 epochs). The dollar figure is `billable_tokens × price`:

- **Check the current Vertex AI tuning price per token** on Google's pricing page —
  do not trust the `--price-per-million` default (a placeholder); pass the current
  rate to get a real estimate.
- **Pin the epoch count.** Vertex AI chooses a **dynamic** number of epochs by
  default, which makes the spend unpredictable. Set a fixed `epoch_count` in the
  tuning job (the deployed model used 40) so you know what you are paying for, and
  size it with `count_tokens.py --epochs <n>` first.

---

## Handoff: using the tuned model

The deployed tuned model lives in the original developer's Google Cloud account, so
its Vertex AI endpoint is not reachable from another account. **Reusing it requires
coordinating with the original developer (Vivek) to transfer the model** — the
specifics are out of scope here; reach out to arrange it.
