# Run one public slide

This page downloads one public whole-slide image (WSI), converts the Motic MDS
file into Tagged Image File Format (TIFF), inspects it without inference, and
shows the optional 1% HistoPLUS command.

The data are on Zenodo record 21466410, digital object identifier (DOI)
10.5281/zenodo.21466410, and are matched to TumorQuantAI v0.4.0. Zenodo access
is public. HistoPLUS model access is gated separately.

## Requirements

For download, conversion, and inspection you need Linux, Python 3.10 or newer,
the packages in requirements-tutorial.txt, and writable mounted storage. For
inference you also need Java 17 or newer, Nextflow 24.10 or newer, Docker 24 or
newer (or a prepared local environment), and authorized HistoPLUS access.

The MDS download is 125,350,400 bytes. Converted image-pyramid levels L0 and
L2, the Nextflow work directory, model cache, and results need additional
space. L0 is the highest-resolution image used for analysis; L2 is its lower-resolution
companion.

Replace /data in the commands with the mount selected for the analysis.

## Check storage

Run this from the repository root. It creates the data directory and a small
Python environment on the selected filesystem.

~~~bash
export TQA_REPO="$PWD"
export TQA_DATA="/data/tumorquantai-one-slide"

mkdir -p "$TQA_DATA"
findmnt -T "$TQA_DATA"
df -hT "$TQA_DATA"
test -w "$TQA_DATA"

python3 -m venv "$TQA_DATA/.venv"
. "$TQA_DATA/.venv/bin/activate"
python -m pip install -r "$TQA_REPO/requirements-tutorial.txt"
~~~

Success means findmnt identifies the intended mounted filesystem, df reports
enough free space, and test exits without output.

## Download with wget

Use these two commands to download only the manifest and sample 022. The -c
option resumes a partial file.

~~~bash
export TQA_DATA="/data/tumorquantai-one-slide"

cd "$TQA_DATA"
wget -c -O tumorquantai_lymphoma_mds_manifest.csv \
  "https://zenodo.org/records/21466410/files/tumorquantai_lymphoma_mds_manifest.csv?download=1"
wget -c -O TumorQuantAI_LymphomaWSI_022.mds \
  "https://zenodo.org/records/21466410/files/TumorQuantAI_LymphomaWSI_022.mds?download=1"
~~~

## Download with curl

Use this block instead of the wget block, not in addition to it. The commands
follow redirects, fail on HTTP errors, and retry transient failures. They
replace an existing destination file rather than attempting an ambiguous
resume of a completed file.

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

## Check the download

MD5 means Message-Digest Algorithm 5. SHA-256 means Secure Hash Algorithm
256-bit. The following checks validate the published manifest checksum, slide
size, slide MD5, and slide SHA-256.

~~~bash
export TQA_DATA="/data/tumorquantai-one-slide"

cd "$TQA_DATA"
echo "ad9a9472e8beb302f8b9ba2b3359bacc  tumorquantai_lymphoma_mds_manifest.csv" | md5sum -c -
test "$(stat -c %s TumorQuantAI_LymphomaWSI_022.mds)" -eq 125350400
echo "94bb5b08ccf1957f8c42a579e8b33cfb  TumorQuantAI_LymphomaWSI_022.mds" | md5sum -c -
echo "db2988b5c6bc791510cec4127106509e604e577feafdb15b94c149043ed7067a  TumorQuantAI_LymphomaWSI_022.mds" | sha256sum -c -
~~~

The three checksum commands print OK. The size test is silent on success. Stop
if any command fails; do not convert an unverified file.

## Convert the MDS file

The converter accepts the ordinary filename downloaded from Zenodo. It verifies
the manifest row before writing L0/L2 TIFF files and preserves resumable
conversion state.

~~~bash
export TQA_REPO="${TQA_REPO:-$PWD}"
export TQA_DATA="/data/tumorquantai-one-slide"

