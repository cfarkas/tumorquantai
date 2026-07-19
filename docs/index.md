# TumorQuantAI

![Abstract TumorQuantAI workflow: a whole-slide image becomes sampled tissue tiles, typed cells, and cohort tables](assets/tumorquantai-hero.svg){ .tqa-hero }

**Whole-slide images in. Cell-type tables, coordinates, and review images out.**
TumorQuantAI is a reproducible research workflow for quantifying HistoPLUS cell
types in H&E whole-slide images (WSIs). It processes each slide independently
and then combines successful samples into analysis-ready cohort matrices.
{: .tqa-lede }

!!! warning "Research use only"
    TumorQuantAI is not a diagnostic device and its predictions are not
    pathologist ground truth. A qualified expert must review image quality,
    tissue selection, overlays, and biological interpretation before results
    are used in research conclusions. Do not use its output for patient-care
    decisions.

## Choose where to start

| Your goal | Start here | What you will do |
| --- | --- | --- |
| Complete a first safe run | [Quick start](QUICKSTART.md) | Check the host, discover slides, confirm MPP, and run one slide at 1%. |
| Understand L0/L2 and physical scale | [Inputs and MPP](INPUTS_AND_MPP.md) | Select the correct primary image and avoid guessing image resolution. |
| Check slide discovery without running the model | [Discover your slides](#step-2-discover-before-inference) | Create and inspect the input manifest without spending inference time. |
| Test one slide first | [Run a 1% smoke test](#step-3-run-one-small-smoke-test) | Process a small, reproducible tissue-tile sample and inspect the outputs. |
| Choose between a sampled or exhaustive run | [Fast versus full](RUN_MODES.md) | Match processing depth to the study question and available compute. |
| Follow a worked WSI example | [Lymphoma WSI tutorial](TUTORIAL_LYMPHOMA_ZENODO.md) | Download the teaching collection, verify it, and progress from one to four to all 21 slides. |
| Understand the result files | [Output guide](OUTPUT_SCHEMA.md) | Find counts, fractions, coordinates, audit records, and per-slide images. |
| Continue an interrupted run | [Running and recovery](RUNNING.md) | Reuse completed tasks and interpret explicit failures. |
| Combine results with clinical metadata | [Clinical stratification and ML](CLINICAL_ML.md) | Run the advanced, privacy-sensitive cohort analysis after validating linkage. |

If this is your first time using TumorQuantAI, follow the three steps below.
The discovery step is deliberately model-free, and the smoke test limits the
first inference run to one sample and 1% of its tissue tiles.

## What TumorQuantAI does

<div class="tqa-summary-grid" markdown>

<div class="tqa-summary-card" markdown>

### 1. Reads exported slides

The portable input is a primary level-0 TIFF such as
`case_001/1_L0_rgb.tif`. Sampled runs also require its level-2 companion,
`case_001/1_L2_rgb.tif`.

</div>

<div class="tqa-summary-card" markdown>

### 2. Finds and types cells

LazySlide handles the WSI and HistoPLUS assigns cell types. Fast mode samples a
fixed percentage of tissue tiles; full mode processes all detected tissue
tiles.

</div>

<div class="tqa-summary-card" markdown>

### 3. Builds reviewable outputs

Each sample gets cell coordinates, class counts, overlays, logs, and
provenance. The cohort gets count and fraction matrices plus an audit of
complete and failed samples.

</div>

</div>

```text
exported L0 TIFF
       |
       v
slide discovery and tissue tiles
       |
       v
cell segmentation and HistoPLUS cell typing
       |
       +----> per-cell coordinates and review overlays
       |
       +----> cell types × samples count and fraction matrices
```

TumorQuantAI does **not** upload your slides, include the gated HistoPLUS
weights, create a clinical diagnosis, or turn sampled-tile counts into
estimated whole-slide counts.

## Before your first run

You need:

- Linux, Java 17 or newer, Nextflow 24.10 or newer, and Docker 24 or newer;
- enough local storage for TIFF inputs, temporary work files, and results;
- authorized access to the gated HistoPLUS model weights; and
- the verified physical resolution of each exported L0 slide in micrometres
  per pixel (MPP), unless reliable MPP metadata is embedded in the TIFF.

A GPU is recommended for inference but is not required. CPU mode is available
and is slower. Follow [Install and check your computer](INSTALL.md) before
continuing.

## Your first result, step by step

### Step 1: clone and check the host

```bash
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai

./setup_server.sh --check
./run.sh --doctor
```

The doctor command should finish with `doctor: OK`. Complete the protected
Hugging Face token or local-weight setup in the
[installation guide](INSTALL.md#hugging-face-authentication) before inference.
Never paste a model token into a command, notebook, issue, or shared log.

### Step 2: discover before inference

Arrange exported images in a dedicated input folder:

```text
/data/slides/
└── case_001/
    ├── 1_L0_rgb.tif
    └── 1_L2_rgb.tif
```

Now create the manifest without loading HistoPLUS:

```bash
./run.sh \
  --input-dir /data/slides \
  --output-dir /data/tumorquantai-discovery \
  --dry-run
```

Open:

```text
/data/tumorquantai-discovery/workflow_metadata/slides.tsv
```

Confirm that every row represents the intended primary L0 slide and that every
sample ID is unique. Correct the input layout before proceeding if a slide is
missing or an unintended file appears.

### Step 3: run one small smoke test

Ask the scanner operator or check the export record for the physical L0 MPP.
The prompt below prevents an example value from being mistaken for a real
measurement:

```bash
read -rp "Verified source L0 MPP: " SOURCE_MPP

./run.sh \
  --input-dir /data/slides \
  --output-dir /data/tumorquantai-smoke \
  --include 'case_001*' \
  --fast \
  --percent-slide 1 \
  --slide-mpp "$SOURCE_MPP" \
  --mpp 0.5 \
  --profile auto
```

`--slide-mpp` describes the source image. `--mpp 0.5` is the model-tile target
resolution. They are different settings. Omit `--slide-mpp` only when the TIFF
contains reliable physical-resolution metadata.

When the command finishes, review these files first:

| File | Why open it |
| --- | --- |
| `tumorquantai-smoke/<sample_id>/overlays/celltypes_overview_and_zoom.png` | Check tissue orientation, selected region, and whether cell markings align visually. |
| `tumorquantai-smoke/<sample_id>/summary/summary.json` | Confirm completion, sampling percentage, seed, source MPP, and detected-cell total. |
| `tumorquantai-smoke/aggregated_celltypes/sample_aggregation_audit.csv` | Confirm the sample was included rather than failed or omitted. |
| `tumorquantai-smoke/aggregated_celltypes/celltype_fractions_by_sample.csv` | View cell-type composition with cell types as rows and samples as columns. |

!!! info "What a 1% or 10% result means"
    Fast-mode raw counts are cells detected in the sampled tissue tiles. They
    are not whole-slide counts and should not be multiplied by
    `100 / percent-slide`. Use the fraction matrix for composition comparisons
    only after reviewing sampling consistency and the audit table.

If the overlay and metadata look sensible, continue with a distinct output
folder for a larger fast run or a full run. Never mix fast and full results in
the same output directory. Resume is enabled automatically when the same
command is repeated after an interruption.

## Where to go next

- [Fast versus full](RUN_MODES.md): choose a processing depth and keep
  sampled/exhaustive results separate.
- [Running and recovery](RUNNING.md): resume, resources, common problems, and
  explicit failed-sample handling.
- [Commands and tools](TOOLS.md): aggregation, reports, and advanced options.
- [Understand the outputs](OUTPUT_SCHEMA.md): precise schemas and how failures
  differ from biological zeroes.
- [Lymphoma WSI tutorial](TUTORIAL_LYMPHOMA_ZENODO.md): integrity-checked
  teaching-data workflow with fail-closed one-, four-, and 21-slide paths after the
  Zenodo record is released.
- [Clinical stratification and ML](CLINICAL_ML.md): advanced private-data
  linkage, descriptive analysis, and nested-cross-validation workflow.
- [Glossary](GLOSSARY.md): short definitions for WSI, L0/L2, MPP, sampling,
  audit tables, and resume.

For a complete list of accepted launcher options, run:

```bash
./run.sh --help
```
