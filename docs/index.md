# TumorQuantAI

![TumorQuantAI whole-slide analysis workflow](assets/tumorquantai-hero.svg){ .tqa-hero }

**TumorQuantAI converts H&E whole-slide images into reviewable HistoPLUS cell coordinates, quality-control overlays, per-slide summaries, and cohort tables.**
{: .tqa-lede }

!!! warning "Research use only"
    TumorQuantAI is not a diagnostic device. Predictions are not diagnoses or pathologist ground truth and must not be used alone for patient-care decisions.

## Start from a fresh clone

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
```

## Choose your path

<div class="tqa-summary-grid" markdown>

<div class="tqa-summary-card" markdown>

### QuickStart Example 1

Download, verify, convert, and inspect [one public lymphoma WSI](quick_start.md). Authorized users can continue with a deterministic 1% HistoPLUS smoke analysis.

</div>

<div class="tqa-summary-card" markdown>

### Full tutorial

Process the complete [21-slide lymphoma collection at 10%](full_tutorial.md), with exact Zenodo downloads, checksums, L0/L2 conversion, roster inspection, inference, and output verification.

</div>

<div class="tqa-summary-card" markdown>

### Your own WSIs

Follow [Apply TumorQuantAI to your own data](own_data.md) to inspect slide names and physical scale before selecting a 1%, 10%, or 100% run.

</div>

</div>

## QuickStart Example 1

The public preparation step does not require HistoPLUS access:

```bash
# Create the tutorial environment.
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-tutorial.txt

# Set the only path that must be changed.
TQA_ROOT=/path/to/mounted/storage/tumorquantai-quickstart

# Download, verify, convert, and inspect one public WSI.
./tumorquantai quickstart \
  --output "$TQA_ROOT" \
  --cpu \
  --no-inference
```

The command downloads only `TumorQuantAI_LymphomaWSI_022.mds`, validates the fixed public manifest and checksums, converts L0 and L2, and writes `START_HERE.html` plus a model-free inspection report.

![One-slide quickstart flow](assets/tutorial/quickstart_wsi_flow.svg)

After [authorized HistoPLUS access](how-to/model-access.md) is configured, rerun the command without `--no-inference` to process a reproducible 1% sample of tissue tiles.

## Full tutorial at 10%

The complete public workflow uses all 21 lymphoma WSIs from Zenodo record `21466410` and the `fast` preset:

```bash
# Run the prepared 21-slide collection at a deterministic 10%.
./tumorquantai run /path/to/mounted/storage/tumorquantai-lymphoma-21/slides \
  --sample-sheet /path/to/mounted/storage/tumorquantai-lymphoma-21/slides/samples.csv \
  --output /path/to/mounted/storage/tumorquantai-lymphoma-21/results-10-percent \
  --work-dir /path/to/mounted/storage/tumorquantai-lymphoma-21/work-10-percent \
  --preset fast \
  --source-mpp 0.261780 \
  --gpu
```

The [full tutorial](full_tutorial.md) begins from cloning, exposes the exact public download and checksum commands, and verifies all 21 outputs.

![Full 21-slide workflow](assets/tutorial/full_lymphoma_flow.svg)

## What the workflow records

```text
H&E WSI
  -> input fingerprint and source MPP
  -> deterministic tissue-tile selection
  -> pinned HistoPLUS model and container identity
  -> cell coordinates and visual overlays
  -> per-slide summary
  -> cohort counts, fractions, and aggregation audit
```

TumorQuantAI keeps slides isolated for retry and resume. A failed or incomplete slide remains visible in the aggregation audit and does not become an all-zero biological sample.

## Sampling presets

![TumorQuantAI sampling presets](assets/tutorial/sampling_presets.svg)

| Preset | Tissue tiles | Use |
| --- | ---: | --- |
| `smoke` | Seeded 1% from one selected slide | First authorized inference check |
| `fast` | Seeded 10% | Reproducible exploratory cohort analysis |
| `full` | 100% | Exhaustive processing after smaller runs pass review |

Counts from 1% or 10% runs describe sampled tiles. They are not validated whole-slide estimates and must not be scaled by dividing by the sampling percentage.

## Open these outputs first

![TumorQuantAI output map](assets/tutorial/output_map.svg)

1. `START_HERE.html`
2. `<sample>/overlays/celltypes_overview_and_zoom.png`
3. `<sample>/summary/summary.json`
4. `aggregated_celltypes/sample_aggregation_audit.csv`
5. `aggregated_celltypes/celltype_counts_by_sample.csv`
6. `aggregated_celltypes/celltype_fractions_by_sample.csv`

See [Output files](outputs.md) for the complete structure and [Results gallery](gallery.md) for visual explanations.

## Published tutorial dataset

The public tutorial dataset is [Zenodo record 21466410](https://zenodo.org/records/21466410), DOI [`10.5281/zenodo.21466410`](https://doi.org/10.5281/zenodo.21466410). It contains 21 privacy-sanitized lymphoma WSIs and has no diagnostic annotations or pathologist ground truth.

## Continue

- [Install requirements](installation.md)
- [QuickStart Example 1](quick_start.md)
- [Full 21-slide tutorial at 10%](full_tutorial.md)
- [Apply to your own WSIs](own_data.md)
- [Input files and MPP](inputs.md)
- [Running, presets, and resume](running.md)
- [Troubleshooting](troubleshooting/index.md)