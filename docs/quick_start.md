<a id="quick-start"></a>

# QuickStart Example 1: one public WSI

This tutorial downloads one public lymphoma WSI, validates its published identity, converts Motic MDS pyramid levels L0 and L2 to TIFF, inspects the slide, and optionally runs a deterministic 1% HistoPLUS analysis.

![One-slide QuickStart workflow](assets/tutorial/quickstart_wsi_flow.svg)

## Public sample

| Item | Fixed value |
| --- | --- |
| Zenodo record | `21466410` |
| Dataset DOI | `10.5281/zenodo.21466410` |
| Sample | `TumorQuantAI_LymphomaWSI_022` |
| File | `TumorQuantAI_LymphomaWSI_022.mds` |
| Download size | `125350400` bytes |
| MD5 | `94bb5b08ccf1957f8c42a579e8b33cfb` |
| SHA-256 | `db2988b5c6bc791510cec4127106509e604e577feafdb15b94c149043ed7067a` |
| Source MPP | `0.261780` µm/pixel |
| Converted levels | L0 and L2 |
| Optional inference | Seeded 1% of detected tissue tiles |

The public download needs no Zenodo credential. HistoPLUS access is required only for inference.

## Estimated time and storage

The 125 MB MDS file expands to multi-gigabyte TIFF data. Conversion time depends on storage speed and CPU. The optional HistoPLUS step can be substantially longer, especially on CPU. Keep the download, converted TIFFs, Nextflow work, model cache, and final results on a verified storage filesystem with several gigabytes of free space.

## 1. Clone TumorQuantAI

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
```

## 2. Install the tutorial dependencies

```bash
# Create and activate the tutorial environment.
python3 -m venv .venv
. .venv/bin/activate

# Install the host-side download and conversion requirements.
python -m pip install --upgrade pip
python -m pip install -r requirements-tutorial.txt
```

## 3. Set the output root

Edit only the path below:

```bash
# Set the only path that must be changed.
TQA_ROOT=/path/to/mounted/storage/tumorquantai-quickstart

# Create and verify the selected storage directory.
mkdir -p "$TQA_ROOT"
findmnt -T "$TQA_ROOT"
df -hT "$TQA_ROOT"
test -w "$TQA_ROOT"
```

Do not place the public WSI, converted TIFFs, work directory, or results inside the Git repository.

## 4. Preview the bounded plan

```bash
# Check storage and print the one-slide plan without downloading anything.
./tumorquantai quickstart \
  --output "$TQA_ROOT" \
  --cpu \
  --dry-run
```

The plan is fixed to one slide, L0/L2 conversion, source MPP `0.261780`, and the `smoke` preset.

## 5. Download, verify, convert, and inspect

```bash
# Prepare the public WSI without running HistoPLUS.
./tumorquantai quickstart \
  --output "$TQA_ROOT" \
  --cpu \
  --no-inference
```

The command:

1. downloads the authoritative public manifest;
2. downloads only sample 022 with resume support;
3. checks the manifest identity, file size, MD5, and SHA-256;
4. converts only L0 and L2 with resumable state;
5. writes a sample sheet and model-free inspection;
6. writes `START_HERE.html`.

Expected final message:

```text
One-slide data preparation and model-free inspection complete.
Open first: /path/to/mounted/storage/tumorquantai-quickstart/START_HERE.html
```

## 6. Review the prepared data

```bash
# List the main preparation outputs.
find "$TQA_ROOT" -maxdepth 3 -type f \
  \( -name 'START_HERE.html' \
  -o -name 'INSPECTION.html' \
  -o -name 'inspection_manifest.csv' \
  -o -name 'samples.csv' \
  -o -name '*_L0_rgb.tif' \
  -o -name '*_L2_rgb.tif' \) \
  -print
```

The prepared directory resembles:

```text
tumorquantai-quickstart/
├── download/
│   ├── tumorquantai_lymphoma_mds_manifest.csv
│   └── raw/TumorQuantAI_LymphomaWSI_022/1.mds
├── converted/
│   ├── TumorQuantAI_LymphomaWSI_022/1_L0_rgb.tif
│   ├── TumorQuantAI_LymphomaWSI_022/1_L2_rgb.tif
│   └── samples.csv
├── inspection/
│   ├── INSPECTION.html
│   └── inspection_manifest.csv
├── START_HERE.html
└── tumorquantai_report.json
```

Review the inspection roster and source MPP before inference.

## 7. Configure HistoPLUS access

Follow [Configure authorized HistoPLUS access](how-to/model-access.md). Do not place a token value on the command line or commit a weight file.

```bash
# Recheck the host and configured model-access path.
./tumorquantai doctor \
  --output "$TQA_ROOT" \
  --online
```

Missing model access does not invalidate the downloaded or converted public data.

## 8. Run the one-slide 1% analysis

```bash
# Run the deterministic one-slide 1% analysis on CPU.
./tumorquantai quickstart \
  --output "$TQA_ROOT" \
  --cpu
```

Use `--gpu` instead of `--cpu` only after the doctor confirms the NVIDIA host and Docker runtime. The command reuses the prepared data and valid cached tasks.

## 9. Verify the outputs

```bash
# Verify the required one-slide summary, overlay, counts, and audit.
python3 examples/quickstart/verify_outputs.py \
  --tutorial-root "$TQA_ROOT"
```

A successful verifier ends with:

```text
SUCCESS: one-slide TumorQuantAI QuickStart outputs are complete.
```

Review in this order:

1. `$TQA_ROOT/START_HERE.html`
2. `$TQA_ROOT/smoke-results/TumorQuantAI_LymphomaWSI_022/overlays/celltypes_overview_and_zoom.png`
3. `$TQA_ROOT/smoke-results/TumorQuantAI_LymphomaWSI_022/summary/summary.json`
4. `$TQA_ROOT/smoke-results/TumorQuantAI_LymphomaWSI_022/cell_types/class_counts.csv`
5. `$TQA_ROOT/smoke-results/aggregated_celltypes/sample_aggregation_audit.csv`

The counts describe the selected 1% of tissue tiles. Do not multiply them by 100.

## Stop and resume

Press **Ctrl+C** to stop. Repeat the identical command with the same `TQA_ROOT`. Verified downloads, converted TIFFs, and valid Nextflow tasks are reused.

Individual preparation stages are also available:

```bash
# Download and verify only the public file.
./tumorquantai quickstart \
  --output "$TQA_ROOT" \
  --download-only

# Convert an already verified download.
./tumorquantai quickstart \
  --output "$TQA_ROOT" \
  --convert-only

# Regenerate preparation and inspection without inference.
./tumorquantai quickstart \
  --output "$TQA_ROOT" \
  --no-inference
```

## Continue

- [Full tutorial: all 21 lymphoma WSIs at 10%](full_tutorial.md)
- [Apply TumorQuantAI to your own WSIs](own_data.md)
- [Output files](outputs.md)
- [Troubleshooting](troubleshooting/index.md)