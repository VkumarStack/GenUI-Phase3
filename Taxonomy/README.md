# Taxonomy/

Two independent LLM-built taxonomies, each a small multi-pass pipeline. Both were
construction-time tools, not part of the runtime pipelines.

- **`RevisionTaxonomy/`** — the 7-category taxonomy of *revision task types*. This
  one matters: it conditions the revision generator and drives MUD task generation.
- **`EvaluationTaxonomy/`** — a taxonomy of *pass/fail reasons* from the human
  evaluations. This one turned out **not to be very useful** (see below).

---

## RevisionTaxonomy/ — revision task categories  (the important one)

Produces the seven revision categories (`Results/taxonomy.json`: `categories` +
per-example `assignments`) that the revision generator is conditioned on. Built in
two passes over `Datasets/RevisionGeneratorModelDataset/All/` (each `Example-NNN/`
has `task.txt`, `screenshot.png`, `meta.json`):

```bash
# Pass 1 — VLM assigns 1–3 free-form labels per unique revision task
python Taxonomy/RevisionTaxonomy/label.py            # -> raw_labels.json

# Pass 2 — consolidate the free-form labels into the final 7 categories + assign
python Taxonomy/RevisionTaxonomy/consolidate.py      # -> Results/taxonomy.{json,md}
```

`assign.py` is the standalone helper used to map a **new** example onto the
existing categories:

```bash
python Taxonomy/RevisionTaxonomy/assign.py --example Datasets/RevisionGeneratorModelDataset/All/Example-NNN
```

This is the tool to reach for if more revision examples are added and the generator
is re-fine-tuned — every training example must carry a category (see
`DatasetBuilder/README.md`).

## EvaluationTaxonomy/ — pass/fail reasons  (did not pan out)

An exploratory attempt to systematize *why* designers passed or failed a revision,
intended to inform the evaluator rubric. Three passes over
`Datasets/EvaluatorModelDataset/` (uses each example's `Output.txt` free-form notes
and `Before/After/screenshot.png`):

```bash
python Taxonomy/EvaluationTaxonomy/collect.py        # parse Output.txt -> raw_data.json
python Taxonomy/EvaluationTaxonomy/label.py          # VLM labels pass/fail reasons
python Taxonomy/EvaluationTaxonomy/consolidate.py    # -> pass/fail taxonomies (+ writes
                                                     #    Pass_Taxonomy.txt/Fail_Taxonomy.txt back)
```

**This taxonomy was not too useful in the end.** The pass/fail reasons it produced
were too diffuse and annotator-specific to translate cleanly into rubric rules; the
five-criterion rubric and its thresholds were instead arrived at mostly through
direct prompt engineering on the evaluator (inspecting wrong cases). The outputs
remain here for reference, but nothing downstream depends on them.
