# Run TumorQuantAI

The beginner command-line interface expands a short command into the existing `run.sh` and Nextflow workflow while preserving the selected input, output, work directory, sampling, seed, source MPP, container, and model identity.

```text
tumorquantai run
        |
        +-- inspect and validate inputs
        +-- select CPU, GPU, or prepared local profile
        +-- write a run manifest
        +-- start Nextflow
        +-- isolate every slide for retry and resume
        +-- aggregate completed slides and audit exclusions
```

## Start with inspection

```bash
# Inspect the input roster without HistoPLUS inference.
tumorquantai inspect /path/to/slides \
  --output /path/to/tumorquantai-inspection \
  --source-mpp 0.261780
```

Open the inspection report and resolve missing L2 companions, duplicate warnings, unknown scale, or unexpected sample IDs before running.

## Choose a preset

![TumorQuantAI sampling presets](assets/tutorial/sampling_presets.svg)

| Preset | Percent of detected tissue tiles | Typical use |
| --- | ---: | --- |
| `smoke` | 1% from one selected slide | First authorized inference check |
| `fast` | 10% | Reproducible exploratory cohort analysis |
| `full` | 100% | Exhaustive processing after smaller runs pass review |

The random seed is recorded. The same input, preset, seed, and configuration select the same sampled tissue tiles.

## Run one slide at 1%

```bash
# Run one selected sample on CPU.
tumorquantai run /path/to/slides \
  --sample-sheet /path/to/slides/samples.csv \
  --output /path/to/results-smoke \
  --work-dir /path/to/work-smoke \
  --preset smoke \
  --sample case_001 \
  --source-mpp 0.261780 \
  --cpu
```

## Run a cohort at 10%

```bash
# Run all selected samples at a deterministic 10% on GPU.
tumorquantai run /path/to/slides \
  --sample-sheet /path/to/slides/samples.csv \
  --output /path/to/results-10-percent \
  --work-dir /path/to/work-10-percent \
  --preset fast \
  --source-mpp 0.261780 \
  --gpu
```

Use `--cpu` instead of `--gpu` when GPU execution is unavailable. CPU and GPU comparisons must use separate output and work directories.

## Run all detected tissue

```bash
# Run every detected tissue tile only after smaller runs pass review.
tumorquantai run /path/to/slides \
  --sample-sheet /path/to/slides/samples.csv \
  --output /path/to/results-full \
  --work-dir /path/to/work-full \
  --preset full \
  --source-mpp 0.261780 \
  --gpu
```

`full` means 100% of detected tissue tiles, not every background pixel.

## CPU, GPU, and local profiles

| Option | Behavior |
| --- | --- |
| `--cpu` | Maintained CPU container and CPU HistoPLUS execution |
| `--gpu` | Maintained GPU container; requires NVIDIA host and Docker runtime |
| `--profile auto` | Select GPU only when the host and Docker runtime are visible; otherwise CPU |
| `--profile local` | Expert-prepared local environment without Docker |

Run `tumorquantai doctor` before a new execution profile.

```bash
# Check a planned GPU result and work location.
tumorquantai doctor \
  --input /path/to/slides \
  --output /path/to/results-10-percent \
  --work-dir /path/to/work-10-percent \
  --online
```

## Select samples

Use a sample sheet for exact sample identity. Add stable include or exclude globs when needed:

```bash
# Process cohort_A samples while excluding repeat samples.
tumorquantai run /path/to/slides \
  --sample-sheet /path/to/slides/samples.csv \
  --output /path/to/results-cohort-A \
  --work-dir /path/to/work-cohort-A \
  --preset fast \
  --source-mpp 0.261780 \
  --include 'cohort_A*' \
  --exclude '*repeat*' \
  --cpu
```

## Use an explicit seed

```bash
# Run 10% with an explicit deterministic seed.
tumorquantai run /path/to/slides \
  --output /path/to/results-seed-20260709 \
  --work-dir /path/to/work-seed-20260709 \
  --preset fast \
  --source-mpp 0.261780 \
  --seed 20260709 \
  --cpu
```

Do not compare sampled runs that used different seeds without accounting for the changed tile selection.

## Discovery-only dry run

```bash
# Validate discovery and print the expanded plan without inference.
tumorquantai run /path/to/slides \
  --output /path/to/results-dry-run \
  --preset fast \
  --source-mpp 0.261780 \
  --cpu \
  --dry-run
```

A dry run writes discovery and run-planning metadata but no biological prediction.

## Stop and resume

Press **Ctrl+C** to stop. Repeat the exact command with the same output and work directories. Resume is enabled by default.

```bash
# Display current completion state and the exact local resume command.
tumorquantai status /path/to/results-10-percent
```

TumorQuantAI refuses to mix incompatible runs in one output directory. Use a new output root when changing:

- preset or percent;
- seed;
- source MPP;
- CPU/GPU/local profile;
- selected samples;
- expert passthrough arguments.

Do not move or delete an active Nextflow work directory. Do not run `nextflow clean -f` until outputs are verified and backed up.

## Failure handling

Each slide runs independently. A slide can retry without rerunning completed slides. When continuation is enabled, other slides can finish after one sample fails.

A failed or incomplete sample:

- remains in `sample_aggregation_audit.csv`;
- has no numeric cohort-matrix column;
- is not interpreted as a biological zero;
- can be retried with the same command.

## Generate the report

```bash
# Regenerate the portable run summary.
tumorquantai report /path/to/results-10-percent
```

Open `START_HERE.html`, then review overlays, summaries, the aggregation audit, and cohort tables.

## Direct expert execution

The beginner CLI is recommended for routine use. The compatible expert interfaces remain available:

```bash
# Display the lower-level shell launcher options.
./run.sh --help

# Display the complete beginner and parameter-file options.
tumorquantai run --help
```

Direct `nextflow run` and `run.sh` usage require the user to manage protected parameters, model access, paths, resources, and provenance correctly. See [CLI reference](reference/cli.md), [Parameters](reference/parameters.md), and [Configuration](reference/configuration.md).

## Continue

- [Apply to your own WSIs](own_data.md)
- [Output files](outputs.md)
- [Troubleshooting](troubleshooting/index.md)