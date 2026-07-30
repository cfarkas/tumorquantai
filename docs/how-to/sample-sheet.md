# Create a sample sheet

| | |
| --- | --- |
| **For** | Users who need stable sample IDs or non-default slide locations |
| **Hands-on steps** | Write two columns, inspect, correct duplicates |
| **Prerequisites** | Prepared primary slide files and neutral, non-PHI sample aliases |
| **Download/storage** | None; the CSV and inspection manifest are small |
| **Writes to** | A user-created CSV and a separate inspection output |

Use UTF-8 CSV with `sample_id,slide_path`:

```csv
sample_id,slide_path
sample_001_block_a,case_001/1_L0_rgb.tif
sample_002_block_a,case_002/1_L0_rgb.tif
```

Paths may be relative to the input directory or absolute. Sample IDs become
output directory and matrix-column identifiers. Do not use names, accession
numbers, or other patient identifiers.

## Validate it without inference

```bash
./tumorquantai inspect /data/slides \
  --sample-sheet /data/slides/samples.csv \
  --output /data/tumorquantai-inspection
```

Expected success is a manifest containing exactly one row per sample sheet
entry. Duplicate IDs, duplicate slide paths, missing files, unsafe paths, and
unexpected companions must fail or be reported for review.

The sample sheet controls slide IDs; an optional aggregation mapping is a
separate advanced concept. Pooling multiple slides into one biological sample
must retain every included and excluded source slide in the audit.

## Stop and clean up

Press **Ctrl+C** and rerun after editing the CSV. Remove only the separate
inspection output; keep the reviewed sample sheet with run provenance.

**Next:** [choose smoke, fast, or full](choose-preset.md).
