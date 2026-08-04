# Other example run: four public WSIs at 10%

This intermediate example uses public lymphoma aliases 022, 002, 006, and 016. It downloads four MDS files, validates them, converts L0/L2, inspects the roster, and processes a deterministic 10% of detected tissue tiles.

## 1. Clone and install once

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai

# Install the command for the selected route; Docker is shown.
./tumorquantai install --docker
export PATH="$HOME/.local/bin:$PATH"
```

Do not create a separate tutorial Python environment.

## 2. Create the example folder

```bash
# Create the fixed relative folder used by this example.
mkdir -p tutorial-data/lymphoma-four/download
```

## 3. Download the manifest and four slides

```bash
# Download or resume the authoritative manifest.
wget --continue \
  --output-document tutorial-data/lymphoma-four/download/tumorquantai_lymphoma_mds_manifest.csv \
  "https://zenodo.org/records/21466410/files/tumorquantai_lymphoma_mds_manifest.csv?download=1"

# Download or resume the fixed four public MDS files.
while IFS= read -r url; do
  filename="${url##*/}"
  filename="${filename%%\?*}"
  wget --continue \
    --output-document "tutorial-data/lymphoma-four/download/$filename" \
    "$url"
done < examples/lymphoma/zenodo_first_four.urls.txt
```

## 4. Verify the downloads

```bash
# Verify the manifest and all four slide checksums.
echo "ad9a9472e8beb302f8b9ba2b3359bacc  tutorial-data/lymphoma-four/download/tumorquantai_lymphoma_mds_manifest.csv" \
  | md5sum -c -
(
  cd tutorial-data/lymphoma-four/download
  sha256sum -c ../../../examples/lymphoma/checksums_first_four.sha256
)
```

## 5. Convert and inspect

```bash
# Convert the four verified MDS files with the installed command.
tumorquantai convert tutorial-data/lymphoma-four/download \
  --manifest tutorial-data/lymphoma-four/download/tumorquantai_lymphoma_mds_manifest.csv \
  --output tutorial-data/lymphoma-four/slides \
  --levels 0 2 \
  --sample-id TumorQuantAI_LymphomaWSI_022 \
  --sample-id TumorQuantAI_LymphomaWSI_002 \
  --sample-id TumorQuantAI_LymphomaWSI_006 \
  --sample-id TumorQuantAI_LymphomaWSI_016 \
  --expected-count 4 \
  --source-mpp 0.261780 \
  --resume

# Inspect the exact four-slide roster without inference.
tumorquantai inspect tutorial-data/lymphoma-four/slides \
  --sample-sheet tutorial-data/lymphoma-four/slides/samples.csv \
  --output tutorial-data/lymphoma-four/inspection
```

## 6. Run the four-slide 10% analysis

```bash
# Process a deterministic 10% of detected tissue tiles from all four slides.
tumorquantai run tutorial-data/lymphoma-four/slides \
  --sample-sheet tutorial-data/lymphoma-four/slides/samples.csv \
  --output tutorial-data/lymphoma-four/results-10-percent \
  --preset fast \
  --source-mpp 0.261780 \
  --gpu
```

Use `--cpu` when GPU execution is unavailable.

## 7. Verify and review

```bash
# Verify four included 10% results and no failed samples.
python3 examples/lymphoma/verify_fast21_outputs.py \
  --output tutorial-data/lymphoma-four/results-10-percent \
  --expected-samples 4
```

Continue to the [full 21-slide tutorial](../full_tutorial.md).
