# Download and convert MDS

The public lymphoma collection is Zenodo record 21466410, digital object
identifier (DOI) 10.5281/zenodo.21466410. Public downloads require no
credential. This example downloads alias 022 under its published direct
filename, verifies it, and converts image-pyramid levels L0 and L2. L0 is
the highest-resolution level; L2 is its lower-resolution companion.

Sample 022 is 125,350,400 bytes. Converted Tagged Image File Format (TIFF)
files can be substantially larger. Keep downloads, conversion, work, caches,
and results on verified mounted storage rather than in the repository.

## Verify the destination

Run from the repository root and replace `/mounted/storage` with the selected
filesystem.

~~~bash
export TQA_REPO="$PWD"
export TQA_DATA="/mounted/storage/tumorquantai-one-slide"

mkdir -p "$TQA_DATA"
findmnt -T "$TQA_DATA"
df -hT "$TQA_DATA"
test -w "$TQA_DATA"
~~~

## Download the manifest and sample

`wget -c` resumes partial transfers. `-O` keeps the standard Zenodo
filenames used by the manifest and checksum lists.

~~~bash
export TQA_DATA="/mounted/storage/tumorquantai-one-slide"

wget -c -O "$TQA_DATA/tumorquantai_lymphoma_mds_manifest.csv" \
  "https://zenodo.org/records/21466410/files/tumorquantai_lymphoma_mds_manifest.csv?download=1"
wget -c -O "$TQA_DATA/TumorQuantAI_LymphomaWSI_022.mds" \
  "https://zenodo.org/records/21466410/files/TumorQuantAI_LymphomaWSI_022.mds?download=1"
~~~

For the equivalent `curl` commands, see
[run one public slide](../start-here/public-slide.md). Keep the same destination
filenames.

## Verify the download

MD5 means Message-Digest Algorithm 5. SHA-256 means Secure Hash Algorithm
256-bit. All three checksum commands must print `OK`; the size test is silent
on success.

~~~bash
export TQA_DATA="/mounted/storage/tumorquantai-one-slide"

cd "$TQA_DATA"
echo "ad9a9472e8beb302f8b9ba2b3359bacc  tumorquantai_lymphoma_mds_manifest.csv" | md5sum -c -
test "$(stat -c %s TumorQuantAI_LymphomaWSI_022.mds)" -eq 125350400
echo "94bb5b08ccf1957f8c42a579e8b33cfb  TumorQuantAI_LymphomaWSI_022.mds" | md5sum -c -
echo "db2988b5c6bc791510cec4127106509e604e577feafdb15b94c149043ed7067a  TumorQuantAI_LymphomaWSI_022.mds" | sha256sum -c -
~~~

Stop before conversion if any identity, size, or checksum differs.

## Convert L0 and L2

The converter resolves the direct filename through the downloaded manifest.
L0 is the highest-resolution image used for analysis; L2 is its
lower-resolution companion. Source resolution is 0.261780 micrometres per
pixel (MPP).

~~~bash
export TQA_REPO="${TQA_REPO:-$PWD}"
export TQA_DATA="/mounted/storage/tumorquantai-one-slide"

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

Success writes
`slides/TumorQuantAI_LymphomaWSI_022/1_L0_rgb.tif`,
`slides/TumorQuantAI_LymphomaWSI_022/1_L2_rgb.tif`, `slides/samples.csv`,
and `slides/mds_conversion_manifest.json`. The manifest binds source
checksums, MPP, geometry, conversion settings, and output hashes.

## Resume and clean up

Press Ctrl+C and repeat the same download or conversion command with the same
paths. `wget -c` resumes the direct file, and `--resume` reuses only
verified TIFF state. Keep `mds_conversion_manifest.json` while resume matters.
Remove only the named one-slide directory after printing its value and
confirming its resolved mount.

Next, [inspect the prepared slide](../start-here/own-slides.md).
