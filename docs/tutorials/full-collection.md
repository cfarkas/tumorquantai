# Tutorial: full 21-slide collection

| | |
| --- | --- |
| **For** | Experienced users who reviewed the one- and four-slide checkpoints |
| **Hands-on steps** | Preflight capacity, download all 21, verify, resume conversion, inspect roster, run 100%, audit |
| **Prerequisites** | Approved study plan, authorized HistoPLUS access, stable compute, storage monitoring, completed smaller checkpoints |
| **Download** | 21 MDS files, 17,370,771,968 bytes, plus the manifest |
| **Storage** | L0/L2 conversion can approach 142 GB; budget at least 300 GB for conversion, work, and results and verify locally |
| **Writes to** | Dedicated full-data, discovery, result, and work paths |

!!! danger "Not a beginner smoke test"
    Full inference can be costly and long-running. Do not begin it merely to
    test installation. Use the one-slide 1% path first.

The public record is `21466410` (DOI `10.5281/zenodo.21466410`), matched to
software `v0.4.0`. It has no diagnostic annotations or pathologist ground
truth.

## Verify the destination before downloading

```bash
export TQA_ROOT=/mounted/storage/tqa-lymphoma-full
mkdir -p "$TQA_ROOT"
findmnt -T "$TQA_ROOT"
df -hT "$TQA_ROOT"
test -w "$TQA_ROOT"
```

Do not place this collection, converted TIFFs, Nextflow work, or model caches
inside the Git checkout, `/`, or an unverified home filesystem.

## Download and convert

```bash
export TQA_MANIFEST="$PWD/examples/lymphoma/tumorquantai_lymphoma_mds_manifest.csv"

python bin/download_zenodo_mds.py \
  --record 21466410 \
  --manifest "$TQA_MANIFEST" \
  --output-dir "$TQA_ROOT/data" \
  --expected-count 21

python bin/mds_to_tiff.py \
  --input "$TQA_ROOT/data/raw" \
  --manifest "$TQA_MANIFEST" \
  --output-dir "$TQA_ROOT/data/slides" \
  --levels 0 2 \
  --expected-count 21 \
  --resume

./tumorquantai inspect "$TQA_ROOT/data/slides" \
  --sample-sheet "$TQA_ROOT/data/slides/samples.csv" \
  --output "$TQA_ROOT/runs/discovery-full"
```

Expected inspection finds exactly 21 unique complete L0/L2 pairs with source
MPP `0.261780`. Stop if the roster differs.

## Run full detected tissue

```bash
./tumorquantai run "$TQA_ROOT/data/slides" \
  --sample-sheet "$TQA_ROOT/data/slides/samples.csv" \
  --output "$TQA_ROOT/runs/full-21-slides" \
  --work-dir "$TQA_ROOT/runs/work-full" \
  --preset full \
  --source-mpp 0.261780
```

Full means 100% of detected tissue tiles, not every background pixel. Expected
audit: 21 included and zero excluded. If any sample is failed or incomplete,
the run is not an all-zero biological sample; use `status` and resume.

## Stop, resume, and clean up

Press **Ctrl+C** and repeat the exact command to resume. Monitor free space
without moving an active work directory. Keep conversion manifests and
Nextflow work until outputs and audit are verified and backed up. Clean only
the explicit `$TQA_ROOT` subdirectory you intend; never clean an entire mount.

**Next:** review [counts versus fractions](../explanation/counts-fractions.md)
and the [output reference](../reference/outputs.md).
