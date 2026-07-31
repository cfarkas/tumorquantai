# Run all 21 public slides

This procedure downloads the complete public Motic MDS collection from Zenodo
record 21466410 and converts image-pyramid levels L0 and L2; L0 is the
highest-resolution level. It then inspects the roster and shows the full-tissue
workflow command. The dataset is matched to TumorQuantAI v0.4.0 and has no
diagnostic annotations or pathologist ground truth.

!!! danger "Not an installation test"
    The 21 MDS files total 17,370,771,968 bytes. L0/L2 conversion can approach
    142 GB. Budget at least 300 GB for downloads, conversion, work, caches, and
    results, then verify the local estimate. Run and review the one- and
    four-slide checkpoints first.

Full inference requires authorized HistoPLUS access, stable compute, and
continuous storage monitoring. Public Zenodo downloads require no credential.

## Verify the destination

Run from the repository root. Replace `/mounted/storage` with the selected
mounted filesystem.

~~~bash
export TQA_REPO="$PWD"
export TQA_DATA="/mounted/storage/tumorquantai-all-21"

mkdir -p "$TQA_DATA"
findmnt -T "$TQA_DATA"
df -hT "$TQA_DATA"
test -w "$TQA_DATA"
~~~

Do not place the collection, converted Tagged Image File Format (TIFF) files,
Nextflow work, or model
caches inside the Git checkout, `/`, or an unverified home filesystem.

## Download standard Zenodo filenames

The URL list is generated from the authoritative public manifest. Each
`wget -c -O` keeps the published `TumorQuantAI_LymphomaWSI_NNN.mds`
filename and resumes a partial transfer.

~~~bash
export TQA_REPO="${TQA_REPO:-$PWD}"
export TQA_DATA="/mounted/storage/tumorquantai-all-21"

wget -c -O "$TQA_DATA/tumorquantai_lymphoma_mds_manifest.csv" \
  "https://zenodo.org/records/21466410/files/tumorquantai_lymphoma_mds_manifest.csv?download=1"

while IFS= read -r url; do
  filename="${url##*/}"
  filename="${filename%%\?*}"
  wget -c -O "$TQA_DATA/$filename" "$url"
done < "$TQA_REPO/examples/lymphoma/zenodo_all_21.urls.txt"
~~~

## Verify every download

MD5 means Message-Digest Algorithm 5. SHA-256 means Secure Hash Algorithm
256-bit. Stop if the manifest or any slide does not print `OK`.

~~~bash
export TQA_REPO="${TQA_REPO:-$PWD}"
export TQA_DATA="/mounted/storage/tumorquantai-all-21"

cd "$TQA_DATA"
echo "ad9a9472e8beb302f8b9ba2b3359bacc  tumorquantai_lymphoma_mds_manifest.csv" | md5sum -c -
sha256sum -c "$TQA_REPO/examples/lymphoma/checksums_all_21.sha256"
~~~

## Convert and inspect

The converter resolves the direct filenames through the downloaded manifest,
verifies their checksums, and writes the L0 primary and L2 companion Tagged
Image File Format (TIFF) files.

~~~bash
export TQA_REPO="${TQA_REPO:-$PWD}"
export TQA_DATA="/mounted/storage/tumorquantai-all-21"

python "$TQA_REPO/bin/mds_to_tiff.py" \
  --input "$TQA_DATA" \
  --manifest "$TQA_DATA/tumorquantai_lymphoma_mds_manifest.csv" \
  --output-dir "$TQA_DATA/slides" \
  --levels 0 2 \
  --expected-count 21 \
  --source-mpp 0.261780 \
  --resume

cd "$TQA_REPO"
./tumorquantai inspect "$TQA_DATA/slides" \
  --sample-sheet "$TQA_DATA/slides/samples.csv" \
  --output "$TQA_DATA/inspection"
~~~

Open `inspection/INSPECTION.html` and
`inspection/inspection_manifest.csv`. Require exactly 21 unique complete
L0/L2 pairs at source resolution 0.261780 micrometres per pixel (MPP). Stop if
the roster, pairing, or physical scale differs.

## Run all detected tissue tiles

Source MPP describes the input pixel size. Target/model MPP is separate. Full
means 100% of detected tissue tiles, not every background pixel.

After authorized HistoPLUS access is configured:

~~~bash
export TQA_REPO="${TQA_REPO:-$PWD}"
export TQA_DATA="/mounted/storage/tumorquantai-all-21"

cd "$TQA_REPO"
./tumorquantai run "$TQA_DATA/slides" \
  --sample-sheet "$TQA_DATA/slides/samples.csv" \
  --output "$TQA_DATA/results-full" \
  --work-dir "$TQA_DATA/work-full" \
  --preset full \
  --source-mpp 0.261780 \
  --profile auto
~~~

Keep results and resumable work in separate directories. Use `--cpu` or
`--gpu` only after `doctor` confirms the intended execution path.

## Check, resume, and retain audit evidence

~~~bash
export TQA_DATA="/mounted/storage/tumorquantai-all-21"

./tumorquantai status "$TQA_DATA/results-full"
./tumorquantai report "$TQA_DATA/results-full"
~~~

Require 21 included samples and no failed, incomplete, or excluded sample in
`aggregated_celltypes/sample_aggregation_audit.csv`. A failure is not a
biological zero and must not create a numeric matrix column.

Press Ctrl+C to stop. Repeat the same download, conversion, or run command with
the same paths. Verified files and valid Nextflow tasks are reused. Keep the
conversion manifest and work directory until outputs and the audit are
verified and backed up. Remove only the named collection directory after
checking its resolved mount.

Next, review [counts versus fractions](../explanation/counts-fractions.md) and
the [output reference](../reference/outputs.md).
