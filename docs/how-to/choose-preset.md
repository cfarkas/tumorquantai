# Choose smoke, fast, or full

| | |
| --- | --- |
| **For** | Users choosing processing depth before inference |
| **Hands-on steps** | Compare presets, select a separate output, dry-run, execute |
| **Prerequisites** | Reviewed inspection manifest, verified source MPP, ready host/model |
| **Download/storage** | Container/model downloads may occur; work/results increase with processed tissue |
| **Writes to** | A distinct output-associated work/result pair per preset |

| Preset | Mapping | Purpose |
| --- | --- | --- |
| `smoke` | one selected slide, seeded 1%, fail fast | First real technical check |
| `fast` | seeded 10% by default | Exploratory composition and iteration |
| `full` | 100% of detected tissue tiles | Exhaustive run after QC/resource review |

## Run a dry plan

```bash
tumorquantai run /data/slides \
  --output /data/results-smoke \
  --preset smoke \
  --source-mpp "$SOURCE_MPP" \
  --cpu \
  --dry-run
```

The CLI prints the expanded `run.sh`/Nextflow mapping with secrets redacted and
states CPU/GPU selection, sampling, seed, result path, and work path.

Use exactly one of `--cpu` or `--gpu` when the execution path must be explicit.
Omit both to retain automatic selection. Existing automation may continue to
use `--profile cpu`, `--profile gpu`, `--profile auto`, or `--profile local`.

Execute by removing `--dry-run`. Use `--sample SAMPLE_ID` when inspection found
multiple slides and you need a specific smoke slide.

## Keep modes separate

```text
/data/results-smoke/  (default work: /data/results-smoke/.tumorquantai-work/)
/data/results-fast/   (default work: /data/results-fast/.tumorquantai-work/)
/data/results-full/   (default work: /data/results-full/.tumorquantai-work/)
```

Do not reuse one result root across fast and full. Counts from different
processed areas are not directly comparable. The main CLI refuses an
unsafe accidental mixture.

Sampling is deterministic for the same input fingerprint, percentage, and
seed. Fast counts are detected cells in sampled tissue tiles—not full-slide
counts. Never multiply by `100 / percent_slide`.

## Stop, resume, and clean up

Press **Ctrl+C**, keep the work directory, and repeat the identical command.
Use `status` for exact recovery instructions. Clean only the named result/work
pair after verifying outputs and audit tables.

**Next:** [review QC overlays](review-overlays.md) after the smoke run.
