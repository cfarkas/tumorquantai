# Quick start

This guide takes you from an exported slide folder to one small, reviewable
TumorQuantAI result. It is designed for a first run, not a final cohort.

!!! warning "Research use only"
    TumorQuantAI predictions are not diagnoses or pathologist ground truth.
    Review slide quality, overlays, sampling, and failed samples before drawing
    biological conclusions.

## 1. Check the computer

TumorQuantAI's recommended path uses Nextflow on Linux and runs the image
analysis inside Docker.

You need:

- Java 17 or newer;
- Nextflow 24.10 or newer;
- Docker 24 or newer;
- enough storage for source TIFFs, the Nextflow work directory, and results;
- authorized HistoPLUS model access; and
- an NVIDIA GPU for practical inference speed, although CPU mode is supported.

```bash
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai

./setup_server.sh --check
./run.sh --doctor
```

If Nextflow is missing, install the repository's verified launcher:

```bash
./setup_server.sh --install-nextflow
export PATH="$HOME/.local/bin:$PATH"
```

See [Installation](INSTALL.md) for Docker, GPU, storage, and local-environment
details.

## 2. Store model access safely

Request access to
[`Owkin-Bioptimus/histoplus`](https://huggingface.co/Owkin-Bioptimus/histoplus)
and create a read-only Hugging Face token. Store it in a private file:

```bash
mkdir -p ~/.config/lazyslide-histoplus
chmod 700 ~/.config/lazyslide-histoplus
umask 077
read -rsp "Hugging Face read-only token: " HF_READ_TOKEN
printf '%s' "$HF_READ_TOKEN" > ~/.config/lazyslide-histoplus/hf_token
unset HF_READ_TOKEN
printf '\n'
chmod 600 ~/.config/lazyslide-histoplus/hf_token
```

Do not put a token in a command, sample sheet, notebook, issue, or shared log.
If your organization provides an approved local weight file, use
`--histoplus-weight-file` instead.

## 3. Arrange one exported slide

The standard portable input is an L0 TIFF plus its L2 companion:

```text
/data/slides/
└── case_001/
    ├── 1_L0_rgb.tif
    └── 1_L2_rgb.tif
```

The L0 image is analyzed. The L2 image supports sampled-patch and overview
artifacts. Read [Inputs, L0/L2, and MPP](INPUTS_AND_MPP.md) before using a
different layout.

## 4. Discover without inference

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

Confirm:

- each intended primary L0 slide appears once;
- sample IDs are unique and understandable;
- no companion, thumbnail, or generated image was selected; and
- the paths point to the expected source files.

Discovery does not run HistoPLUS.

## 5. Confirm physical resolution

MPP means micrometres per pixel. Obtain the physical L0 MPP from the scanner,
export record, or reliable embedded TIFF metadata.

`--slide-mpp` is the source image resolution. `--mpp 0.5` is the target
resolution used for model tiles. They are not interchangeable.

!!! danger "Do not guess MPP"
    A plausible but incorrect value can change physical scale and invalidate
    the analysis. The command below prompts you instead of providing a
    copyable example value.

```bash
read -rp "Verified source L0 MPP: " SOURCE_MPP
```

Omit `--slide-mpp` only when the TIFF contains reliable physical-resolution
metadata. TumorQuantAI fails closed when it cannot establish the source scale.

## 6. Run one slide at 1%

```bash
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

`--profile auto` selects the supported Docker CPU or GPU path based on the
host. The first run may download the container image and gated model.

## 7. Review before scaling up

Start with:

| File | Check |
| --- | --- |
| `<sample>/overlays/celltypes_overview_and_zoom.png` | Cell markings and selected tissue align visually. |
| `<sample>/summary/summary.json` | Completion, MPP, seed, sampled tiles, and cell total are plausible. |
| `aggregated_celltypes/sample_aggregation_audit.csv` | The slide is included and not silently missing. |
| `aggregated_celltypes/celltype_fractions_by_sample.csv` | The cell-type composition table is readable. |

Fast-mode raw counts describe sampled tissue tiles; they are not whole-slide
counts. Do not multiply them by `100 / percent-slide`.

If the review passes, use a new output directory for a 10% fast cohort or a
full run. See [Fast versus full](RUN_MODES.md).

## If the run stops

Repeat the same command after correcting the environmental problem. Resume is
enabled by default and valid completed tasks are reused. See
[Running, resume, and failures](RUNNING.md).
