# Other example run: four public WSIs at 10%

This intermediate example uses public lymphoma aliases 022, 002, 006, and 016. It downloads four MDS files, validates them, converts L0/L2, inspects the roster, and processes a deterministic 10% of detected tissue tiles.

Complete [QuickStart Example 1](../quick_start.md) before this cohort example.

## 1. Clone TumorQuantAI

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
```

## 2. Install the tutorial environment

```bash
# Create and activate the tutorial environment.
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-tutorial.txt
```

## 3. Set the storage root

```bash
# Set the only path that must be changed and remember the repository root.
TQA_ROOT=/path/to/mounted/storage/tumorquantai-lymphoma-four
REPO_ROOT="$(pwd)"
mkdir -p "$TQA_ROOT"
findmnt -T "$TQA_ROOT"
df -hT "$TQA_ROOT"
test -w "$TQA_ROOT"
```

## 4. Download the manifest and four slides

```bash
# Download or resume the authoritative manifest.
wget --continue \
  --output-document "$TQA_ROOT/tumorquantai_lymphoma_mds_manifest.csv" \
  "https://zenodo.org/records/21466410/files/tumorquantai_lymphoma_mds_manifest.csv?download=1"

# Download or resume the fixed four public MDS files.
while IFS= read -r url; do
  filename="${url##*/}"
  filename="${filename%%\?*}"
  wget --continue \
    --output-document "$TQA_ROOT/$filename" \
    "$url"
done < examples/lymphoma/zenodo_first_four.urls.txt
```

## 5. Verify the downloads

```bash
# Verify the manifest and all four slide checksums.
echo "ad9a9472e8beb302f8b9ba2b3359bacc  $TQA_ROOT/tumorquantai_lymphoma_mds_manifest.csv" \
  | md5sum -c -
(
  cd "$TQA_ROOT"
  sha256sum -c "$REPO_ROOT/examples/lymphoma/checksums_first_four.sha256"
)
```

Stop if any checksum fails.

## 6. Convert and inspect

```bash
# Convert the fixed four MDS files to L0 and L2 TIFFs.
python bin/mds_to_tiff.py \
  --input "$TQA_ROOT" \
  --manifest "$TQA_ROOT/tumorquantai_lymphoma_mds_manifest.csv" \
  --output-dir "$TQA_ROOT/slides" \
  --levels 0 2 \
  --sample-id TumorQuantAI_LymphomaWSI_022 \
  --sample-id TumorQuantAI_LymphomaWSI_002 \
  --sample-id TumorQuantAI_LymphomaWSI_006 \
  --sample-id TumorQuantAI_LymphomaWSI_016 \
  --expected-count 4 \
  --source-mpp 0.261780 \
  --resume

# Inspect the exact four-slide roster without inference.
./tumorquantai inspect "$TQA_ROOT/slides" \
  --sample-sheet "$TQA_ROOT/slides/samples.csv" \
  --output "$TQA_ROOT/inspection"
```

Open `$TQA_ROOT/inspection/INSPECTION.html`. Require four unique L0/L2 pairs and source MPP `0.261780`.

## 7. Run the four-slide 10% analysis

```bash
# Process a deterministic 10% of detected tissue tiles from all four slides.
./tumorquantai run "$TQA_ROOT/slides" \
  --sample-sheet "$TQA_ROOT/slides/samples.csv" \
  --output "$TQA_ROOT/results-10-percent" \
  --work-dir "$TQA_ROOT/work-10-percent" \
  --preset fast \
  --source-mpp 0.261780 \
  --gpu
```

Replace `--gpu` with `--cpu` when GPU execution is unavailable.

## 8. Verify and review

```bash
# Verify four included 10% results and no failed samples.
python3 examples/lymphoma/verify_fast21_outputs.py \
  --output "$TQA_ROOT/results-10-percent" \
  --expected-samples 4
```

Require four included samples, four nonempty overlays, four summaries recording 10% sampling, and nonempty cohort count/fraction matrices.

Ten-percent counts are sampled-tile counts and must not be multiplied by ten.

## Stop and resume

Press **Ctrl+C** and repeat the exact conversion or inference command. Verified files and valid Nextflow tasks are reused.

Continue to the [full 21-slide tutorial at 10%](../full_tutorial.md).