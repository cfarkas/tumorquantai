# Public lymphoma WSI example files

These files support the public tutorials for Zenodo record `21466410`, DOI `10.5281/zenodo.21466410`.

## Included artifacts

| File | Purpose |
| --- | --- |
| `tumorquantai_lymphoma_mds_manifest.csv` | Repository copy of the strict public manifest for review and offline planning |
| `zenodo_one.urls.txt` | Direct public URL for sample 022 |
| `zenodo_first_four.urls.txt` | Direct URLs for samples 022, 002, 006, and 016 |
| `zenodo_all_21.urls.txt` | Direct URLs for all 21 published MDS files |
| `checksums_one.sha256` | SHA-256 verification for sample 022 |
| `checksums_first_four.sha256` | SHA-256 verification for the fixed four-slide example |
| `checksums_all_21.sha256` | SHA-256 verification for the complete collection |
| `sample_sheet_first4.csv` | Fixed four-slide sample selection |
| `verify_fast21_outputs.py` | Verifier for 4- or 21-slide 10% results |

During a real download, the authoritative manifest comes from Zenodo. The repository copy and generated URL/checksum files must remain consistent with it.

## QuickStart Example 1: one WSI at 1%

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai

# Create the tutorial environment.
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-tutorial.txt

# Set the only path that must be changed.
TQA_ROOT=/path/to/mounted/storage/tumorquantai-quickstart

# Prepare one public WSI without inference.
./tumorquantai quickstart \
  --output "$TQA_ROOT" \
  --cpu \
  --no-inference
```

After authorized HistoPLUS access is ready, repeat without `--no-inference` and verify with `examples/quickstart/verify_outputs.py`.

## Four public WSIs at 10%

Use `zenodo_first_four.urls.txt` and `checksums_first_four.sha256`, convert aliases 022, 002, 006, and 016, then run `./tumorquantai run ... --preset fast`.

See [`docs/tutorials/four-public-slides.md`](../../docs/tutorials/four-public-slides.md).

## Full 21-slide tutorial at 10%

```bash
# Set the only path that must be changed and remember the repository root.
TQA_ROOT=/path/to/mounted/storage/tumorquantai-lymphoma-21
REPO_ROOT="$(pwd)"
mkdir -p "$TQA_ROOT"

# Download all 21 standard public filenames.
while IFS= read -r url; do
  filename="${url##*/}"
  filename="${filename%%\?*}"
  wget --continue \
    --output-document "$TQA_ROOT/$filename" \
    "$url"
done < examples/lymphoma/zenodo_all_21.urls.txt

# Verify all 21 slide checksums.
(
  cd "$TQA_ROOT"
  sha256sum -c "$REPO_ROOT/examples/lymphoma/checksums_all_21.sha256"
)
```

After conversion and inspection, the maintained full tutorial runs:

```bash
# Process a deterministic 10% of detected tissue tiles from all 21 slides.
./tumorquantai run "$TQA_ROOT/slides" \
  --sample-sheet "$TQA_ROOT/slides/samples.csv" \
  --output "$TQA_ROOT/results-10-percent" \
  --work-dir "$TQA_ROOT/work-10-percent" \
  --preset fast \
  --source-mpp 0.261780 \
  --gpu

# Verify all 21 included samples and cohort tables.
python3 examples/lymphoma/verify_fast21_outputs.py \
  --output "$TQA_ROOT/results-10-percent"
```

See [`docs/full_tutorial.md`](../../docs/full_tutorial.md) for the complete download, manifest, conversion, inspection, run, resume, and review procedure.

## Public-data safety

Public files and documentation use privacy-sanitized aliases only. Never add source accessions, label images, private mappings, clinical data, protected health information, model weights, or tokens to this directory.