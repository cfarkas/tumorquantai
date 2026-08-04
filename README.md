# TumorQuantAI

![TumorQuantAI: whole-slide images to reviewable cell-type measurements](docs/assets/tumorquantai-hero.svg)

[![CI](https://github.com/cfarkas/tumorquantai/actions/workflows/ci.yml/badge.svg)](https://github.com/cfarkas/tumorquantai/actions/workflows/ci.yml)
[![Documentation](https://github.com/cfarkas/tumorquantai/actions/workflows/docs.yml/badge.svg)](https://cfarkas.github.io/tumorquantai/)
[![Release](https://img.shields.io/github/v/release/cfarkas/tumorquantai?sort=semver)](https://github.com/cfarkas/tumorquantai/releases/latest)
[![Dataset DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21466410.svg)](https://doi.org/10.5281/zenodo.21466410)

TumorQuantAI is a Nextflow research workflow for H&E whole-slide images (WSIs). It validates physical scale, samples tissue reproducibly, runs HistoPLUS, and writes overlays, cell coordinates, per-slide summaries, and cohort tables.

```text
H&E WSI -> validated scale -> tissue tiles -> HistoPLUS -> overlays + coordinates + cohort tables
```

**Research use only.** TumorQuantAI is not a diagnostic device. Predictions are not diagnoses or pathologist ground truth.

## Install the `tumorquantai` command

Clone the repository, enter it, and choose one installation method. The installer creates an isolated Python environment, installs the global command under `~/.local/bin`, installs pinned Nextflow when needed, and checks the selected runtime.

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai

# Install the command and prepare the Docker route.
./tumorquantai install --docker

# Make the user-level command available in this terminal.
export PATH="$HOME/.local/bin:$PATH"

# Confirm that the command is available.
tumorquantai --version
```

Choose only one installation command:

```bash
# Installation and execution through Docker.
./tumorquantai install --docker

# Installation and execution through Singularity or Apptainer.
./tumorquantai install --singularity

# Installation through Poetry; Docker is the default scientific backend.
./tumorquantai install --poetry

# Installation and execution through Conda.
./tumorquantai install --conda
```

For a system-wide command, use `sudo ./tumorquantai install --docker --system` or replace `--docker` with the selected method. The installer does not silently modify the operating-system package manager; when Docker, Apptainer/Singularity, Conda, Java, or another system prerequisite is missing, it prints the exact component that must be installed.

## QuickStart Example 1: one public WSI

No output path needs to be edited. The default directory is created beside the repository as `tumorquantai-quickstart-one-wsi`.

```bash
# Preview the fixed one-slide plan without downloading anything.
tumorquantai quickstart --dry-run

# Download, verify, convert, and inspect sample 022 without HistoPLUS inference.
tumorquantai quickstart --no-inference

# Verify the public download, L0/L2 conversion, and model-free inspection.
python3 examples/quickstart/verify_outputs.py --preparation-only
```

The command downloads only `TumorQuantAI_LymphomaWSI_022` from Zenodo record `21466410`, verifies its published size and checksums, converts L0 and L2, and writes `START_HERE.html`. Use `--output /another/directory` only when a different storage location is needed.

After authorized HistoPLUS access is configured, run the same one-slide 1% analysis through one route:

```bash
# Run through Docker on CPU.
tumorquantai quickstart --docker --cpu

# Run through Singularity or Apptainer on CPU.
tumorquantai quickstart --singularity --cpu

# Run through the Poetry-installed command with Docker.
tumorquantai quickstart --docker --cpu

# Run through Conda on CPU.
tumorquantai quickstart --conda --cpu
```

Then verify the inference outputs:

```bash
# Verify the overlay, summary, coordinates, class counts, and aggregation audit.
python3 examples/quickstart/verify_outputs.py
```

See the [complete one-WSI QuickStart](https://cfarkas.github.io/tumorquantai/quick_start/) for sample identity, checksums, model access, output review, and resume behavior.

## Full tutorial: 21 public lymphoma WSIs at 10%

The [full tutorial](https://cfarkas.github.io/tumorquantai/full_tutorial/) downloads all 21 public lymphoma MDS files, validates every SHA-256 checksum, converts L0/L2, and processes a deterministic 10% of detected tissue tiles per slide. It uses the `fast` preset and seed `20260709`.

## Run your own WSIs

Use one L0 TIFF and, for sampled analyses, one L2 companion per sample:

```text
slides/
└── case_001/
    ├── 1_L0_rgb.tif
    └── 1_L2_rgb.tif
```

```bash
# Inspect your own slides without running HistoPLUS.
tumorquantai inspect /path/to/slides \
  --output /path/to/tumorquantai-inspection \
  --source-mpp 0.261780

# Run a reproducible 10% Docker analysis after reviewing the inspection.
tumorquantai run /path/to/slides \
  --output /path/to/tumorquantai-results \
  --work-dir /path/to/tumorquantai-work \
  --preset fast \
  --source-mpp 0.261780 \
  --docker \
  --cpu
```

Do not copy an MPP from another slide. Use scanner or export provenance.

## Inspect these outputs first

| Path | Purpose |
| --- | --- |
| `START_HERE.html` | Run status and links to outputs that exist |
| `<sample>/overlays/celltypes_overview_and_zoom.png` | Visual alignment and cell-type overlay QC |
| `<sample>/summary/summary.json` | Completion, scale, sampling, seed, model, and provenance |
| `<sample>/cell_types/class_counts.csv` | Detected-cell counts in processed tissue tiles |
| `aggregated_celltypes/sample_aggregation_audit.csv` | Included, failed, incomplete, and excluded samples |
| `aggregated_celltypes/celltype_fractions_by_sample.csv` | Within-sample cell-type fractions |

A zero is interpretable only for a completed sample. Failed or incomplete samples do not become all-zero columns.

## Documentation

- [Installation](https://cfarkas.github.io/tumorquantai/installation/)
- [QuickStart Example 1](https://cfarkas.github.io/tumorquantai/quick_start/)
- [Execution methods](https://cfarkas.github.io/tumorquantai/execution_environments/)
- [Full 21-slide tutorial](https://cfarkas.github.io/tumorquantai/full_tutorial/)
- [Apply to your own WSIs](https://cfarkas.github.io/tumorquantai/own_data/)
- [Outputs](https://cfarkas.github.io/tumorquantai/outputs/)
- [Troubleshooting](https://cfarkas.github.io/tumorquantai/troubleshooting/)
