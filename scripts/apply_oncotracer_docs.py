#!/usr/bin/env python3
"""Build the beginner-first OncoTracer-style TumorQuantAI documentation."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


README = r'''# TumorQuantAI

![TumorQuantAI: whole-slide images to auditable cell-type outputs](docs/assets/tumorquantai-hero.svg)

[![CI](https://github.com/cfarkas/tumorquantai/actions/workflows/ci.yml/badge.svg)](https://github.com/cfarkas/tumorquantai/actions/workflows/ci.yml)
[![Documentation](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://cfarkas.github.io/tumorquantai/)
[![Zenodo](https://img.shields.io/badge/Zenodo-10.5281%2Fzenodo.21466410-blue)](https://doi.org/10.5281/zenodo.21466410)
[![Docker](https://img.shields.io/badge/docker-carlosfarkas%2Flazyslide--histoplus-blue)](https://hub.docker.com/r/carlosfarkas/lazyslide-histoplus)
[![Nextflow](https://img.shields.io/badge/nextflow-%E2%89%A525.10-green)](https://www.nextflow.io/)

TumorQuantAI is a Nextflow research workflow for H&E whole-slide images (WSIs). It converts the public lymphoma Motic MDS examples to L0/L2 TIFF pairs, samples tissue reproducibly, runs HistoPLUS, and writes cell-type tables, overlays, and audit reports.

```text
WSI -> verified L0/L2 images -> tissue tiles -> HistoPLUS -> per-slide outputs -> cohort tables
```

> **Research use only.** TumorQuantAI is not a diagnostic device. HistoPLUS predictions are not pathologist ground truth.

## Requirements

Use Linux with [Git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git), [Java 17](https://adoptium.net/temurin/releases/?version=17) or newer, [Nextflow](https://www.nextflow.io/docs/latest/install.html), and [Python 3.11](https://www.python.org/downloads/). Choose Docker, Singularity/Apptainer, or Miniforge/Conda for scientific execution. Poetry is optional and manages the Python launcher.

Whole-slide images are large. Clone the repository on the mounted data filesystem that will hold the tutorial, work, cache, and result directories.

## QuickStart #1: one public lymphoma WSI

This reproducible example downloads only `TumorQuantAI_LymphomaWSI_022.mds` from [Zenodo record 21466410](https://zenodo.org/records/21466410), verifies the published hashes, converts L0 and L2, and creates a model-free inspection report.

```bash
# Clone TumorQuantAI and install the lightweight download/conversion tools.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-tutorial.txt

# Download, verify, convert, and inspect the single public WSI.
TQA_RUN="$(dirname "$PWD")/tumorquantai-quickstart-one-wsi"
./tumorquantai quickstart \
  --output "$TQA_RUN" \
  --no-inference

# Open the model-free inspection and run report.
xdg-open "$TQA_RUN/inspection/INSPECTION.html" 2>/dev/null || true
xdg-open "$TQA_RUN/START_HERE.html" 2>/dev/null || true
```

The public WSI requires no Zenodo credential. HistoPLUS inference is separate and requires approved upstream model access; follow the [model-access guide](https://cfarkas.github.io/tumorquantai/model_access/) before the next command.

## Four installation and execution methods

Choose **one** method. All four reuse the verified one-slide preparation above and run the same 1% deterministic QuickStart analysis.

### Installation and execution through Docker

```bash
# Run QuickStart #1 with the maintained CPU Docker image.
TQA_RUN="$(dirname "$PWD")/tumorquantai-quickstart-one-wsi"
./tumorquantai quickstart --output "$TQA_RUN" --docker --cpu
```

### Installation and execution through Singularity or Apptainer

```bash
# Run QuickStart #1 through Singularity or Apptainer on Linux/HPC.
TQA_RUN="$(dirname "$PWD")/tumorquantai-quickstart-one-wsi"
./tumorquantai quickstart --output "$TQA_RUN" --singularity --cpu
```

### Installation and execution through Poetry

```bash
# Install the Poetry launcher and run QuickStart #1 with Docker.
python -m pip install 'poetry>=2,<3'
poetry install --no-interaction
TQA_RUN="$(dirname "$PWD")/tumorquantai-quickstart-one-wsi"
poetry run tumorquantai quickstart --output "$TQA_RUN" --docker --cpu
```

Poetry can also forward `--singularity` or `--conda`.

### Installation and execution through Conda

```bash
# Let Nextflow create and reuse the versioned CPU Conda environment.
TQA_RUN="$(dirname "$PWD")/tumorquantai-quickstart-one-wsi"
./tumorquantai quickstart --output "$TQA_RUN" --conda --cpu
```

The versioned Conda route is CPU-only. Use Docker or Singularity/Apptainer for NVIDIA GPU execution.

## Full tutorial: 21 lymphoma WSIs at 10%

The [full tutorial](https://cfarkas.github.io/tumorquantai/full_tutorial/) downloads all 21 privacy-sanitized lymphoma WSIs from the same Zenodo record, verifies every checksum, converts L0/L2, and analyzes a deterministic 10% of detected tissue tiles per slide. The source archive is about 17.4 GB; plan at least 300 GB for download, conversion, work, caches, and results.

## Run your own slides

TumorQuantAI expects a primary L0 TIFF and, for sampled runs, an L2 companion. Inspect first, then run only after confirming the source micrometres-per-pixel (MPP).

```bash
# Inspect your slide folder without loading HistoPLUS.
SLIDES=/path/to/your/slides
RESULTS=/path/to/your/tumorquantai-results
./tumorquantai inspect "$SLIDES" \
  --output "${RESULTS}-inspection" \
  --source-mpp 0.25

# Analyze 10% of detected tissue with Docker after model access is ready.
./tumorquantai run "$SLIDES" \
  --output "$RESULTS" \
  --preset fast \
  --percent-slide 10 \
  --source-mpp 0.25 \
  --docker \
  --cpu
```

Replace `0.25` with the verified scanner/export resolution. See [Run your own data](https://cfarkas.github.io/tumorquantai/own_data/) for sample sheets, naming, and the four equivalent execution methods.

## Main outputs

- `START_HERE.html`: first report to open
- `SAMPLE/cell_types/class_counts.csv`: per-slide cell-type counts
- `SAMPLE/cell_types/cell_type_coordinates.csv`: detected-cell coordinates
- `SAMPLE/overlays/celltypes_overview_and_zoom.png`: visual quality control
- `aggregated_celltypes/celltype_counts_by_sample.csv`: cohort count matrix
- `aggregated_celltypes/celltype_fractions_by_sample.csv`: cohort fraction matrix
- `aggregated_celltypes/sample_aggregation_audit.csv`: completed, failed, and excluded samples
- `workflow_metadata/`: Nextflow trace, timeline, manifests, and logs

A failed or incomplete sample is recorded in the audit and is not converted into a biological zero.

## Public data and model access

The tutorial uses [Zenodo DOI 10.5281/zenodo.21466410](https://doi.org/10.5281/zenodo.21466410). HistoPLUS weights are not included in TumorQuantAI and must not be committed to this repository. The upstream model is gated for approved non-commercial academic/research use.

Read the [complete documentation](https://cfarkas.github.io/tumorquantai/) for installation, one-slide validation, the 21-slide tutorial, output interpretation, resuming, and troubleshooting.
'''
write("README.md", README)

INDEX = r'''# TumorQuantAI

![TumorQuantAI workflow](assets/tumorquantai-hero.svg)

TumorQuantAI turns H&E whole-slide images into auditable HistoPLUS cell-type outputs. The documentation follows the same beginner-first structure used by OncoTracer: start with one public sample, choose one execution method, inspect the result, and only then scale to a cohort.

> **Research use only.** The workflow and model outputs are not diagnoses, treatment recommendations, or pathologist ground truth.

## Start here

1. [Install the requirements](installation.md).
2. Complete [QuickStart #1 with one public WSI](quick_start.md).
3. Review `INSPECTION.html`, `START_HERE.html`, and the overlay image.
4. Follow [Run your own slides](own_data.md) or the [21-slide lymphoma tutorial](full_tutorial.md).

[![QuickStart flow](assets/tutorial/quickstart_flow.svg)](assets/tutorial/quickstart_flow.svg)

## What QuickStart #1 does

QuickStart #1 downloads the smallest public WSI in the TumorQuantAI Zenodo collection, verifies its byte size, MD5, and SHA-256, converts image levels L0 and L2, and creates a model-free inspection. After approved HistoPLUS access is configured, the same command analyzes 1% of detected tissue with a fixed random seed.

## Choose one execution method

[![Four execution methods](assets/tutorial/runtime_routes.svg)](assets/tutorial/runtime_routes.svg)

- **Docker**: maintained CPU or GPU image.
- **Singularity/Apptainer**: the same maintained image on Linux/HPC.
- **Poetry**: isolated Python launcher that forwards to Docker, Singularity, or Conda.
- **Conda**: versioned native CPU environment created and reused by Nextflow.

See [Execution environments](execution_environments.md) for installation and exact commands.

## Public lymphoma tutorial

The public collection contains 21 privacy-sanitized Motic MDS WSIs. The [full tutorial](full_tutorial.md) verifies every file, converts L0/L2, and samples exactly 10% of detected tissue per slide with the documented seed. It does not claim diagnostic labels or pathologist ground truth.

## Result review

Open results in this order:

1. `START_HERE.html`
2. `aggregated_celltypes/sample_aggregation_audit.csv`
3. per-slide overlays
4. per-slide count and coordinate tables
5. cohort count/fraction matrices
6. workflow trace and logs

[![Output guide](assets/tutorial/output_guide.svg)](assets/tutorial/output_guide.svg)

## Help

- [Model access](model_access.md)
- [Input and naming guide](own_data.md)
- [Output files](outputs.md)
- [Parameters](reference/parameters.md)
- [Resume a run](how-to/resume.md)
- [Troubleshooting](troubleshooting/index.md)
- [Validation record](validation.md)
'''
write("docs/index.md", INDEX)

INSTALL = r'''# Installation

TumorQuantAI runs on Linux. Use Java and Nextflow on the host, plus one scientific execution environment.

## 1. Install common requirements

Install:

- [Git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git)
- [Java 17](https://adoptium.net/temurin/releases/?version=17) or newer
- [Nextflow](https://www.nextflow.io/docs/latest/install.html)
- [Python 3.11](https://www.python.org/downloads/)
- `curl` or `wget`

## 2. Clone TumorQuantAI

Clone on the mounted filesystem that will hold the WSI tutorial and its work directory.

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
```

## 3. Install the lightweight host tools

The host tools download Zenodo files, convert MDS to TIFF, and inspect image metadata. Scientific inference is supplied by the selected backend.

```bash
# Create the lightweight tutorial environment.
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-tutorial.txt
```

## 4. Choose one scientific backend

### Docker

Install [Docker Engine](https://docs.docker.com/engine/install/) and confirm the daemon is accessible.

```bash
# Confirm Docker before selecting --docker.
docker --version
docker info >/dev/null
```

### Singularity or Apptainer

Install [Apptainer](https://apptainer.org/docs/admin/main/installation.html) or [SingularityCE](https://docs.sylabs.io/guides/latest/admin-guide/installation.html). TumorQuantAI automatically selects Apptainer when both are available.

```bash
# Confirm the HPC container runtime before selecting --singularity.
apptainer --version 2>/dev/null || singularity --version
```

### Poetry

Poetry manages the TumorQuantAI Python launcher; choose Docker, Singularity, or Conda for the scientific backend.

```bash
# Install the locked Poetry launcher.
python -m pip install 'poetry>=2,<3'
poetry install --no-interaction
poetry run tumorquantai --help
```

### Conda

Install [Miniforge](https://github.com/conda-forge/miniforge). Nextflow creates and caches the versioned CPU environment from `environment.yml` on the first `--conda` analysis.

```bash
# Confirm Conda before selecting --conda.
conda --version
conda config --set channel_priority strict
```

## 5. Prepare HistoPLUS access

Public Zenodo data need no credential. Real inference requires approved access to the upstream HistoPLUS model. Continue with [Model access](model_access.md). Download and conversion can be tested before model access.

## 6. Run the one-slide test

Continue with [QuickStart #1](quick_start.md). The first successful checkpoint is model-free and therefore separates data/setup errors from gated-model errors.
'''
write("docs/installation.md", INSTALL)

QUICK = r'''# QuickStart #1: one public lymphoma WSI

This tutorial processes one WSI: `TumorQuantAI_LymphomaWSI_022`. The MDS download is 125,350,400 bytes. The data are public; HistoPLUS access is required only for inference.

[![One-slide QuickStart](assets/tutorial/quickstart_flow.svg)](assets/tutorial/quickstart_flow.svg)

## Estimated time and storage

The download is about 125 MB. L0/L2 conversion expands the image to several gigabytes. Use at least 12 GB free for the model-free checkpoint and more for inference, caches, and work files. CPU inference is slower than GPU inference.

## 1. Clone and install the host tools

```bash
# Clone TumorQuantAI and install the lightweight tutorial dependencies.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-tutorial.txt
```

## 2. Download, verify, convert, and inspect

The output is a sibling of the clone so large tutorial data are never placed inside Git.

```bash
# Prepare the single WSI without model inference.
TQA_RUN="$(dirname "$PWD")/tumorquantai-quickstart-one-wsi"
./tumorquantai quickstart \
  --output "$TQA_RUN" \
  --no-inference
```

The command:

1. downloads the Zenodo manifest and sample 022;
2. checks byte size, MD5, and SHA-256;
3. converts image levels L0 and L2 to TIFF;
4. writes `converted/samples.csv`;
5. writes `inspection/INSPECTION.html`;
6. writes `START_HERE.html`.

```bash
# Confirm the one-slide preparation checkpoint.
TQA_RUN="$(dirname "$PWD")/tumorquantai-quickstart-one-wsi"
test -s "$TQA_RUN/converted/TumorQuantAI_LymphomaWSI_022_L0_rgb.tif"
test -s "$TQA_RUN/converted/TumorQuantAI_LymphomaWSI_022_L2_rgb.tif"
test -s "$TQA_RUN/inspection/INSPECTION.html"
grep -F TumorQuantAI_LymphomaWSI_022 "$TQA_RUN/inspection/inspection_manifest.csv"
```

Stop here when model access has not been approved. The data/conversion test is complete and reproducible without HistoPLUS.

## 3. Configure approved model access

Follow [Model access](model_access.md). Do not put a token in a command, commit it, upload it as an artifact, or include it in an issue.

## 4. Choose one execution method

Each method runs the same one-slide 1% deterministic analysis. Repeating the selected command resumes valid completed steps.

### Docker

```bash
# Run or resume the one-slide analysis with Docker on CPU.
TQA_RUN="$(dirname "$PWD")/tumorquantai-quickstart-one-wsi"
./tumorquantai quickstart --output "$TQA_RUN" --docker --cpu
```

For an NVIDIA system configured with the NVIDIA Container Toolkit, replace `--cpu` with `--gpu`.

### Singularity or Apptainer

```bash
# Run or resume the one-slide analysis through Singularity or Apptainer.
TQA_RUN="$(dirname "$PWD")/tumorquantai-quickstart-one-wsi"
./tumorquantai quickstart --output "$TQA_RUN" --singularity --cpu
```

On a GPU node, use `--gpu`; TumorQuantAI passes the NVIDIA option to the container runtime.

### Poetry

```bash
# Install the launcher and run the one-slide analysis through Poetry with Docker.
python -m pip install 'poetry>=2,<3'
poetry install --no-interaction
TQA_RUN="$(dirname "$PWD")/tumorquantai-quickstart-one-wsi"
poetry run tumorquantai quickstart --output "$TQA_RUN" --docker --cpu
```

Poetry also accepts `--singularity` and `--conda`.

### Conda

```bash
# Run or resume with the versioned native CPU Conda environment.
TQA_RUN="$(dirname "$PWD")/tumorquantai-quickstart-one-wsi"
./tumorquantai quickstart --output "$TQA_RUN" --conda --cpu
```

## 5. Verify the completed analysis

```bash
# Review the one-slide result and audit files.
TQA_RUN="$(dirname "$PWD")/tumorquantai-quickstart-one-wsi"
./tumorquantai status "$TQA_RUN/smoke-results"
./tumorquantai report "$TQA_RUN/smoke-results"
test -s "$TQA_RUN/smoke-results/START_HERE.html"
test -s "$TQA_RUN/smoke-results/aggregated_celltypes/sample_aggregation_audit.csv"
```

A completed smoke run records 1% tissue sampling and seed `20260709`. It is a software validation, not a whole-slide abundance estimate.
'''
write("docs/quick_start.md", QUICK)

OWN = r'''# Run your own whole-slide images

Start with model-free inspection. Do not start inference until the slide roster, L0/L2 pairing, and source MPP are correct.

## Supported layout

For sampled runs, use one L0 primary image and one L2 companion per sample:

```text
slides/
├── Patient_001_L0_rgb.tif
├── Patient_001_L2_rgb.tif
├── Patient_002_L0_rgb.tif
└── Patient_002_L2_rgb.tif
```

L0 is the high-resolution analysis image. L2 is the lower-resolution companion used during tissue sampling. The source MPP must come from scanner/export metadata or another audited source.

## 1. Inspect without inference

```bash
# Inspect the WSI folder and supply the verified source MPP when needed.
SLIDES=/path/to/your/slides
INSPECTION=/path/to/your/tumorquantai-inspection
./tumorquantai inspect "$SLIDES" \
  --output "$INSPECTION" \
  --source-mpp 0.25
```

Open `INSPECTION.html`. Confirm every intended sample, each L2 companion, and the physical scale.

## 2. Optional explicit sample sheet

Use a CSV when filenames do not provide the desired sample IDs.

```csv
sample_id,slide_path
Patient_001,Patient_001_L0_rgb.tif
Patient_002,Patient_002_L0_rgb.tif
```

Relative paths are interpreted below the input directory.

## 3. Run 10% of tissue

Choose one method. Use a new output directory for a different cohort, source MPP, sampling percentage, or seed.

### Docker

```bash
# Analyze 10% of tissue with Docker.
SLIDES=/path/to/your/slides
RESULTS=/path/to/your/tumorquantai-results
./tumorquantai run "$SLIDES" \
  --output "$RESULTS" \
  --preset fast \
  --percent-slide 10 \
  --source-mpp 0.25 \
  --docker \
  --cpu
```

### Singularity or Apptainer

```bash
# Analyze the same slides through Singularity or Apptainer.
SLIDES=/path/to/your/slides
RESULTS=/path/to/your/tumorquantai-results
./tumorquantai run "$SLIDES" \
  --output "$RESULTS" \
  --preset fast \
  --percent-slide 10 \
  --source-mpp 0.25 \
  --singularity \
  --cpu
```

### Poetry

```bash
# Launch the Docker-backed analysis through Poetry.
poetry install --no-interaction
SLIDES=/path/to/your/slides
RESULTS=/path/to/your/tumorquantai-results
poetry run tumorquantai run "$SLIDES" \
  --output "$RESULTS" \
  --preset fast \
  --percent-slide 10 \
  --source-mpp 0.25 \
  --docker \
  --cpu
```

### Conda

```bash
# Analyze the same slides with the versioned native CPU environment.
SLIDES=/path/to/your/slides
RESULTS=/path/to/your/tumorquantai-results
./tumorquantai run "$SLIDES" \
  --output "$RESULTS" \
  --preset fast \
  --percent-slide 10 \
  --source-mpp 0.25 \
  --conda \
  --cpu
```

Replace `0.25` with the verified source MPP. Add `--sample-sheet FILE` when using an explicit mapping.

## 4. Review and resume

```bash
# Check status, regenerate the report, or resume with the same run command.
RESULTS=/path/to/your/tumorquantai-results
./tumorquantai status "$RESULTS"
./tumorquantai report "$RESULTS"
```

Repeat the same selected run command to resume. Do not delete the Nextflow work directory until the outputs have been reviewed and backed up.
'''
write("docs/own_data.md", OWN)

FULL = r'''# Full tutorial: 21 lymphoma WSIs at 10%

This tutorial downloads all 21 privacy-sanitized lymphoma WSIs from Zenodo record 21466410, verifies every file, converts L0/L2, inspects the cohort, and analyzes a deterministic 10% of detected tissue per slide.

[![Full 21-slide tutorial](assets/tutorial/full_tutorial_flow.svg)](assets/tutorial/full_tutorial_flow.svg)

## Resources

The source MDS archive totals 17,370,771,968 bytes (about 17.4 GB). L0/L2 conversion can approach 142 GB. Plan at least 300 GB for download, conversion, model caches, Nextflow work, and final results. Start with [QuickStart #1](quick_start.md).

The public collection has no diagnostic annotations or pathologist ground truth.

## 1. Clone and install the host tools

Clone on the large mounted filesystem.

```bash
# Clone TumorQuantAI and install the public-data tools.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-tutorial.txt
```

## 2. Download all 21 MDS files

```bash
# Download the manifest and every standard Zenodo filename.
TQA_DATA="$(dirname "$PWD")/tumorquantai-lymphoma-21"
mkdir -p "$TQA_DATA"
wget -c -O "$TQA_DATA/tumorquantai_lymphoma_mds_manifest.csv" \
  'https://zenodo.org/records/21466410/files/tumorquantai_lymphoma_mds_manifest.csv?download=1'

while IFS= read -r url; do
  filename="${url##*/}"
  filename="${filename%%\?*}"
  wget -c -O "$TQA_DATA/$filename" "$url"
done < examples/lymphoma/zenodo_all_21.urls.txt
```

## 3. Verify every download

```bash
# Verify the public manifest and all 21 slide SHA-256 values.
TQA_DATA="$(dirname "$PWD")/tumorquantai-lymphoma-21"
ROOT="$PWD"
(
  cd "$TQA_DATA"
  echo 'ad9a9472e8beb302f8b9ba2b3359bacc  tumorquantai_lymphoma_mds_manifest.csv' | md5sum -c -
  sha256sum -c "$ROOT/examples/lymphoma/checksums_all_21.sha256"
)
```

Stop when any line does not print `OK`.

## 4. Convert L0/L2 and inspect the cohort

```bash
# Convert all verified MDS files and inspect the 21-slide roster.
TQA_DATA="$(dirname "$PWD")/tumorquantai-lymphoma-21"
python bin/mds_to_tiff.py \
  --input "$TQA_DATA" \
  --manifest "$TQA_DATA/tumorquantai_lymphoma_mds_manifest.csv" \
  --output-dir "$TQA_DATA/slides" \
  --levels 0 2 \
  --expected-count 21 \
  --source-mpp 0.261780 \
  --resume

./tumorquantai inspect "$TQA_DATA/slides" \
  --sample-sheet "$TQA_DATA/slides/samples.csv" \
  --output "$TQA_DATA/inspection" \
  --source-mpp 0.261780
```

Require exactly 21 unique complete L0/L2 pairs in `inspection/inspection_manifest.csv`.

## 5. Configure approved HistoPLUS access

Complete [Model access](model_access.md). Public downloads and conversion do not require a Hugging Face token; inference does.

## 6. Analyze 10% of detected tissue

Choose one method. The `fast` preset and explicit `--percent-slide 10` record the intended sampling fraction. The default seed is `20260709`.

### Docker

```bash
# Run all 21 slides at 10% through Docker.
TQA_DATA="$(dirname "$PWD")/tumorquantai-lymphoma-21"
./tumorquantai run "$TQA_DATA/slides" \
  --sample-sheet "$TQA_DATA/slides/samples.csv" \
  --output "$TQA_DATA/results-10-percent" \
  --work-dir "$TQA_DATA/work-docker-10-percent" \
  --preset fast \
  --percent-slide 10 \
  --source-mpp 0.261780 \
  --docker \
  --cpu
```

### Singularity or Apptainer

```bash
# Run the same 21-slide analysis through Singularity or Apptainer.
TQA_DATA="$(dirname "$PWD")/tumorquantai-lymphoma-21"
./tumorquantai run "$TQA_DATA/slides" \
  --sample-sheet "$TQA_DATA/slides/samples.csv" \
  --output "$TQA_DATA/results-10-percent" \
  --work-dir "$TQA_DATA/work-singularity-10-percent" \
  --preset fast \
  --percent-slide 10 \
  --source-mpp 0.261780 \
  --singularity \
  --cpu
```

### Poetry

```bash
# Launch the Docker-backed 21-slide analysis through Poetry.
poetry install --no-interaction
TQA_DATA="$(dirname "$PWD")/tumorquantai-lymphoma-21"
poetry run tumorquantai run "$TQA_DATA/slides" \
  --sample-sheet "$TQA_DATA/slides/samples.csv" \
  --output "$TQA_DATA/results-10-percent" \
  --work-dir "$TQA_DATA/work-poetry-10-percent" \
  --preset fast \
  --percent-slide 10 \
  --source-mpp 0.261780 \
  --docker \
  --cpu
```

### Conda

```bash
# Run all 21 slides at 10% with the versioned CPU Conda environment.
TQA_DATA="$(dirname "$PWD")/tumorquantai-lymphoma-21"
./tumorquantai run "$TQA_DATA/slides" \
  --sample-sheet "$TQA_DATA/slides/samples.csv" \
  --output "$TQA_DATA/results-10-percent" \
  --work-dir "$TQA_DATA/work-conda-10-percent" \
  --preset fast \
  --percent-slide 10 \
  --source-mpp 0.261780 \
  --conda \
  --cpu
```

Use `--gpu` with Docker or Singularity/Apptainer only after GPU visibility is confirmed.

## 7. Verify the cohort result

```bash
# Review the final run and require an explicit 21-sample aggregation audit.
TQA_DATA="$(dirname "$PWD")/tumorquantai-lymphoma-21"
RESULTS="$TQA_DATA/results-10-percent"
./tumorquantai status "$RESULTS"
./tumorquantai report "$RESULTS"
test -s "$RESULTS/START_HERE.html"
test -s "$RESULTS/aggregated_celltypes/sample_aggregation_audit.csv"
```

Review failed or incomplete samples before using cohort matrices. A failure is not a zero-cell biological result.
'''
write("docs/full_tutorial.md", FULL)

ENVIRONMENTS = r'''# Execution environments

All methods launch the same Nextflow workflow. Choose one method for a run and keep its work directory when using resume.

[![Runtime routes](assets/tutorial/runtime_routes.svg)](assets/tutorial/runtime_routes.svg)

| Method | Scientific software | CPU | NVIDIA GPU | Typical use |
| --- | --- | ---: | ---: | --- |
| Docker | maintained image | yes | yes | workstation/server |
| Singularity/Apptainer | same maintained image | yes | yes | HPC |
| Poetry | Python launcher + selected backend | yes | depends on backend | isolated launcher |
| Conda | `environment.yml` | yes | no | native CPU environment |

## Docker

```bash
# Run a 10% analysis with Docker.
./tumorquantai run /path/to/slides \
  --output /path/to/results \
  --preset fast \
  --source-mpp 0.25 \
  --docker \
  --cpu
```

## Singularity or Apptainer

The single `--singularity` option uses Apptainer when `apptainer` is available and otherwise uses Singularity.

```bash
# Run the same analysis through the HPC container runtime.
./tumorquantai run /path/to/slides \
  --output /path/to/results \
  --preset fast \
  --source-mpp 0.25 \
  --singularity \
  --cpu
```

## Poetry

Poetry does not replace the scientific backend. It installs a reproducible Python launcher, then forwards to Docker, Singularity, or Conda.

```bash
# Install the launcher and forward the analysis to Docker.
poetry install --no-interaction
poetry run tumorquantai run /path/to/slides \
  --output /path/to/results \
  --preset fast \
  --source-mpp 0.25 \
  --docker \
  --cpu
```

## Conda

Nextflow creates the environment from `environment.yml` on the first run and reuses it later. Set `NXF_CONDA_CACHEDIR` to a large persistent path when needed.

```bash
# Run with the versioned native CPU environment.
export NXF_CONDA_CACHEDIR=/path/to/persistent/conda-cache
./tumorquantai run /path/to/slides \
  --output /path/to/results \
  --preset fast \
  --source-mpp 0.25 \
  --conda \
  --cpu
```

## Resume

Repeat the same command with the same output and work directory. TumorQuantAI records the selected backend, compute profile, sampling, source MPP, seed, model revision, and container/environment identity in the run manifest.
'''
write("docs/execution_environments.md", ENVIRONMENTS)

MODEL = r'''# HistoPLUS model access

TumorQuantAI does not distribute HistoPLUS weights. The public Zenodo slides can be downloaded, verified, converted, and inspected without a model credential. Inference requires access approved by the upstream model provider.

## 1. Request access

Open the [HistoPLUS model page](https://huggingface.co/Owkin-Bioptimus/histoplus), review the current terms, and request access with the account that will run TumorQuantAI. The upstream model is restricted to approved non-commercial academic/research use.

## 2. Store a token privately

After access is approved, create a private token file without placing the token in shell history.

```bash
# Read the token silently and store it with owner-only permissions.
mkdir -p "$HOME/.config/tumorquantai"
read -rsp 'Hugging Face token: ' TQA_TOKEN
echo
install -m 600 /dev/null "$HOME/.config/tumorquantai/hf_token"
printf '%s' "$TQA_TOKEN" > "$HOME/.config/tumorquantai/hf_token"
unset TQA_TOKEN
```

Alternatively, point `--local-weight` at an authorized local HistoPLUS weight file. TumorQuantAI hashes the file for provenance but does not copy it into results.

## 3. Protect credentials

Never:

- commit the token or model weight;
- put a token directly on the command line;
- upload credentials as workflow artifacts;
- paste credentials into issues or logs;
- redistribute gated weights.

## 4. Run inference

Return to [QuickStart #1](quick_start.md) and choose Docker, Singularity/Apptainer, Poetry, or Conda.
'''
write("docs/model_access.md", MODEL)

OUTPUTS = r'''# Output files

[![Output review order](assets/tutorial/output_guide.svg)](assets/tutorial/output_guide.svg)

## Open first

`START_HERE.html` summarizes run status, completed samples, failures, exclusions, provenance, and the first files to review.

## Per-slide outputs

```text
SAMPLE/
├── cell_types/
│   ├── class_counts.csv
│   └── cell_type_coordinates.csv
├── overlays/
│   ├── celltypes_overview_and_zoom.png
│   └── celltypes_overview_and_zoom.pdf
└── summary/
    └── summary.json
```

Counts are predictions from HistoPLUS. Coordinates are in the workflow output coordinate system documented by the sample summary. Review overlays before interpreting tables.

## Cohort outputs

```text
aggregated_celltypes/
├── celltype_counts_by_sample.csv
├── celltype_fractions_by_sample.csv
├── celltype_counts_long.csv
├── sample_aggregation_audit.csv
└── workflow_aggregation_manifest.csv
```

Numeric matrices contain completed samples only. `sample_aggregation_audit.csv` is authoritative for failed, incomplete, excluded, and completed samples.

## Workflow metadata

`workflow_metadata/` contains the input manifest, TumorQuantAI run manifest, Nextflow trace, report, timeline, logs, and preflight inspection. Preserve it with any result used in a figure or analysis.

## Interpretation limits

Sampling percentages refer to detected tissue tiles, not to the fraction of every image pixel. The 1% QuickStart is a software test; it is not a whole-slide abundance estimate. The 10% tutorial is a reproducible sampled analysis, not a clinical validation.
'''
write("docs/outputs.md", OUTPUTS)

VALIDATION = r'''# Validation record

TumorQuantAI separates public-data preparation, runtime portability, and gated-model inference so failures are attributable.

## Public one-slide acceptance

Sample `TumorQuantAI_LymphomaWSI_022` is downloaded from Zenodo, checked against the published size, MD5, and SHA-256, converted to L0/L2 TIFFs, and inspected as exactly one sample.

## Runtime validation

Continuous integration checks:

- Docker profile parsing and one-process execution;
- Singularity/Apptainer profile parsing and container execution;
- Poetry installation and launcher invocation;
- Conda profile parsing and environment creation;
- model-free one-slide download, conversion, and inspection;
- command-box Bash syntax and strict MkDocs builds.

## Gated inference acceptance

A real CPU one-slide HistoPLUS smoke run was completed during the public-workflow acceptance work before this documentation overhaul. It used the authorized local-weight route, 1% tissue sampling, seed `20260709`, and sample 022. The weight was not committed or uploaded.

The public CI intentionally does not contain a HistoPLUS token or weight. Users must complete the upstream access process before reproducing inference.
'''
write("docs/validation.md", VALIDATION)

# Explanatory SVGs are plain text so they remain version-controlled and accessible.
write(
    "docs/assets/tumorquantai-hero.svg",
    r'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 440" role="img" aria-labelledby="title desc">
<title id="title">TumorQuantAI workflow</title><desc id="desc">Whole-slide images are verified, converted, sampled, analyzed with HistoPLUS, and summarized in auditable outputs.</desc>
<rect width="1200" height="440" rx="24" fill="#f7f9fc"/>
<text x="60" y="68" font-family="Arial,sans-serif" font-size="38" font-weight="700" fill="#172033">TumorQuantAI</text>
<text x="60" y="105" font-family="Arial,sans-serif" font-size="20" fill="#44506a">H&amp;E whole-slide images to reproducible cell-type outputs</text>
<g font-family="Arial,sans-serif" text-anchor="middle">
<rect x="55" y="170" width="190" height="130" rx="18" fill="#dceafe" stroke="#456fb5" stroke-width="3"/><text x="150" y="220" font-size="24" font-weight="700" fill="#173a70">WSI</text><text x="150" y="252" font-size="16" fill="#294d7d">MDS or L0/L2 TIFF</text><text x="150" y="278" font-size="16" fill="#294d7d">verified source MPP</text>
<rect x="300" y="170" width="190" height="130" rx="18" fill="#e8f4e5" stroke="#4b8b4a" stroke-width="3"/><text x="395" y="220" font-size="24" font-weight="700" fill="#245226">Prepare</text><text x="395" y="252" font-size="16" fill="#356537">checksums + L0/L2</text><text x="395" y="278" font-size="16" fill="#356537">input manifest</text>
<rect x="545" y="170" width="190" height="130" rx="18" fill="#fff0d8" stroke="#b57b28" stroke-width="3"/><text x="640" y="220" font-size="24" font-weight="700" fill="#6c4310">Sample</text><text x="640" y="252" font-size="16" fill="#80561d">1%, 10%, or 100%</text><text x="640" y="278" font-size="16" fill="#80561d">fixed random seed</text>
<rect x="790" y="170" width="190" height="130" rx="18" fill="#efe4fa" stroke="#7d4aa6" stroke-width="3"/><text x="885" y="220" font-size="24" font-weight="700" fill="#4d246e">HistoPLUS</text><text x="885" y="252" font-size="16" fill="#63377f">detection + classes</text><text x="885" y="278" font-size="16" fill="#63377f">gated model access</text>
<rect x="1035" y="170" width="110" height="130" rx="18" fill="#ffe5e5" stroke="#a64b4b" stroke-width="3"/><text x="1090" y="215" font-size="21" font-weight="700" fill="#6f2929">Results</text><text x="1090" y="248" font-size="15" fill="#7d3838">tables</text><text x="1090" y="272" font-size="15" fill="#7d3838">overlays</text><text x="1090" y="294" font-size="15" fill="#7d3838">audit</text>
</g>
<g stroke="#667085" stroke-width="4" fill="none"><path d="M245 235h55"/><path d="M490 235h55"/><path d="M735 235h55"/><path d="M980 235h55"/></g>
<g fill="#667085"><path d="M294 225l16 10-16 10z"/><path d="M539 225l16 10-16 10z"/><path d="M784 225l16 10-16 10z"/><path d="M1029 225l16 10-16 10z"/></g>
<text x="600" y="370" font-family="Arial,sans-serif" font-size="18" text-anchor="middle" fill="#44506a">Docker • Singularity/Apptainer • Poetry • Conda</text>
</svg>''',
)
write(
    "docs/assets/tutorial/quickstart_flow.svg",
    r'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 300" role="img" aria-labelledby="title desc"><title id="title">One-slide QuickStart flow</title><desc id="desc">Clone, download sample 022, verify it, convert L0 and L2, inspect, then optionally infer one percent of tissue.</desc><rect width="1200" height="300" rx="20" fill="#fbfcfe"/><g font-family="Arial,sans-serif" text-anchor="middle" font-size="17"><g fill="#e5efff" stroke="#5277b8" stroke-width="2"><rect x="35" y="95" width="150" height="90" rx="15"/><rect x="230" y="95" width="150" height="90" rx="15"/><rect x="425" y="95" width="150" height="90" rx="15"/><rect x="620" y="95" width="150" height="90" rx="15"/><rect x="815" y="95" width="150" height="90" rx="15"/><rect x="1010" y="95" width="155" height="90" rx="15"/></g><text x="110" y="132" font-weight="700">Clone</text><text x="110" y="157">install host tools</text><text x="305" y="132" font-weight="700">Download</text><text x="305" y="157">WSI 022</text><text x="500" y="132" font-weight="700">Verify</text><text x="500" y="157">size + hashes</text><text x="695" y="132" font-weight="700">Convert</text><text x="695" y="157">L0 + L2 TIFF</text><text x="890" y="132" font-weight="700">Inspect</text><text x="890" y="157">model-free report</text><text x="1087" y="125" font-weight="700">Infer</text><text x="1087" y="150">1% tissue</text><text x="1087" y="172">after access</text></g><g stroke="#6b7280" stroke-width="3" fill="#6b7280"><path d="M185 140h45"/><path d="M380 140h45"/><path d="M575 140h45"/><path d="M770 140h45"/><path d="M965 140h45"/></g><text x="600" y="55" font-family="Arial,sans-serif" font-size="28" font-weight="700" text-anchor="middle" fill="#172033">QuickStart #1 — one public lymphoma WSI</text><text x="600" y="245" font-family="Arial,sans-serif" font-size="17" text-anchor="middle" fill="#44506a">Public data preparation is credential-free; HistoPLUS inference is gated separately.</text></svg>''',
)
write(
    "docs/assets/tutorial/runtime_routes.svg",
    r'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1100 360" role="img" aria-labelledby="title desc"><title id="title">Four execution routes</title><desc id="desc">One TumorQuantAI workflow can use Docker, Singularity or Apptainer, Poetry with a selected backend, or Conda.</desc><rect width="1100" height="360" rx="20" fill="#fafbfe"/><text x="550" y="48" font-family="Arial,sans-serif" font-size="28" font-weight="700" text-anchor="middle" fill="#172033">One workflow, four execution methods</text><rect x="425" y="80" width="250" height="72" rx="15" fill="#e8eef9" stroke="#536ea4" stroke-width="3"/><text x="550" y="113" font-family="Arial,sans-serif" font-size="21" font-weight="700" text-anchor="middle" fill="#283d68">TumorQuantAI + Nextflow</text><text x="550" y="137" font-family="Arial,sans-serif" font-size="15" text-anchor="middle" fill="#43577d">same inputs and outputs</text><g font-family="Arial,sans-serif" text-anchor="middle"><rect x="55" y="230" width="210" height="85" rx="15" fill="#ddecff" stroke="#3f72b5" stroke-width="3"/><text x="160" y="267" font-size="22" font-weight="700" fill="#194d82">Docker</text><text x="160" y="293" font-size="15" fill="#2f5e8d">CPU or NVIDIA GPU</text><rect x="315" y="230" width="210" height="85" rx="15" fill="#e7f3e5" stroke="#4f8a4b" stroke-width="3"/><text x="420" y="262" font-size="20" font-weight="700" fill="#2e5e2c">Singularity</text><text x="420" y="286" font-size="15" fill="#3d713a">or Apptainer • HPC</text><rect x="575" y="230" width="210" height="85" rx="15" fill="#fff0dc" stroke="#b47a2a" stroke-width="3"/><text x="680" y="267" font-size="22" font-weight="700" fill="#70470f">Poetry</text><text x="680" y="293" font-size="15" fill="#80591f">isolated launcher</text><rect x="835" y="230" width="210" height="85" rx="15" fill="#eee4f8" stroke="#77509b" stroke-width="3"/><text x="940" y="267" font-size="22" font-weight="700" fill="#4d2b68">Conda</text><text x="940" y="293" font-size="15" fill="#67447f">versioned CPU env</text></g><g stroke="#667085" stroke-width="3" fill="none"><path d="M550 152v40H160v38"/><path d="M550 192H420v38"/><path d="M550 192h130v38"/><path d="M550 192h390v38"/></g></svg>''',
)
write(
    "docs/assets/tutorial/full_tutorial_flow.svg",
    r'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 320" role="img" aria-labelledby="title desc"><title id="title">Full lymphoma tutorial flow</title><desc id="desc">Twenty-one Zenodo MDS files are verified, converted to L0 and L2, sampled at ten percent, and aggregated with an audit.</desc><rect width="1200" height="320" rx="20" fill="#fbfcfe"/><text x="600" y="48" font-family="Arial,sans-serif" font-size="28" font-weight="700" text-anchor="middle" fill="#172033">Full tutorial — 21 lymphoma WSIs at 10%</text><g font-family="Arial,sans-serif" text-anchor="middle"><rect x="45" y="105" width="190" height="105" rx="16" fill="#dceafe" stroke="#456fb5" stroke-width="3"/><text x="140" y="145" font-size="22" font-weight="700" fill="#173a70">21 MDS files</text><text x="140" y="174" font-size="15" fill="#294d7d">Zenodo • 17.4 GB</text><rect x="285" y="105" width="190" height="105" rx="16" fill="#e8f4e5" stroke="#4b8b4a" stroke-width="3"/><text x="380" y="145" font-size="22" font-weight="700" fill="#245226">Verify</text><text x="380" y="174" font-size="15" fill="#356537">manifest + SHA-256</text><rect x="525" y="105" width="190" height="105" rx="16" fill="#fff0d8" stroke="#b57b28" stroke-width="3"/><text x="620" y="145" font-size="22" font-weight="700" fill="#6c4310">Convert</text><text x="620" y="174" font-size="15" fill="#80561d">21 L0/L2 pairs</text><rect x="765" y="105" width="190" height="105" rx="16" fill="#efe4fa" stroke="#7d4aa6" stroke-width="3"/><text x="860" y="145" font-size="22" font-weight="700" fill="#4d246e">Sample 10%</text><text x="860" y="174" font-size="15" fill="#63377f">seed 20260709</text><rect x="1005" y="105" width="150" height="105" rx="16" fill="#ffe5e5" stroke="#a64b4b" stroke-width="3"/><text x="1080" y="140" font-size="21" font-weight="700" fill="#6f2929">Aggregate</text><text x="1080" y="168" font-size="15" fill="#7d3838">counts + fractions</text><text x="1080" y="190" font-size="15" fill="#7d3838">audit</text></g><g stroke="#667085" stroke-width="4" fill="#667085"><path d="M235 157h50"/><path d="M475 157h50"/><path d="M715 157h50"/><path d="M955 157h50"/></g><text x="600" y="270" font-family="Arial,sans-serif" font-size="17" text-anchor="middle" fill="#44506a">Choose Docker, Singularity/Apptainer, Poetry, or Conda; use one route and retain its work directory.</text></svg>''',
)
write(
    "docs/assets/tutorial/output_guide.svg",
    r'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1050 300" role="img" aria-labelledby="title desc"><title id="title">TumorQuantAI output review order</title><desc id="desc">Review the start report, aggregation audit, overlays, tables, and workflow metadata in order.</desc><rect width="1050" height="300" rx="20" fill="#fbfcfe"/><text x="525" y="48" font-family="Arial,sans-serif" font-size="28" font-weight="700" text-anchor="middle" fill="#172033">Review results in this order</text><g font-family="Arial,sans-serif" text-anchor="middle"><rect x="35" y="105" width="165" height="92" rx="15" fill="#dceafe" stroke="#456fb5" stroke-width="3"/><text x="117" y="140" font-size="18" font-weight="700">1. START_HERE</text><text x="117" y="169" font-size="14">run status</text><rect x="240" y="105" width="165" height="92" rx="15" fill="#e8f4e5" stroke="#4b8b4a" stroke-width="3"/><text x="322" y="140" font-size="18" font-weight="700">2. Audit</text><text x="322" y="169" font-size="14">included / failed</text><rect x="445" y="105" width="165" height="92" rx="15" fill="#fff0d8" stroke="#b57b28" stroke-width="3"/><text x="527" y="140" font-size="18" font-weight="700">3. Overlays</text><text x="527" y="169" font-size="14">visual QC</text><rect x="650" y="105" width="165" height="92" rx="15" fill="#efe4fa" stroke="#7d4aa6" stroke-width="3"/><text x="732" y="140" font-size="18" font-weight="700">4. Tables</text><text x="732" y="169" font-size="14">counts + coordinates</text><rect x="855" y="105" width="165" height="92" rx="15" fill="#ffe5e5" stroke="#a64b4b" stroke-width="3"/><text x="937" y="140" font-size="18" font-weight="700">5. Metadata</text><text x="937" y="169" font-size="14">trace + logs</text></g><g stroke="#667085" stroke-width="3"><path d="M200 151h40"/><path d="M405 151h40"/><path d="M610 151h40"/><path d="M815 151h40"/></g><text x="525" y="245" font-family="Arial,sans-serif" font-size="16" text-anchor="middle" fill="#44506a">Never treat a failed or incomplete sample as a biological zero.</text></svg>''',
)

CSS = r''':root {
  --md-primary-fg-color: #223b63;
  --md-accent-fg-color: #456fb5;
}
.md-typeset h1 { font-weight: 750; letter-spacing: -0.02em; }
.md-typeset h2 { font-weight: 700; }
.md-typeset code { border-radius: 0.2rem; }
.md-typeset .highlight pre { border: 1px solid #d9e0ea; }
.md-typeset img { max-width: 100%; height: auto; }
.md-typeset table:not([class]) { font-size: 0.82rem; }
'''
write("docs/stylesheets/tumorquantai.css", CSS)

MKDOCS = r'''site_name: TumorQuantAI
site_description: Reproducible HistoPLUS analysis of H&E whole-slide images
site_author: TumorQuantAI developers
site_url: https://cfarkas.github.io/tumorquantai/
repo_name: cfarkas/tumorquantai
repo_url: https://github.com/cfarkas/tumorquantai
edit_uri: edit/main/docs/

theme:
  name: material
  features:
    - navigation.tabs
    - navigation.sections
    - navigation.expand
    - navigation.top
    - toc.follow
    - content.code.copy
    - content.action.edit
    - search.suggest
    - search.highlight
  palette:
    - media: "(prefers-color-scheme: light)"
      scheme: default
      primary: indigo
      accent: blue

extra_css:
  - stylesheets/tumorquantai.css

markdown_extensions:
  - admonition
  - attr_list
  - tables
  - toc:
      permalink: true
  - pymdownx.details
  - pymdownx.superfences
  - pymdownx.highlight

nav:
  - Home: index.md
  - Getting Started:
      - 1. Installation: installation.md
      - 2. QuickStart #1 — One WSI: quick_start.md
      - 3. Run Your Own Slides: own_data.md
      - 4. Model Access: model_access.md
  - Full Tutorial:
      - 21 Lymphoma WSIs at 10%: full_tutorial.md
  - Run and Configure:
      - Execution Environments: execution_environments.md
      - Input Discovery: reference/input-discovery.md
      - Parameters: reference/parameters.md
      - Sampling and Randomness: explanation/sampling-randomness.md
      - Image Levels and MPP: explanation/wsi-levels-mpp.md
      - Resume a Run: how-to/resume.md
  - Understand Results:
      - Output Files: outputs.md
      - Review Overlays: how-to/review-overlays.md
      - Counts and Fractions: explanation/counts-fractions.md
      - Validation Record: validation.md
  - Help and About:
      - Troubleshooting: troubleshooting/index.md
      - Security and Privacy: SECURITY.md
      - Glossary: GLOSSARY.md
      - Citation: explanation/scientific-scope.md
      - Maintainer Guide: maintainer/README.md

plugins:
  - search

validation:
  omitted_files: warn
  absolute_links: warn
  unrecognized_links: warn
'''
write("mkdocs.yml", MKDOCS)

# Convert legacy tilde fences to the same Markdown syntax used by OncoTracer.
for path in (ROOT / "docs").rglob("*.md"):
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"^~~~([A-Za-z0-9_-]*)\s*$", r"```\1", text, flags=re.MULTILINE)
    path.write_text(text, encoding="utf-8")

TEST = r'''#!/usr/bin/env python3
"""Check the OncoTracer-style beginner documentation and command boxes."""

from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = (
    "README.md",
    "docs/index.md",
    "docs/installation.md",
    "docs/quick_start.md",
    "docs/own_data.md",
    "docs/full_tutorial.md",
    "docs/execution_environments.md",
    "docs/model_access.md",
    "docs/outputs.md",
    "docs/validation.md",
)
BASH = re.compile(r"```bash\s*\n(.*?)```", re.DOTALL)


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


for relative in CANONICAL:
    path = ROOT / relative
    if not path.is_file():
        fail(f"missing canonical page: {relative}")
    text = path.read_text(encoding="utf-8")
    if "REPO_DIR=" in text or "$REPO_DIR" in text:
        fail(f"verbose repository variable in {relative}")
    if "git clone https://github.com/cfarkas/tumorquantai.git" not in text and relative in {
        "README.md", "docs/installation.md", "docs/quick_start.md", "docs/full_tutorial.md"
    }:
        fail(f"missing clone command in {relative}")
    for number, block in enumerate(BASH.findall(text), start=1):
        first = next((line.strip() for line in block.splitlines() if line.strip()), "")
        if not first.startswith("#"):
            fail(f"Bash block {number} in {relative} does not start with #")
        checked = subprocess.run(
            ["bash", "-n"], input=block, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if checked.returncode:
            fail(f"invalid Bash block {number} in {relative}: {checked.stderr.strip()}")

quickstart = (ROOT / "docs/quick_start.md").read_text(encoding="utf-8")
for required in (
    "TumorQuantAI_LymphomaWSI_022", "--no-inference", "--docker",
    "--singularity", "poetry run tumorquantai", "--conda", "1%",
):
    if required not in quickstart:
        fail(f"QuickStart is missing {required}")

full = (ROOT / "docs/full_tutorial.md").read_text(encoding="utf-8")
for required in ("21 lymphoma WSIs", "--preset fast", "--percent-slide 10", "results-10-percent"):
    if required not in full:
        fail(f"full tutorial is missing {required}")

for relative in (
    "docs/assets/tumorquantai-hero.svg",
    "docs/assets/tutorial/quickstart_flow.svg",
    "docs/assets/tutorial/runtime_routes.svg",
    "docs/assets/tutorial/full_tutorial_flow.svg",
    "docs/assets/tutorial/output_guide.svg",
):
    try:
        ET.parse(ROOT / relative)
    except (ET.ParseError, OSError) as exc:
        fail(f"invalid explanatory figure {relative}: {exc}")

print("PASS: beginner pages, four execution routes, figures, and Bash boxes are valid")
'''
write("tests/test_oncotracer_style_docs.py", TEST)

ci_path = ROOT / ".github/workflows/ci.yml"
ci = ci_path.read_text(encoding="utf-8")
anchor = "          python scripts/check_repository_hygiene.py\n"
if anchor not in ci:
    raise SystemExit("Unable to extend documentation CI")
ci = ci.replace(anchor, anchor + "          python tests/test_oncotracer_style_docs.py\n", 1)
ci_path.write_text(ci, encoding="utf-8")

print("OncoTracer-style documentation prepared.")
