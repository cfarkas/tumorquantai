# TumorQuantAI

Turn H&E whole-slide images into reproducible HistoPLUS cell coordinates,
review overlays, per-slide counts, and cohort tables.

[![CI](https://github.com/cfarkas/tumorquantai/actions/workflows/ci.yml/badge.svg)](https://github.com/cfarkas/tumorquantai/actions/workflows/ci.yml)
[![Documentation](https://github.com/cfarkas/tumorquantai/actions/workflows/docs.yml/badge.svg)](https://cfarkas.github.io/tumorquantai/)
[![Release](https://img.shields.io/github/v/release/cfarkas/tumorquantai?sort=semver)](https://github.com/cfarkas/tumorquantai/releases/latest)
[![Nextflow](https://img.shields.io/badge/workflow-Nextflow-0dc09d)](https://www.nextflow.io/)
[![Dataset DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21466410.svg)](https://doi.org/10.5281/zenodo.21466410)

> [!WARNING]
> **Research use only.** TumorQuantAI is not a diagnostic device. HistoPLUS
> predictions are not diagnoses or pathologist ground truth. Review image
> quality, physical scale, sampling, overlays, failures, and biological
> interpretation; never use these outputs for patient-care decisions.

## Quick start

No GPU, model weights, account, or network connection is needed after cloning:

```bash
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
./tumorquantai demo
```

Expected final message (the last line uses your absolute checkout path):

```text
TumorQuantAI structural demo complete.
No HistoPLUS inference ran; values have no biological meaning.
Included fixture samples: 2; intentional failed fixture: 1; completed zero fixture: 1
Open first: /your/checkout/tumorquantai-demo/START_HERE.html
```

This is a **structural software demo**, not a biological prediction or
validation dataset. Open `tumorquantai-demo/START_HERE.html` in a browser.

Next, choose one path:

```bash
# Public real slide; inference continues when authorized HistoPLUS access exists
./tumorquantai quickstart --output /mounted/storage/tutorial-one-slide

# Inspect your own slides without inference
./tumorquantai inspect /data/slides --output /data/tumorquantai-inspection
```

The quickstart refuses repository, home-directory, root-filesystem, or
unverifiable data locations. Replace `/mounted/storage` with your verified
mounted storage path.

The one-slide path fetches only
`TumorQuantAI_LymphomaWSI_022.mds` (125,350,400 bytes) from public
[Zenodo record 21466410](https://zenodo.org/records/21466410), verifies it,
converts levels L0/L2, and prepares a 1% smoke test. Zenodo credentials are not
needed. Gated HistoPLUS access is needed only for inference.

[Start here](https://cfarkas.github.io/tumorquantai/start-here/demo/) ·
[Public one-slide guide](https://cfarkas.github.io/tumorquantai/start-here/public-slide/) ·
[Model access](https://cfarkas.github.io/tumorquantai/how-to/model-access/) ·
[Troubleshooting](https://cfarkas.github.io/tumorquantai/troubleshooting/)

## What TumorQuantAI does

```text
H&E whole-slide image
        │
        ├─ discover input and establish physical scale
        ├─ select tissue tiles reproducibly
        ├─ run HistoPLUS cell typing
        └─ write reviewable per-slide and cohort outputs
```

TumorQuantAI discovers primary slides without inference, processes them
independently with retry/resume, records fingerprints and physical scale, and
writes coordinates, overlays, per-slide counts, and cohort matrices. It records
the model/container identity, sampling percentage, random seed, and failed or
incomplete samples.

## What it does not do

TumorQuantAI does not:

- provide a diagnosis, clinical decision, or clinically validated biomarker;
- include or grant access to the gated HistoPLUS weights;
- infer trustworthy physical scale when source MPP is absent;
- turn sampled-tile counts into whole-slide counts; or
- make a failed or incomplete sample look like a biological zero.

The public lymphoma collection has no diagnostic annotations or pathologist
ground truth. It is a technical tutorial and reproducibility dataset, not a
clinical benchmark.

## Three beginner paths

| Goal | Command | Model/GPU needed? |
| --- | --- | --- |
| Check the software structure | `./tumorquantai demo` | No |
| Prepare and smoke-test one public WSI | `./tumorquantai quickstart --output PATH` | Only for inference |
| Review your own slide roster and MPP | `./tumorquantai inspect INPUT --output PATH` | No |

Run `./tumorquantai doctor` before real inference to check the host, Java,
Nextflow, Docker, GPU/CPU path, caches, and configured model readiness. Its
default storage probe uses the current path; add `--output PATH` and optionally
`--work-dir PATH` to check the intended mount. `--online` checks pinned public
metadata, not account authorization.

## Input expectations

The portable layout is a highest-resolution L0 TIFF and lower-resolution L2
companion:

```text
/data/slides/
└── case_001/
    ├── 1_L0_rgb.tif   # primary image analyzed
    └── 1_L2_rgb.tif   # companion for sampled reports
```

**WSI** means whole-slide image. **MPP** means micrometres per pixel. L0 is the
highest-resolution image; L2 is a lower-resolution pyramid level. The source
MPP describes the input; the target MPP describes model tiles. TumorQuantAI
fails closed when a required source scale cannot be established—do not copy an
MPP from another slide.

Alternative paths and controlled sample IDs are supported through an input
manifest/sample sheet. Inspect every roster before inference:

```bash
./tumorquantai inspect /data/slides --output /data/tumorquantai-inspection
```

## Choose a preset

| Preset | Tissue tiles | Use |
| --- | ---: | --- |
| `smoke` | Seeded 1% from one selected slide | First real run and environment check |
| `fast` | Seeded 10% by default | Exploratory composition and iteration |
| `full` | 100% of detected tissue tiles | Exhaustive processing after review |

```bash
./tumorquantai run /data/slides \
  --output /data/tumorquantai-smoke \
  --preset smoke \
  --source-mpp "$SOURCE_MPP"
```

Beginner runs place resumable Nextflow work inside the selected output by
default. Use different output/work directories for `fast` and `full`; the CLI
refuses unsafe mixing. Advanced `run.sh`, direct `nextflow run`, and existing
worker overrides remain supported.

## Inspect these outputs first

| Path | What it tells you |
| --- | --- |
| `START_HERE.html` | Portable run summary and links to outputs that exist |
| `<sample>/overlays/celltypes_overview_and_zoom.png` | Overview plus annotated zoom for visual QC |
| `<sample>/summary/summary.json` | Completion, MPP, sampling, seed, cells, and provenance |
| `<sample>/cell_types/class_counts.csv` | Counts in processed tissue tiles for one completed slide |
| `aggregated_celltypes/sample_aggregation_audit.csv` | Included, failed, and incomplete samples |
| `aggregated_celltypes/celltype_fractions_by_sample.csv` | Within-sample cell-type fractions |
| `aggregated_celltypes/celltype_counts_by_sample.csv` | Raw detected-cell counts in processed tiles |

Counts from 1% or 10% runs describe sampled tiles. They are not validated
whole-slide estimates and must not be multiplied by `100 / percent_slide`.

An absent class in a **completed** slide is a biological zero. A failed,
missing, or incomplete slide has no numeric matrix column and remains visible
in `sample_aggregation_audit.csv`.

```bash
./tumorquantai status /data/tumorquantai-smoke
./tumorquantai report /data/tumorquantai-smoke
```

Human `status` identifies the first log and prints the exact local resume
command. `status --json` and `report` redact sensitive filesystem paths and
never record credential locations; the report uses relative output links.

## Requirements at a glance

| Task | Requirements |
| --- | --- |
| Demo | Linux and Python 3; no network, GPU, Docker, or model |
| Inspect | Python 3; optional slide readers improve metadata reporting |
| Real inference | Linux, Java 17+, Nextflow 24.10+, Docker 24+ or prepared local environment, authorized HistoPLUS access |
| GPU inference | Compatible NVIDIA driver and container runtime |

Before a download, conversion, or run, verify the destination mount and budget
space separately for downloads, converted TIFFs, Nextflow work, and final
results. See [storage and mounts](https://cfarkas.github.io/tumorquantai/how-to/storage/).

## Documentation and help

- [Credential-free structural demo](https://cfarkas.github.io/tumorquantai/start-here/demo/)
- [Public one-slide quickstart](https://cfarkas.github.io/tumorquantai/start-here/public-slide/)
- [Inspect and run your own slide](https://cfarkas.github.io/tumorquantai/start-here/own-slides/)
- [Outputs and filenames](https://cfarkas.github.io/tumorquantai/reference/outputs/)
- [Resume an interrupted run](https://cfarkas.github.io/tumorquantai/how-to/resume/)
- [Troubleshooting](https://cfarkas.github.io/tumorquantai/troubleshooting/)
- [CLI reference](https://cfarkas.github.io/tumorquantai/reference/cli/)

When reporting a bug, attach redacted `doctor --json` and `status --json`
output. Never attach tokens, model weights, raw WSI, PHI, patient-level tables,
or unredacted logs.

## Reproducibility

The workflow pins the HistoPLUS revision and container identity, fingerprints
source slides and relevant companions, records deterministic sampling and MPP,
and isolates each slide for retry/cache reuse. Keep `summary.json`, workflow
metadata, aggregation audit, and command provenance with every analysis.

The public dataset is fixed at DOI
[`10.5281/zenodo.21466410`](https://doi.org/10.5281/zenodo.21466410) and is
matched to software release `v0.4.0`.

## Citation and license status

Cite each resource you actually use separately: TumorQuantAI software, the
public Zenodo tutorial dataset, LazySlide, and HistoPLUS. See
[CITATIONS.md](CITATIONS.md) for non-conflated guidance. The dataset DOI is not
a software DOI. The Zenodo dataset declares CC BY 4.0; that dataset license is
separate from repository source and gated model terms.

This repository currently has **no declared open-source license**. The source
is visible, but absence of a license does not grant permission to copy, modify,
or redistribute it. The owner decision is tracked in
[LICENSE_DECISION.md](docs/maintainers/LICENSE_DECISION.md); no license has
been selected on the owner's behalf.
