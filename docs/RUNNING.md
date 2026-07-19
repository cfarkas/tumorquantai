# Running, resume, and failures

## The run pattern

Every analysis should follow the same sequence:

1. check the host;
2. discover the intended slide roster;
3. smoke-test one slide;
4. inspect visual and machine-readable QC;
5. run the cohort into a new output root; and
6. review both successful samples and the failure audit.

Use `./run.sh --help` for the complete launcher contract.

## Resume is enabled by default

Repeat the same command after an interruption. Nextflow reuses valid completed
tasks when inputs and relevant parameters have not changed.

```bash
./run.sh \
  --input-dir /data/slides \
  --output-dir /data/results-fast \
  --fast \
  --slide-mpp "$SOURCE_MPP" \
  --mpp 0.5
```

Disable cache reuse only when intentional:

```bash
./run.sh ... --no-resume
```

Changing an input fingerprint, the L2 companion, processing settings, source
MPP, or immutable model identity invalidates the affected task. Deleting a
published result does not delete the Nextflow work cache.

Do not run `nextflow clean -f` until outputs and audit tables have been backed
up and verified.

## Failures remain visible

Each failed slide is retried once by default. After retries, the workflow can
continue with other slides so the cohort audit is still produced.

Add `--fail-fast` when the whole workflow should stop after an exhausted sample.

Review:

```text
workflow_metadata/
aggregated_celltypes/sample_aggregation_audit.csv
aggregated_celltypes/aggregation_summary.json
```

A failed or incomplete sample is excluded from numeric matrices and retained in
the audit. It is never inserted as an all-zero biological sample.

## Output and work directories

Keep source, results, and scratch work separate:

```text
/data/slides/                    # read-only source exports
/data/results-fast/              # published fast outputs
/scratch/tumorquantai-work-fast/ # resumable Nextflow work
```

```bash
./run.sh \
  --input-dir /data/slides \
  --output-dir /data/results-fast \
  --work-dir /scratch/tumorquantai-work-fast \
  --fast
```

Retain the work directory while resume is useful. Use a new result and work
directory when switching between fast and full.

## Common first-run problems

### No slides discovered

- Check the input root.
- Confirm filenames match `*_L0_rgb.tif` or `*_L0_rgb.tiff`.
- Use `--pattern` only for intentional alternative formats.
- Inspect the discovery manifest before inference.

### Missing L2 companion

Sampled runs and requested collages need the matching lower-resolution
companion. Correct the export layout; do not substitute an unrelated image.

### Source MPP is missing

Obtain the physical scale from scanner/export provenance and pass
`--slide-mpp`. Do not copy a value from another study.

### Hugging Face authorization fails

Confirm model access was granted and the token file is readable only by its
owner:

```bash
stat -c '%a %n' ~/.config/lazyslide-histoplus/hf_token
```

Expected mode: `600`.

### Docker DataLoader bus error

The default Docker shared memory is `2g`. On a restricted host, try fewer
workers:

```text
--num-workers 0
```

### One slide repeatedly fails

Read its log and the Nextflow trace. Check file readability, free disk space,
physical resolution, container/GPU access, and whether the failure occurred
before or after inference. Do not delete the cohort audit.

## Aggregating an existing result

Aggregation runs automatically after the cohort workflow. To rebuild matrices
from an existing result root:

```bash
python bin/aggregate_histoplus_celltypes.py \
  --input-root /data/results-fast \
  --expected-percent-slide 10
```

The workflow manifest is authoritative and prevents unrelated stale result
folders from entering the matrix.
