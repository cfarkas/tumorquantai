# TumorQuantAI

TumorQuantAI processes hematoxylin and eosin (H&E) whole-slide images (WSIs)
with HistoPLUS and records the image scale, sampling, failures, and outputs.

> **Research use only.** TumorQuantAI is not a diagnostic device. Predictions
> are not diagnoses or pathologist ground truth.

## Quick start

This example downloads one public Motic MDS slide, converts image-pyramid
levels L0 and L2 to Tagged Image File Format (TIFF), and inspects the files
without model inference. L0 is the highest-resolution image used for analysis;
L2 is its lower-resolution companion. Replace /data with a writable directory
on a mounted data filesystem.

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

The checksum commands print OK when the manifest and slide match the published
files. MD5 means Message-Digest Algorithm 5; SHA-256 means Secure Hash
Algorithm 256-bit. Successful inspection writes inspection/INSPECTION.html and
inspection/inspection_manifest.csv.

The dataset is public and requires no Zenodo credential. HistoPLUS access is
gated separately and is required only for inference. Configure it using the
[model-access guide](how-to/model-access.md).

After Java, Nextflow, Docker, and authorized model access are ready, process 1%
of the detected tissue tiles:

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

Source resolution is 0.261780 micrometres per pixel (MPP). Source MPP describes
the input image; target MPP describes the scale presented to the model. The 1%
preset samples detected tissue tiles deterministically and does not estimate a
whole-slide count. Use --cpu for a central processing unit (CPU) or --gpu for a
graphics processing unit (GPU). The result directory holds outputs; the
separate Nextflow work directory holds resumable task state.

See [run one public slide](start-here/public-slide.md) for the equivalent curl
download, exact stop/resume steps, and the files to inspect.

## Public dataset

The tutorial data are [Zenodo record
21466410](https://zenodo.org/records/21466410), digital object identifier (DOI)
[10.5281/zenodo.21466410](https://doi.org/10.5281/zenodo.21466410), matched to
TumorQuantAI v0.4.0. The collection has no diagnostic annotations or
pathologist ground truth.

- [Review one-slide results](tutorials/one-public-slide.md)
- [Run four public slides](tutorials/four-public-slides.md)
- [Run all 21 public slides](tutorials/full-collection.md)

## Run your slides

First inspect the files without loading HistoPLUS:

~~~bash
export TQA_INPUT="/data/slides"
export TQA_INSPECTION="/data/tumorquantai-inspection"

./tumorquantai inspect "$TQA_INPUT" --output "$TQA_INSPECTION"
~~~

A normal converted input contains an L0 primary TIFF and an L2 companion.
Review the generated manifest and establish source MPP from scanner or export
provenance before inference. TumorQuantAI stops when physical scale is required
but cannot be established.

See [run your slides](start-here/own-slides.md), [parameters](reference/parameters.md),
and [installation](how-to/install.md).

## Results

A completed run writes:

~~~text
results/
├── START_HERE.html
├── SAMPLE/
│   ├── cell_types/class_counts.csv
│   ├── cell_types/cell_type_coordinates.csv
│   ├── overlays/celltypes_overview_and_zoom.png
│   └── summary/summary.json
└── aggregated_celltypes/
    ├── celltype_counts_by_sample.csv
    ├── celltype_fractions_by_sample.csv
    └── sample_aggregation_audit.csv
~~~

Comma-separated values (CSV) tables contain completed samples only.
summary.json uses JavaScript Object Notation (JSON). A failed or incomplete
sample remains in sample_aggregation_audit.csv and is excluded from numeric
matrices; it is not represented as a completed sample with zero cells.

Review [output files](reference/outputs.md) and [quality-control (QC)
overlays](how-to/review-overlays.md) before interpreting results.

## Help

- [Parameters](reference/parameters.md)
- [Results](reference/outputs.md)
- [Resume a run](how-to/resume.md)
- [Troubleshooting](troubleshooting/index.md)
- [Glossary](GLOSSARY.md)

Bug reports should contain redacted ./tumorquantai doctor --json and
./tumorquantai status RESULTS --json output. Do not attach tokens, model
weights, raw slides, protected health information (PHI), patient-level tables,
or unredacted logs.
