# Public lymphoma WSI example files

These files support the public tutorials for Zenodo record `21466410`, DOI `10.5281/zenodo.21466410`.

## Included artifacts

| File | Purpose |
| --- | --- |
| `tumorquantai_lymphoma_mds_manifest.csv` | Repository copy of the public manifest for review and offline planning |
| `zenodo_one.urls.txt` | Direct public URL for sample 022 |
| `zenodo_first_four.urls.txt` | Direct URLs for samples 022, 002, 006, and 016 |
| `zenodo_all_21.urls.txt` | Direct URLs for all 21 published MDS files |
| `checksums_one.sha256` | SHA-256 verification for sample 022 |
| `checksums_first_four.sha256` | SHA-256 verification for the fixed four-slide example |
| `checksums_all_21.sha256` | SHA-256 verification for the complete collection |
| `sample_sheet_first4.csv` | Fixed four-slide sample selection |
| `verify_fast21_outputs.py` | Verifier for 4- or 21-slide 10% results |

## QuickStart Example 1

```bash
# Clone, install, and prepare the fixed public WSI.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
./tumorquantai install --docker
export PATH="$HOME/.local/bin:$PATH"
tumorquantai quickstart --no-inference
```

## Full 21-slide download and conversion

```bash
# Create the relative tutorial download directory.
mkdir -p tutorial-data/lymphoma-21/download

# Download all 21 public MDS files.
while IFS= read -r url; do
  filename="${url##*/}"
  filename="${filename%%\?*}"
  wget --continue \
    --output-document "tutorial-data/lymphoma-21/download/$filename" \
    "$url"
done < examples/lymphoma/zenodo_all_21.urls.txt

# Convert verified MDS files through the installed command.
tumorquantai convert tutorial-data/lymphoma-21/download \
  --manifest examples/lymphoma/tumorquantai_lymphoma_mds_manifest.csv \
  --output tutorial-data/lymphoma-21/slides \
  --levels 0 2 \
  --expected-count 21 \
  --source-mpp 0.261780 \
  --resume
```

See [`docs/full_tutorial.md`](../../docs/full_tutorial.md) for manifest download, checksum verification, HistoPLUS access, 10% execution, resume, and output verification.

Public files and documentation use privacy-sanitized aliases only. Never add private mappings, clinical data, model weights, or tokens to this directory.
