# TumorQuantAI

TumorQuantAI processes hematoxylin and eosin (H&E) whole-slide images (WSIs)
with HistoPLUS and writes reproducible cell coordinates, quality-control
overlays, per-slide summaries, and cohort tables.
The public tutorial dataset has digital object identifier (DOI)
`10.5281/zenodo.21466410`.


[![CI](https://github.com/cfarkas/tumorquantai/actions/workflows/ci.yml/badge.svg)](https://github.com/cfarkas/tumorquantai/actions/workflows/ci.yml)
[![Documentation](https://github.com/cfarkas/tumorquantai/actions/workflows/docs.yml/badge.svg)](https://cfarkas.github.io/tumorquantai/)
[![Release](https://img.shields.io/github/v/release/cfarkas/tumorquantai?sort=semver)](https://github.com/cfarkas/tumorquantai/releases/latest)
[![Nextflow](https://img.shields.io/badge/workflow-Nextflow-0dc09d)](https://www.nextflow.io/)
[![Dataset DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21466410.svg)](https://doi.org/10.5281/zenodo.21466410)

## Quick start

This example downloads one public Motic MDS slide, converts image-pyramid
levels L0 and L2 to Tagged Image File Format (TIFF), and inspects the result
without running the model. L0 is the highest-resolution image used for
analysis; L2 is its lower-resolution companion. Replace /data with a writable
directory on a mounted data filesystem.

~~~bash
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai

export TQA_REPO="$PWD"
export TQA_DATA="/data/tumorquantai-one-slide"

mkdir -p "$TQA_DATA"
findmnt -T "$TQA_DATA"
df -hT "$TQA_DATA"
test -w "$TQA_DATA"

python3 -m venv "$TQA_DATA/.venv"
. "$TQA_DATA/.venv/bin/activate"
python -m pip install -r "$TQA_REPO/requirements-tutorial.txt"

cd "$TQA_DATA"
wget -c -O tumorquantai_lymphoma_mds_manifest.csv \
  "https://zenodo.org/records/21466410/files/tumorquantai_lymphoma_mds_manifest.csv?download=1"
wget -c -O TumorQuantAI_LymphomaWSI_022.mds \
  "https://zenodo.org/records/21466410/files/TumorQuantAI_LymphomaWSI_022.mds?download=1"

echo "ad9a9472e8beb302f8b9ba2b3359bacc  tumorquantai_lymphoma_mds_manifest.csv" | md5sum -c -
test "$(stat -c %s TumorQuantAI_LymphomaWSI_022.mds)" -eq 125350400
echo "94bb5b08ccf1957f8c42a579e8b33cfb  TumorQuantAI_LymphomaWSI_022.mds" | md5sum -c -
echo "db2988b5c6bc791510cec4127106509e604e577feafdb15b94c149043ed7067a  TumorQuantAI_LymphomaWSI_022.mds" | sha256sum -c -

cd "$TQA_REPO"
python bin/mds_to_tiff.py \
  --input "$TQA_DATA/TumorQuantAI_LymphomaWSI_022.mds" \
  --manifest "$TQA_DATA/tumorquantai_lymphoma_mds_manifest.csv" \
  --output-dir "$TQA_DATA/slides" \
  --levels 0 2 \
  --sample-id TumorQuantAI_LymphomaWSI_022 \
  --expected-count 1 \
  --source-mpp 0.261780 \
  --resume

./tumorquantai inspect "$TQA_DATA/slides" \
  --sample-sheet "$TQA_DATA/slides/samples.csv" \
  --output "$TQA_DATA/inspection"
~~~

If `wget` is unavailable, use these `curl` commands instead of the two `wget`
commands above. They keep the same direct Zenodo filenames; after they finish,
continue with the checksum, conversion, and inspection commands.

~~~bash
export TQA_DATA="/data/tumorquantai-one-slide"

cd "$TQA_DATA"
curl -L --fail --retry 5 \
  -o tumorquantai_lymphoma_mds_manifest.csv \
  "https://zenodo.org/records/21466410/files/tumorquantai_lymphoma_mds_manifest.csv?download=1"
curl -L --fail --retry 5 \
  -o TumorQuantAI_LymphomaWSI_022.mds \
  "https://zenodo.org/records/21466410/files/TumorQuantAI_LymphomaWSI_022.mds?download=1"
~~~

Successful downloads print OK for each checksum. MD5 means Message-Digest
Algorithm 5; SHA-256 means Secure Hash Algorithm 256-bit. Successful conversion
writes slides/TumorQuantAI_LymphomaWSI_022/1_L0_rgb.tif,
slides/TumorQuantAI_LymphomaWSI_022/1_L2_rgb.tif, and slides/samples.csv.
Inspection writes inspection/INSPECTION.html and inspection/inspection_manifest.csv.

Public data access does not require a Zenodo credential. HistoPLUS model access
is gated separately and is required only for inference; see
[configure HistoPLUS access](https://cfarkas.github.io/tumorquantai/how-to/model-access/).

After model access, Java, Nextflow, and Docker have been configured, process a
seeded 1% of the detected tissue tiles:

~~~bash
export TQA_REPO="${TQA_REPO:-$PWD}"
export TQA_DATA="/data/tumorquantai-one-slide"

cd "$TQA_REPO"
./tumorquantai run "$TQA_DATA/slides" \
  --sample-sheet "$TQA_DATA/slides/samples.csv" \
  --output "$TQA_DATA/results-1-percent" \
  --work-dir "$TQA_DATA/work-1-percent" \
  --preset smoke \
  --sample TumorQuantAI_LymphomaWSI_022 \
  --source-mpp 0.261780 \
  --profile auto
~~~

Use --cpu to force central processing unit (CPU) execution or --gpu to select
the graphics processing unit (GPU) profile. The result directory contains the
scientific outputs; the separate Nextflow work directory contains resumable
task state and can be much larger.

> **Research use only.** TumorQuantAI is not a diagnostic device. HistoPLUS
> predictions are not diagnoses or pathologist ground truth. Review image
> quality, physical scale, sampling, overlays, failures, and biological
> interpretation before research use.

The public data are fixed at [Zenodo record
21466410](https://zenodo.org/records/21466410), digital object identifier (DOI)
[10.5281/zenodo.21466410](https://doi.org/10.5281/zenodo.21466410), and are
matched to TumorQuantAI v0.4.0. Sample 022 has a source resolution of 0.261780
micrometres per pixel (MPP). The model target MPP is a separate workflow
setting and does not replace the verified source MPP.

For the same procedure with a curl alternative and resume instructions, see
[run one public slide](https://cfarkas.github.io/tumorquantai/start-here/public-slide/).

## What TumorQuantAI does

TumorQuantAI discovers primary slides, validates physical scale, selects tissue
tiles deterministically, runs HistoPLUS cell typing, and writes one result
directory per slide. It records slide fingerprints, source and target MPP,
sampling percentage, random seed, software/model/container identities, and
sample failures.

The workflow preserves per-slide isolation and Nextflow cache reuse. A failed
or incomplete sample remains in the aggregation audit and is excluded from
numeric matrices; it is never converted to a completed sample with zero cells.

## Run your slides

Inspect an input directory before inference:

~~~bash
export TQA_INPUT="/data/slides"
export TQA_INSPECTION="/data/tumorquantai-inspection"

./tumorquantai inspect "$TQA_INPUT" --output "$TQA_INSPECTION"
~~~

The portable input layout is:

~~~text
/data/slides/
└── case_001/
    ├── 1_L0_rgb.tif
    └── 1_L2_rgb.tif
~~~

Use a verified source MPP from scanner or export provenance. TumorQuantAI stops
when a required physical scale cannot be established.

Three presets control the fraction of detected tissue tiles:

| Preset | Tiles processed | Typical use |
| --- | ---: | --- |
| smoke | Seeded 1% from one selected slide | Installation and scale check |
| fast | Seeded 10% by default | Reproducible sampled analysis |
| full | 100% | All detected tissue tiles |

Counts from 1% or 10% runs describe only the sampled tiles. They are not
whole-slide counts and must not be multiplied by 100 / percent_slide.

## Check the results

| File | Contents |
| --- | --- |
| START_HERE.html | Local run summary and links to files that exist |
| SAMPLE/overlays/celltypes_overview_and_zoom.png | Overview and annotated zoom for visual quality control (QC) |
| SAMPLE/summary/summary.json | Completion, scale, sampling, seed, cells, and provenance in JavaScript Object Notation (JSON) |
| SAMPLE/cell_types/class_counts.csv | Counts in processed tiles as comma-separated values (CSV) |
| aggregated_celltypes/sample_aggregation_audit.csv | Included, failed, and incomplete samples |
| aggregated_celltypes/celltype_fractions_by_sample.csv | Within-sample cell-type fractions |
| aggregated_celltypes/celltype_counts_by_sample.csv | Raw detected-cell counts in processed tiles |

A zero for a class is interpretable only for a completed sample. A missing,
failed, or incomplete sample has no numeric matrix column and remains visible
in sample_aggregation_audit.csv.

~~~bash
export TQA_RESULTS="/data/tumorquantai-one-slide/results-1-percent"

./tumorquantai status "$TQA_RESULTS"
./tumorquantai report "$TQA_RESULTS"
~~~

Repeat the original run command to resume after interruption. Resume is enabled
by default and reuses valid cached tasks.

## Test without downloading data

The synthetic test needs Linux and Python 3, but no model, Docker, GPU, or
public slide:

~~~bash
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
./tumorquantai demo
~~~

The generated counts and failures test software structure only and have no
biological meaning. Open tumorquantai-demo/START_HERE.html.

## Requirements

| Task | Requirements |
| --- | --- |
| Download and inspect | Linux, Python 3.10+, requirements-tutorial.txt, mounted storage |
| CPU inference | Java 17+, Nextflow 24.10+, Docker 24+ or a prepared local environment, authorized HistoPLUS access |
| GPU inference | CPU requirements plus a compatible NVIDIA driver and container runtime |

Before conversion or inference, check download, converted TIFF, work, cache,
and result space separately. See [storage and work
directories](https://cfarkas.github.io/tumorquantai/how-to/storage/).

## Documentation

- [Quick start](https://cfarkas.github.io/tumorquantai/start-here/public-slide/)
- [Run four public slides](https://cfarkas.github.io/tumorquantai/tutorials/four-public-slides/)
- [Run all 21 public slides](https://cfarkas.github.io/tumorquantai/tutorials/full-collection/)
- [Run your slides](https://cfarkas.github.io/tumorquantai/start-here/own-slides/)
- [Parameters](https://cfarkas.github.io/tumorquantai/reference/parameters/)
- [Results](https://cfarkas.github.io/tumorquantai/reference/outputs/)
- [Troubleshooting](https://cfarkas.github.io/tumorquantai/troubleshooting/)
- [Command-line interface](https://cfarkas.github.io/tumorquantai/reference/cli/)

Bug reports should include redacted ./tumorquantai doctor --json and
./tumorquantai status RESULTS --json output. Do not attach tokens, model
weights, raw WSI files, protected health information (PHI), patient-level
tables, or unredacted logs.

## Citation and license status

Cite TumorQuantAI software, the public dataset, LazySlide, and HistoPLUS
separately. See [CITATIONS.md](CITATIONS.md). The dataset DOI is not a software
DOI.

The repository currently has no declared open-source license. Source visibility
does not grant permission to copy, modify, or redistribute it. The dataset and
the gated model have their own terms.
