# Fast versus full

TumorQuantAI provides two explicit processing modes. Choose the mode before the
run and keep each mode in a separate output directory.

## Comparison

| Mode | Tissue tiles processed | Typical use | Main limitation |
| --- | ---: | --- | --- |
| `--fast` | Seeded subset; 10% by default | Smoke tests, iteration, exploratory cohort composition | Raw counts are sampled-tile counts |
| `--full` | 100% of detected tissue tiles | Exhaustive final processing | More GPU time, storage, and review effort |

## Recommended progression

1. Discover all slides with `--dry-run`.
2. Run one slide with `--fast --percent-slide 1`.
3. Review MPP, overlays, sampling, logs, and output ownership.
4. Run the cohort at 10% if exploratory composition is appropriate.
5. Use `--full` only when exhaustive processing is required and resources are
   available.

## Fast mode

```bash
./run.sh \
  --input-dir /data/slides \
  --output-dir /data/results-fast \
  --fast \
  --slide-mpp "$SOURCE_MPP" \
  --mpp 0.5 \
  --max-parallel-slides 1 \
  --profile auto
```

The default fast percentage is 10. Choose another percentage below 100 with
`--percent-slide`. Sampling uses a recorded seed, so identical inputs and
parameters select the same tile set.

Fast raw counts are detections in the sampled tissue tiles. They are not
validated whole-slide estimates and are not automatically extrapolated.

For samples with different tissue areas, prefer
`celltype_fractions_by_sample.csv` when comparing composition, and review the
sampled/total tile counts in the summary.

## Full mode

```bash
./run.sh \
  --input-dir /data/slides \
  --output-dir /data/results-full \
  --full \
  --slide-mpp "$SOURCE_MPP" \
  --mpp 0.5 \
  --max-parallel-slides 1 \
  --profile auto
```

Full means 100% of detected tissue tiles. It does not mean every pixel outside
detected tissue is processed.

## Keep modes separate

Do not switch modes inside one output root:

```text
/data/results-fast/
/data/results-full/
```

This prevents stale presentation files and sampled/full outputs from being
confused. Counts from different processed areas are not directly comparable.

## Resource settings

Start conservatively:

```text
--max-parallel-slides 1
--celltypes-batch-size 2
--num-workers 2
--cpus 8
--memory '32 GB'
```

Increase concurrency only after measuring GPU memory, CPU memory, storage
throughput, and shared-memory use on the actual host. Docker uses `2g` of
shared memory by default; `--num-workers 0` is a slower fallback on restricted
systems.
