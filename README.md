# TumorQuantAI

![TumorQuantAI: whole-slide images to reviewable cell-type measurements](docs/assets/tumorquantai-hero.svg)

[![CI](https://github.com/cfarkas/tumorquantai/actions/workflows/ci.yml/badge.svg)](https://github.com/cfarkas/tumorquantai/actions/workflows/ci.yml)
[![Documentation](https://github.com/cfarkas/tumorquantai/actions/workflows/docs.yml/badge.svg)](https://cfarkas.github.io/tumorquantai/)
[![Release](https://img.shields.io/github/v/release/cfarkas/tumorquantai?sort=semver)](https://github.com/cfarkas/tumorquantai/releases/latest)
[![Nextflow](https://img.shields.io/badge/workflow-Nextflow-0dc09d)](https://www.nextflow.io/)
[![Dataset DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21466410.svg)](https://doi.org/10.5281/zenodo.21466410)

TumorQuantAI is a reproducible research workflow for **H&E whole-slide images (WSIs)**. It discovers slides, records physical scale, samples tissue tiles deterministically, runs HistoPLUS cell typing, and creates cell coordinates, quality-control overlays, per-slide summaries, and cohort tables.

```text
H&E WSI -> validated scale -> tissue tiles -> HistoPLUS -> overlays + coordinates + cohort tables
```

**Research use only.** TumorQuantAI is not a diagnostic device. Predictions are not diagnoses or pathologist ground truth and must not be used alone for patient-care decisions.

Read the [complete documentation](https://cfarkas.github.io/tumorquantai/) for installation, tutorials, input formats, outputs, and troubleshooting.

## Requirements

Use Linux with [Git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git), [Python 3.10](https://www.python.org/downloads/) or newer, [Java 17](https://adoptium.net/temurin/releases/?version=17) or newer, [Nextflow 24.10](https://www.nextflow.io/docs/latest/install.html) or newer, and [Docker Engine](https://docs.docker.com/engine/install/) for the maintained container route. Install [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) only for GPU execution.

Public Zenodo download, checksum validation, MDS conversion, and model-free inspection do not require HistoPLUS access. HistoPLUS inference requires [authorized model access](https://cfarkas.github.io/tumorquantai/how-to/model-access/).

## Clone TumorQuantAI

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
```

## QuickStart Example 1: one public WSI

This example downloads one public lymphoma WSI from [Zenodo record 21466410](https://zenodo.org/records/21466410), verifies the published file, converts pyramid levels L0 and L2, and inspects the slide. The optional inference step processes a deterministic **1%** sample of detected tissue tiles.

```bash
# Create the lightweight tutorial environment.
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-tutorial.txt

# Set the only path that must be changed.
TQA_ROOT=/path/to/mounted/storage/tumorquantai-quickstart

# Create the exact quickstart download layout.
mkdir -p "$TQA_ROOT/download/raw/TumorQuantAI_LymphomaWSI_022"

# Download or resume the public manifest and fixed sample 022.
wget -c -O "$TQA_ROOT/download/tumorquantai_lymphoma_mds_manifest.csv" \
  "https://zenodo.org/records/21466410/files/tumorquantai_lymphoma_mds_manifest.csv?download=1"
wget -c -O "$TQA_ROOT/download/raw/TumorQuantAI_LymphomaWSI_022/1.mds" \
  "https://zenodo.org/records/21466410/files/TumorQuantAI_LymphomaWSI_022.mds?download=1"

# Verify the published manifest and WSI identity.
echo "ad9a9472e8beb302f8b9ba2b3359bacc  $TQA_ROOT/download/tumorquantai_lymphoma_mds_manifest.csv" \
  | md5sum -c -
test "$(stat -c %s "$TQA_ROOT/download/raw/TumorQuantAI_LymphomaWSI_022/1.mds")" \
  -eq 125350400
echo "db2988b5c6bc791510cec4127106509e604e577feafdb15b94c149043ed7067a  $TQA_ROOT/download/raw/TumorQuantAI_LymphomaWSI_022/1.mds" \
  | sha256sum -c -

# Reuse the verified files, convert L0/L2, and inspect without inference.
./tumorquantai quickstart \
  --output "$TQA_ROOT" \
  --cpu \
  --no-inference
```

The public preparation step needs no Zenodo account or token. It writes `START_HERE.html`, the verified download, converted TIFFs, and a model-free inspection report.

After HistoPLUS access is authorized, repeat the same command without `--no-inference`:

```bash
# Run the reproducible one-slide 1% HistoPLUS smoke analysis on CPU.
./tumorquantai quickstart \
  --output "$TQA_ROOT" \
  --cpu

# Verify the required one-slide outputs.
python3 examples/quickstart/verify_outputs.py \
  --tutorial-root "$TQA_ROOT"
```

Use `--gpu` instead of `--cpu` only after `./tumorquantai doctor --output "$TQA_ROOT"` confirms the NVIDIA path. The quickstart reuses verified downloads, converted TIFFs, and valid Nextflow tasks.

See [QuickStart Example 1](https://cfarkas.github.io/tumorquantai/quick_start/) for the fixed sample identity, checksums, expected folders, resume instructions, and output review order.

## Full tutorial: 21 public lymphoma WSIs at 10%

The full tutorial downloads the complete 21-slide public lymphoma collection, validates every file, converts L0/L2, inspects the roster, and processes a deterministic **10%** sample of detected tissue tiles from each slide.

```bash
# Set the only path that must be changed and remember the repository root.
TQA_ROOT=/path/to/mounted/storage/tumorquantai-lymphoma-21
REPO_ROOT="$(pwd)"
mkdir -p "$TQA_ROOT"

# Download the authoritative manifest.
wget --continue \
  --output-document "$TQA_ROOT/tumorquantai_lymphoma_mds_manifest.csv" \
  "https://zenodo.org/records/21466410/files/tumorquantai_lymphoma_mds_manifest.csv?download=1"

# Download all 21 published MDS files with resumable standard filenames.
while IFS= read -r url; do
  filename="${url##*/}"
  filename="${filename%%\?*}"
  wget --continue --output-document "$TQA_ROOT/$filename" "$url"
done < examples/lymphoma/zenodo_all_21.urls.txt

# Verify all 21 slide checksums without leaving the repository directory.
(
  cd "$TQA_ROOT"
  sha256sum -c "$REPO_ROOT/examples/lymphoma/checksums_all_21.sha256"
)

# Convert every verified MDS slide to L0 and L2 TIFF files.
python bin/mds_to_tiff.py \
  --input "$TQA_ROOT" \
  --manifest "$TQA_ROOT/tumorquantai_lymphoma_mds_manifest.csv" \
  --output-dir "$TQA_ROOT/slides" \
  --levels 0 2 \
  --expected-count 21 \
  --source-mpp 0.261780 \
  --resume

# Inspect the exact 21-slide roster before inference.
./tumorquantai inspect "$TQA_ROOT/slides" \
  --sample-sheet "$TQA_ROOT/slides/samples.csv" \
  --output "$TQA_ROOT/inspection"
```

After authorized HistoPLUS access is ready, run the 10% analysis. GPU is recommended for this cohort:

```bash
# Process a deterministic 10% of detected tissue tiles from all 21 slides.
./tumorquantai run "$TQA_ROOT/slides" \
  --sample-sheet "$TQA_ROOT/slides/samples.csv" \
  --output "$TQA_ROOT/results-10-percent" \
  --work-dir "$TQA_ROOT/work-10-percent" \
  --preset fast \
  --source-mpp 0.261780 \
  --gpu

# Verify the 21-slide audit, summaries, overlays, and cohort tables.
python3 examples/lymphoma/verify_fast21_outputs.py \
  --output "$TQA_ROOT/results-10-percent"
```

Replace `--gpu` with `--cpu` only when a much longer CPU run is acceptable. Ten-percent counts describe processed tiles; they are not validated whole-slide estimates and must not be multiplied by ten.

See the [full 21-slide tutorial](https://cfarkas.github.io/tumorquantai/full_tutorial/) for storage planning, the curl alternative, pause/resume behavior, and the files that must be reviewed before interpretation.

## Run your own WSIs

The portable input is one highest-resolution L0 TIFF and, for sampled runs, one lower-resolution L2 companion per sample:

```text
slides/
└── case_001/
    ├── 1_L0_rgb.tif
    └── 1_L2_rgb.tif
```

Inspect inputs before inference. Supply a verified source MPP when it is not embedded in the TIFF metadata.

```bash
# Inspect your own WSI folder without running HistoPLUS.
./tumorquantai inspect /path/to/slides \
  --output /path/to/tumorquantai-inspection \
  --source-mpp 0.261780

# Run a reproducible 10% analysis after reviewing the inspection report.
./tumorquantai run /path/to/slides \
  --output /path/to/tumorquantai-results \
  --work-dir /path/to/tumorquantai-work \
  --preset fast \
  --source-mpp 0.261780 \
  --cpu
```

Do not copy an MPP from another slide. Use scanner or export provenance. See [Apply TumorQuantAI to your own WSIs](https://cfarkas.github.io/tumorquantai/own_data/) for sample sheets, supported names, CPU/GPU selection, and multi-slide examples.

## Presets

| Preset | Tissue tiles processed | Recommended use |
| --- | ---: | --- |
| `smoke` | Seeded 1% from one selected slide | First authorized inference check |
| `fast` | Seeded 10% | Reproducible exploratory cohort analysis |
| `full` | 100% | Exhaustive processing after smaller runs are reviewed |

Sampling is based on detected tissue tiles, not total slide pixels. Keep the recorded random seed with every result.

## Inspect these outputs first

| Path | What it tells you |
| --- | --- |
| `START_HERE.html` | Run status and links to outputs that exist |
| `<sample>/overlays/celltypes_overview_and_zoom.png` | Visual alignment and cell-type overlay QC |
| `<sample>/summary/summary.json` | Completion, MPP, sampling, seed, model, and provenance |
| `<sample>/cell_types/class_counts.csv` | Detected-cell counts in processed tissue tiles |
| `aggregated_celltypes/sample_aggregation_audit.csv` | Included, failed, incomplete, and excluded samples |
| `aggregated_celltypes/celltype_fractions_by_sample.csv` | Within-sample cell-type fractions |
| `aggregated_celltypes/celltype_counts_by_sample.csv` | Raw detected-cell counts by completed sample |

A zero is interpretable only for a completed sample. Failed, missing, or incomplete samples remain in the audit and do not become all-zero matrix columns.

```bash
# Summarize a run and regenerate its portable report.
./tumorquantai status /path/to/tumorquantai-results
./tumorquantai report /path/to/tumorquantai-results
```

## Documentation

- [Install requirements](https://cfarkas.github.io/tumorquantai/installation/)
- [QuickStart Example 1: one public WSI](https://cfarkas.github.io/tumorquantai/quick_start/)
- [Full tutorial: 21 lymphoma WSIs at 10%](https://cfarkas.github.io/tumorquantai/full_tutorial/)
- [Apply to your own WSIs](https://cfarkas.github.io/tumorquantai/own_data/)
- [Input files and MPP](https://cfarkas.github.io/tumorquantai/inputs/)
- [Output files](https://cfarkas.github.io/tumorquantai/outputs/)
- [Troubleshooting](https://cfarkas.github.io/tumorquantai/troubleshooting/)

When reporting a bug, attach redacted `./tumorquantai doctor --json` and `./tumorquantai status OUTPUT --json` output. Never attach tokens, model weights, raw WSIs, protected health information, patient-level tables, or unredacted logs.

## Citation and license status

Cite TumorQuantAI software, the public Zenodo dataset, LazySlide, and HistoPLUS separately. See [CITATIONS.md](CITATIONS.md). The dataset DOI is not a software DOI.

This repository currently has no declared open-source license. Source visibility does not grant permission to copy, modify, or redistribute it. The public dataset and gated HistoPLUS model have separate terms.