python "$TQA_REPO/bin/mds_to_tiff.py" \
  --input "$TQA_DATA/TumorQuantAI_LymphomaWSI_022.mds" \
  --manifest "$TQA_DATA/tumorquantai_lymphoma_mds_manifest.csv" \
  --output-dir "$TQA_DATA/slides" \
  --levels 0 2 \
  --sample-id TumorQuantAI_LymphomaWSI_022 \
  --expected-count 1 \
  --source-mpp 0.261780 \
  --resume
~~~

Success writes:

~~~text
slides/
├── TumorQuantAI_LymphomaWSI_022/
│   ├── 1_L0_rgb.tif
│   └── 1_L2_rgb.tif
├── mds_conversion_manifest.json
└── samples.csv
~~~

The manifest is JavaScript Object Notation (JSON). Do not delete it while
resume is useful.

## Inspect the slide

Inspection does not load HistoPLUS and works without a graphics processing unit
(GPU).

~~~bash
export TQA_REPO="${TQA_REPO:-$PWD}"
export TQA_DATA="/data/tumorquantai-one-slide"

cd "$TQA_REPO"
./tumorquantai inspect "$TQA_DATA/slides" \
  --sample-sheet "$TQA_DATA/slides/samples.csv" \
  --output "$TQA_DATA/inspection"
~~~

Success writes inspection/INSPECTION.html and
inspection/inspection_manifest.csv. CSV means comma-separated values. Confirm
one sample, one L0 primary file, one L2 companion, and source resolution
0.261780 micrometres per pixel (MPP).

## Run 1% of the tissue tiles

Source MPP describes the physical scale of the input. Target/model MPP is the
separate scale used to form model tiles. The smoke preset selects a seeded 1%
of detected tissue tiles; its counts are not whole-slide counts and must not be
multiplied by 100. Public Zenodo access does not authorize HistoPLUS inference.

The result directory contains outputs. The separate Nextflow work directory
contains resumable tasks and can be larger. Configure
[authorized HistoPLUS access](../how-to/model-access.md), then run:

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

The auto profile selects an available execution path. Use --cpu to force the
central processing unit (CPU), or --gpu to select the GPU profile after doctor
confirms the NVIDIA runtime.

## Check the results

Open these files in order:

1. results-1-percent/START_HERE.html
2. results-1-percent/TumorQuantAI_LymphomaWSI_022/overlays/celltypes_overview_and_zoom.png
3. results-1-percent/TumorQuantAI_LymphomaWSI_022/summary/summary.json
4. results-1-percent/aggregated_celltypes/sample_aggregation_audit.csv
5. results-1-percent/aggregated_celltypes/celltype_fractions_by_sample.csv
6. results-1-percent/aggregated_celltypes/celltype_counts_by_sample.csv

The overlay is for visual quality control (QC). The summary must record source
MPP, target MPP, 1% sampling, seed, model revision, and completion. The audit
must contain exactly one included sample and no failed or incomplete sample.

A zero cell class is valid only for a completed sample. A failed, missing, or
incomplete sample has no numeric matrix column and remains in the audit.

## Resume a run

Press Ctrl+C to stop. Repeat the same conversion or inference command with the
same paths. Conversion --resume reuses verified TIFF files, and inference
resume reuses valid Nextflow tasks.

~~~bash
export TQA_REPO="${TQA_REPO:-$PWD}"
export TQA_DATA="/data/tumorquantai-one-slide"

cd "$TQA_REPO"
./tumorquantai status "$TQA_DATA/results-1-percent"
~~~

Status prints the first relevant log and the exact resume command.

To remove this example after review, first print and verify the exact value of
TQA_DATA and its mount. Remove only /data/tumorquantai-one-slide; retain the
work directory if another resume may be needed.

Next, read [the one-slide results](../tutorials/one-public-slide.md) or
[run your slides](own-slides.md).
