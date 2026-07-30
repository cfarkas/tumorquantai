# Download and convert MDS

| | |
| --- | --- |
| **For** | Users preparing the public TumorQuantAI Zenodo MDS collection |
| **Hands-on steps** | Verify mount, download selected manifest rows, checksum, convert L0/L2, inspect |
| **Prerequisites** | Python dependencies from `requirements.txt` and adequate mounted storage |
| **Download** | Alias 022 is 125,350,400 bytes; the full collection is 17,370,771,968 bytes |
| **Storage** | Conversion can exceed source size substantially; keep raw, TIFF, work, and results separate |
| **Writes to** | `raw/`, checksums/state, `slides/`, and `mds_conversion_manifest.json` under the selected root |

The record is public: `21466410`, DOI `10.5281/zenodo.21466410`. Do not use a
Zenodo token for this path.

## One-slide safe path

```bash
export TQA_DATA=/mounted/storage/tqa-022-data
export TQA_MANIFEST="$PWD/examples/lymphoma/tumorquantai_lymphoma_mds_manifest.csv"

mkdir -p "$TQA_DATA"
findmnt -T "$TQA_DATA"
df -hT "$TQA_DATA"
test -w "$TQA_DATA"

python bin/download_zenodo_mds.py \
  --record 21466410 \
  --manifest "$TQA_MANIFEST" \
  --output-dir "$TQA_DATA" \
  --sample-id TumorQuantAI_LymphomaWSI_022 \
  --expected-count 1
```

The remote authoritative manifest must match the repository copy. The
downloader resumes safely and verifies size, MD5, SHA-256, selection count,
trusted origins, and safe paths.

Inspect and execute conversion:

```bash
python bin/mds_to_tiff.py \
  --input "$TQA_DATA/raw" \
  --manifest "$TQA_MANIFEST" \
  --output-dir "$TQA_DATA/slides" \
  --levels 0 2 \
  --sample-id TumorQuantAI_LymphomaWSI_022 \
  --expected-count 1 \
  --dry-run

python bin/mds_to_tiff.py \
  --input "$TQA_DATA/raw" \
  --manifest "$TQA_MANIFEST" \
  --output-dir "$TQA_DATA/slides" \
  --levels 0 2 \
  --sample-id TumorQuantAI_LymphomaWSI_022 \
  --expected-count 1 \
  --resume
```

Expected success writes canonical L0/L2 TIFFs, `samples.csv`, and
`mds_conversion_manifest.json` bound to source checksums, MPP, geometry,
conversion settings, and output hashes.

## Stop, resume, and clean up

Press **Ctrl+C**. Repeat the same download or conversion command; `--resume`
reuses only verified state. Do not delete `mds_conversion_manifest.json` while
resume matters. Clean only `$TQA_DATA` after printing and checking its resolved
mount.

**Next:** [inspect the prepared slide](../start-here/own-slides.md).
