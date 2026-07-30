# TumorQuantAI documentation

![Diagram showing a whole-slide image becoming tissue tiles, predicted cells, review overlays, and cohort tables](assets/tumorquantai-hero.svg){ .tqa-hero }

**TumorQuantAI is a reproducible research workflow that applies HistoPLUS cell
typing to H&E whole-slide images and keeps the inputs, sampling, failures, and
outputs reviewable.**
{: .tqa-lede }

!!! warning "Research use only"
    TumorQuantAI is not a diagnostic device. Predictions are not diagnoses or
    pathologist ground truth and must not be used for patient-care decisions.

## Start with a command

Check the software structure without a GPU, model, Docker, or credentials:

```bash
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
./tumorquantai demo
```

Then open `tumorquantai-demo/START_HERE.html`. Every demo page is labelled as
synthetic structural output with no biological meaning.

## Choose your path

<div class="tqa-summary-grid" markdown>

<div class="tqa-summary-card" markdown>

### No model: learn the layout

Run the [structural demo](start-here/demo.md). It exercises discovery,
per-sample isolation, failure auditing, aggregation, status, and reporting.

</div>

<div class="tqa-summary-card" markdown>

### One public real slide

Follow the [one-slide quickstart](start-here/public-slide.md). The public MDS
download needs no Zenodo credential; inference waits for authorized HistoPLUS
access.

</div>

<div class="tqa-summary-card" markdown>

### Your own slides

Use [inspect and run your own slide](start-here/own-slides.md) to create a
reviewable manifest and establish source MPP before inference.

</div>

</div>

## The result contract

TumorQuantAI writes one result directory per sample, then aggregates only
completed samples:

```text
results/
├── START_HERE.html
├── <sample>/
│   ├── cell_types/class_counts.csv
│   ├── cell_types/cell_type_coordinates.csv
│   ├── overlays/celltypes_overview_and_zoom.png
│   └── summary/summary.json
└── aggregated_celltypes/
    ├── celltype_counts_by_sample.csv
    ├── celltype_fractions_by_sample.csv
    └── sample_aggregation_audit.csv
```

The exact [output reference](reference/outputs.md) is derived from the current
writers. A failed or incomplete sample is excluded from numeric matrices and
retained in the audit; it never becomes an all-zero biological sample.

## Understand before scaling

- [What TumorQuantAI predicts](explanation/predictions.md)
- [WSI, pyramid levels, L0 and L2](explanation/wsi-pyramid.md)
- [Source MPP versus target MPP](explanation/mpp.md)
- [Sampling and reproducibility](explanation/sampling.md)
- [Counts versus fractions](explanation/counts-fractions.md)
- [Failed sample versus biological zero](explanation/failed-vs-zero.md)

For errors, begin at [Troubleshooting](troubleshooting/index.md). A bug report
should contain redacted `doctor --json` and `status --json` output—never a
token, model weight, raw WSI, PHI, or patient-level table.

## Published teaching dataset

The public collection is [Zenodo record
21466410](https://zenodo.org/records/21466410), DOI
[`10.5281/zenodo.21466410`](https://doi.org/10.5281/zenodo.21466410), matched
to TumorQuantAI `v0.4.0`. The collection has no diagnostic annotations or
pathologist ground truth and is not a clinical benchmark.
