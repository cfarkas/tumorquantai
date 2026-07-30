# Tutorial: four public slides at 10%

| | |
| --- | --- |
| **For** | Users who completed and reviewed the one-slide path |
| **Hands-on steps** | Verify mount, add three fixed MDS files, resume conversion, inspect four-slide roster, infer 10%, audit |
| **Prerequisites** | Completed one-slide preparation, authorized HistoPLUS access, Java/Nextflow/Docker or prepared local environment |
| **Download** | Four fixed MDS files total 917,772,288 bytes; existing alias 022 is reused |
| **Storage** | Plan approximately 30 GB for raw, conversion, work, and results; verify actual free space first |
| **Writes to** | Separate raw/conversion, `discovery-four`, `fast-four-slides`, and `work-fast` paths |

This advanced progression is not invoked by `quickstart`. The beginner command
is deliberately capped at one slide. All files are public on Zenodo record
`21466410`; no Zenodo token is required.

## Select the fixed four

The four aliases are 022, 002, 006, and 016:

```bash
export TQA_ROOT=/mounted/storage/tqa-lymphoma
export TQA_RAW="$TQA_ROOT/data"
export TQA_RUNS="$TQA_ROOT/runs"
export TQA_MANIFEST="$PWD/examples/lymphoma/tumorquantai_lymphoma_mds_manifest.csv"

mkdir -p "$TQA_ROOT"
findmnt -T "$TQA_ROOT"
df -hT "$TQA_ROOT"
test -w "$TQA_ROOT"

python bin/download_zenodo_mds.py \
  --record 21466410 \
  --manifest "$TQA_MANIFEST" \
  --output-dir "$TQA_RAW" \
  --sample-id TumorQuantAI_LymphomaWSI_022 \
  --sample-id TumorQuantAI_LymphomaWSI_002 \
  --sample-id TumorQuantAI_LymphomaWSI_006 \
  --sample-id TumorQuantAI_LymphomaWSI_016 \
  --expected-count 4
```

The downloader verifies any existing file before reuse and downloads only
missing selections.

## Convert and inspect

```bash
python bin/mds_to_tiff.py \
  --input "$TQA_RAW/raw" \
  --manifest "$TQA_MANIFEST" \
  --output-dir "$TQA_RAW/slides" \
  --levels 0 2 \
  --sample-id TumorQuantAI_LymphomaWSI_022 \
  --sample-id TumorQuantAI_LymphomaWSI_002 \
  --sample-id TumorQuantAI_LymphomaWSI_006 \
  --sample-id TumorQuantAI_LymphomaWSI_016 \
  --expected-count 4 \
  --resume

./tumorquantai inspect "$TQA_RAW/slides" \
  --sample-sheet "$PWD/examples/lymphoma/sample_sheet_first4.csv" \
  --output "$TQA_RUNS/discovery-four"
```

Expected inspection finds exactly four unique L0/L2 pairs at source MPP
`0.261780`.

## Run 10% into a distinct root

```bash
./tumorquantai run "$TQA_RAW/slides" \
  --sample-sheet "$PWD/examples/lymphoma/sample_sheet_first4.csv" \
  --output "$TQA_RUNS/fast-four-slides" \
  --work-dir "$TQA_RUNS/work-fast" \
  --preset fast \
  --source-mpp 0.261780

./tumorquantai status "$TQA_RUNS/fast-four-slides"
```

Expected audit: four included, zero excluded. Review every slide overlay; a
cohort matrix alone is not sufficient QC. Ten-percent counts are sampled-tile
counts and must not be multiplied by ten.

## Stop, resume, and clean up

Press **Ctrl+C** and repeat the identical command. Existing verified downloads,
conversion state, and valid Nextflow tasks are reused. Keep `work-fast` while
resume matters. Remove only the named four-slide result/work paths after
verification; retain shared raw/conversion data if continuing.

**Next:** read the [full-collection resource warning](full-collection.md)
before deciding whether 100% processing is scientifically and operationally
justified.
