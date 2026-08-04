# TumorQuantAI

![TumorQuantAI: whole-slide images to reviewable cell-type measurements](docs/assets/tumorquantai-hero.svg)

[![CI](https://github.com/cfarkas/tumorquantai/actions/workflows/ci.yml/badge.svg)](https://github.com/cfarkas/tumorquantai/actions/workflows/ci.yml)
[![Documentation](https://github.com/cfarkas/tumorquantai/actions/workflows/docs.yml/badge.svg)](https://cfarkas.github.io/tumorquantai/)
[![Release](https://img.shields.io/github/v/release/cfarkas/tumorquantai?sort=semver)](https://github.com/cfarkas/tumorquantai/releases/latest)
[![Dataset DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21466410.svg)](https://doi.org/10.5281/zenodo.21466410)

TumorQuantAI is a Nextflow workflow for H&E whole-slide images (WSIs). It validates physical scale, samples tissue reproducibly, runs HistoPLUS, and writes overlays, cell coordinates, per-slide summaries, and cohort tables.

```text
H&E WSI -> validated scale -> tissue tiles -> HistoPLUS -> overlays + coordinates + cohort tables
```

## Install the `tumorquantai` command

Clone the repository, enter it, and choose one installation method. The installer creates the managed command under `~/.local/bin`, installs pinned Nextflow when needed, and checks the selected runtime.

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai

# Install the command and prepare the Docker route.
./tumorquantai install --docker

# Make the installed command available in this terminal.
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

For a system-wide command, use `sudo ./tumorquantai install --docker --system` or replace `--docker` with the selected method. Do not create another tutorial virtual environment after this installation.

## Configure HistoPLUS access from Hugging Face

HistoPLUS is gated. First open the [HistoPLUS model page](https://huggingface.co/Owkin-Bioptimus/histoplus), sign in, and request access. After access is approved, create a Hugging Face token with **Read** permission and save it in the default private file:

```bash
# Create the private TumorQuantAI configuration directory.
install -d -m 700 "$HOME/.config/tumorquantai"

# Paste the Hugging Face read token without displaying it on screen.
read -rsp "Hugging Face read token: " HF_READ_TOKEN
printf '\n'
printf '%s' "$HF_READ_TOKEN" > "$HOME/.config/tumorquantai/hf_token"
unset HF_READ_TOKEN
chmod 600 "$HOME/.config/tumorquantai/hf_token"

# Check the installed runtime and the configured credential file.
tumorquantai doctor --online
```

TumorQuantAI automatically reads `$HOME/.config/tumorquantai/hf_token`; no environment variable is required. Creating a token does not grant access by itself—the Hugging Face model-access request must also be approved. The first authorized inference confirms that the pinned model artifact can be downloaded. Never paste the token into a command, issue, log, or repository file.

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

After HistoPLUS access is configured, run the same one-slide 1% analysis through the installed route:

```bash
# Run through the backend selected during installation.
tumorquantai quickstart --cpu

# Verify the overlay, summary, coordinates, class counts, and aggregation audit.
python3 examples/quickstart/verify_outputs.py
```

The command downloads only `TumorQuantAI_LymphomaWSI_022` from Zenodo record `21466410`, verifies its published size and checksums, converts L0 and L2, and writes `START_HERE.html`.

See the [complete one-WSI QuickStart](https://cfarkas.github.io/tumorquantai/quick_start/) for sample identity, checksums, output review, and resume behavior.

## Full tutorial: 21 public lymphoma WSIs at 10%

The [full tutorial](https://cfarkas.github.io/tumorquantai/full_tutorial/) starts with `git clone` and `cd tumorquantai`, uses fixed relative tutorial directories, downloads all 21 public lymphoma MDS files, validates every SHA-256 checksum, converts L0/L2 with the installed `tumorquantai convert` command, and processes a deterministic 10% of detected tissue tiles per slide.

## Other example run: breast IHC TIFF patches at 100%

The patch route accepts authorized local raw TIFF patches, processes every
discovered patch without percentage subsampling, and can write paper-ready and
QC figures. Use TIFF-embedded physical pixel size when it is reliable:

```bash
# Process every local TIFF patch on CPU and request paper/QC figures.
tumorquantai --patches /path/to/breast-ihc-tiff-patches \
  --paper-figures \
  --output /path/to/breast-ihc-patch-results \
  --cpu
```

If the TIFFs do not contain reliable micrometres-per-pixel metadata, provide one
verified common value with `--source-mpp`. Do not copy an MPP from another
scanner, objective, or export. The example dataset and its Zenodo DOI are
pending data-governance review and publication; no breast-IHC DOI is currently
claimed. See the [breast IHC patch tutorial](https://cfarkas.github.io/tumorquantai/tutorials/breast-ihc-patches/).

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

# Run a reproducible 10% analysis after reviewing the inspection.
tumorquantai run /path/to/slides \
  --output /path/to/tumorquantai-results \
  --preset fast \
  --source-mpp 0.261780 \
  --cpu
```

Use the physical MPP recorded by the scanner or export software.

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
- [HistoPLUS access](https://cfarkas.github.io/tumorquantai/how-to/model-access/)
- [QuickStart Example 1](https://cfarkas.github.io/tumorquantai/quick_start/)
- [Execution methods](https://cfarkas.github.io/tumorquantai/execution_environments/)
- [Full 21-slide tutorial](https://cfarkas.github.io/tumorquantai/full_tutorial/)
- [Breast IHC TIFF patches at 100%](https://cfarkas.github.io/tumorquantai/tutorials/breast-ihc-patches/)
- [Apply to your own WSIs](https://cfarkas.github.io/tumorquantai/own_data/)
- [Outputs](https://cfarkas.github.io/tumorquantai/outputs/)
- [Troubleshooting](https://cfarkas.github.io/tumorquantai/troubleshooting/)
