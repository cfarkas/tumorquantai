# Run four public slides

This procedure downloads samples 022, 002, 006, and 016 from Zenodo record
21466410 and processes a seeded 10% of detected tissue tiles.

## Requirements

You need a Linux host, Python 3.10 or newer with requirements-tutorial.txt,
mounted storage, and the inference requirements from the
[installation guide](../how-to/install.md). The four Motic MDS files total
917,772,288 bytes. Allow about 30 GB for downloads, converted Tagged Image File
Format (TIFF) images, the Nextflow work directory, cache, and results; verify
the local estimate before starting.

Public Zenodo access needs no credential. HistoPLUS access is gated separately.
The images have source resolution 0.261780 micrometres per pixel (MPP).

## Download the four MDS files

Run from the repository root. Replace /data with the mounted storage selected
for this run.

~~~bash
export TQA_REPO="$PWD"
export TQA_DATA="/data/tumorquantai-four-slides"

mkdir -p "$TQA_DATA"
findmnt -T "$TQA_DATA"
df -hT "$TQA_DATA"
test -w "$TQA_DATA"

wget -c -O "$TQA_DATA/tumorquantai_lymphoma_mds_manifest.csv" \
  "https://zenodo.org/records/21466410/files/tumorquantai_lymphoma_mds_manifest.csv?download=1"
wget -c -O "$TQA_DATA/TumorQuantAI_LymphomaWSI_022.mds" \
  "https://zenodo.org/records/21466410/files/TumorQuantAI_LymphomaWSI_022.mds?download=1"
wget -c -O "$TQA_DATA/TumorQuantAI_LymphomaWSI_002.mds" \
  "https://zenodo.org/records/21466410/files/TumorQuantAI_LymphomaWSI_002.mds?download=1"
wget -c -O "$TQA_DATA/TumorQuantAI_LymphomaWSI_006.mds" \
  "https://zenodo.org/records/21466410/files/TumorQuantAI_LymphomaWSI_006.mds?download=1"
wget -c -O "$TQA_DATA/TumorQuantAI_LymphomaWSI_016.mds" \
  "https://zenodo.org/records/21466410/files/TumorQuantAI_LymphomaWSI_016.mds?download=1"
~~~

Each -c download resumes a partial file and leaves the published filename
visible.

## Check the downloads

MD5 means Message-Digest Algorithm 5. SHA-256 means Secure Hash Algorithm
256-bit. The repository checksum file is generated from the authoritative
manifest.

~~~bash
export TQA_REPO="${TQA_REPO:-$PWD}"
export TQA_DATA="/data/tumorquantai-four-slides"

cd "$TQA_DATA"
echo "ad9a9472e8beb302f8b9ba2b3359bacc  tumorquantai_lymphoma_mds_manifest.csv" | md5sum -c -
sha256sum -c "$TQA_REPO/examples/lymphoma/checksums_first_four.sha256"
~~~

Success prints OK for the manifest and all four slides. Stop if any check fails.

## Convert the files

The converter resolves ordinary Zenodo filenames through the manifest, rejects
ambiguous candidates, verifies each checksum, and writes image-pyramid levels
L0 and L2 as TIFF files. L0 is highest-resolution; L2 is its lower-resolution
companion.

~~~bash
export TQA_REPO="${TQA_REPO:-$PWD}"
export TQA_DATA="/data/tumorquantai-four-slides"

python "$TQA_REPO/bin/mds_to_tiff.py" \
  --input "$TQA_DATA" \
  --manifest "$TQA_DATA/tumorquantai_lymphoma_mds_manifest.csv" \
  --output-dir "$TQA_DATA/slides" \
  --levels 0 2 \
  --sample-id TumorQuantAI_LymphomaWSI_022 \
  --sample-id TumorQuantAI_LymphomaWSI_002 \
  --sample-id TumorQuantAI_LymphomaWSI_006 \
  --sample-id TumorQuantAI_LymphomaWSI_016 \
  --expected-count 4 \
  --source-mpp 0.261780 \
  --resume
~~~

Success writes four alias directories, samples.csv, and
mds_conversion_manifest.json. JSON means JavaScript Object Notation.

## Check the slide list

Inspection does not run HistoPLUS.

~~~bash
export TQA_REPO="${TQA_REPO:-$PWD}"
export TQA_DATA="/data/tumorquantai-four-slides"

cd "$TQA_REPO"
./tumorquantai inspect "$TQA_DATA/slides" \
  --sample-sheet "$TQA_DATA/slides/samples.csv" \
  --output "$TQA_DATA/inspection"
~~~

Open inspection/INSPECTION.html and inspection/inspection_manifest.csv.
CSV means comma-separated values. Confirm exactly four distinct samples,
complete L0/L2 pairs, and source MPP 0.261780.

## Run 10% of tissue tiles

Source MPP describes each input image. Target/model MPP is a separate setting.
The fast preset selects a reproducible 10% of detected tissue tiles; its raw
counts are not whole-slide counts and must not be multiplied by ten. Results
and resumable Nextflow work use separate directories.

After authorized HistoPLUS access is configured:

~~~bash
export TQA_REPO="${TQA_REPO:-$PWD}"
export TQA_DATA="/data/tumorquantai-four-slides"

cd "$TQA_REPO"
./tumorquantai run "$TQA_DATA/slides" \
  --sample-sheet "$TQA_DATA/slides/samples.csv" \
  --output "$TQA_DATA/results-10-percent" \
  --work-dir "$TQA_DATA/work-10-percent" \
  --preset fast \
  --source-mpp 0.261780 \
  --profile auto
~~~

The auto profile selects an available execution path. Use --cpu for a central
processing unit (CPU), or --gpu for a graphics processing unit (GPU) after
doctor confirms the NVIDIA runtime.

## Check the results

~~~bash
export TQA_DATA="/data/tumorquantai-four-slides"

./tumorquantai status "$TQA_DATA/results-10-percent"
./tumorquantai report "$TQA_DATA/results-10-percent"
~~~

Require four included samples and no excluded, failed, or incomplete sample in
aggregated_celltypes/sample_aggregation_audit.csv. Review every overlay as
visual quality control (QC) before comparing the count and fraction matrices.

A completed sample with zero cells of a class is distinct from a failed or
missing sample, which has no numeric matrix column.

## Resume an interrupted run

Press Ctrl+C to stop. Repeat the conversion or run command with the same paths.
Verified TIFF files and valid Nextflow tasks are reused. Keep
work-10-percent until resume is no longer needed. Remove only the named
four-slide directory after verifying its mount.

Next, read the [storage requirements for all 21 slides](full-collection.md).
