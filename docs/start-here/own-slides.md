# Inspect and run your own slide

| | |
| --- | --- |
| **For** | Researchers bringing exported H&E slides to TumorQuantAI |
| **Hands-on steps** | Check host, inspect roster, verify MPP, run one 1% smoke preset, review |
| **Prerequisites** | Python 3 for inspection; Java, Nextflow, Docker/local environment, and HistoPLUS access for inference |
| **Download** | None, unless the container or gated model is not cached |
| **Storage** | Input stays read-only; reserve separate space for work and results |
| **Writes to** | The explicit inspection/result paths in the commands below |

## 1. Arrange portable inputs

```text
/data/slides/
└── case_001/
    ├── 1_L0_rgb.tif
    └── 1_L2_rgb.tif
```

L0 is the highest-resolution primary image. L2 is a lower-resolution companion
used by sampled reports. A WSI is a whole-slide image; MPP is micrometres per
pixel. Read [WSI and pyramid levels](../explanation/wsi-pyramid.md) if these
terms are new.

## 2. Inspect without inference

```bash
./tumorquantai inspect /data/slides \
  --output /data/tumorquantai-inspection
```

Expected output reports each sample ID, selected primary file, companion,
format/pyramid metadata when available, source MPP or its absence, duplicates,
and storage estimates. Review the written manifest before proceeding.

Inspection does not load HistoPLUS and does not need a GPU. If a required
physical scale cannot be established, it fails closed for run readiness.
Obtain MPP from scanner/export provenance; do not guess it.

## 3. Check the host and model readiness

```bash
./tumorquantai doctor \
  --input /data/slides \
  --output /data/tumorquantai-smoke
```

Resolve every `FAIL`. A GPU warning can be acceptable when intentional CPU
execution is practical. Follow [model access](../how-to/model-access.md)
without putting a token value in shell history.

## 4. Run one 1% smoke test

```bash
read -rp "Verified source L0 MPP: " SOURCE_MPP

./tumorquantai run /data/slides \
  --output /data/tumorquantai-smoke \
  --preset smoke \
  --source-mpp "$SOURCE_MPP"
```

The expanded legacy/Nextflow command is printed before execution with secrets
redacted. Resume is on by default, resources are conservative, and work files
stay on the output-associated filesystem.

Success produces `/data/tumorquantai-smoke/START_HERE.html`. Review
`<sample>/overlays/celltypes_overview_and_zoom.png`,
`<sample>/summary/summary.json`, and
`aggregated_celltypes/sample_aggregation_audit.csv` before scaling.

## Stop, resume, and clean up

Press **Ctrl+C** to stop. Repeat the exact command to resume, or run:

```bash
./tumorquantai status /data/tumorquantai-smoke
```

Status prints the exact resume command and first relevant log. Keep the work
directory until no resume is needed. To clean, remove only the inspection and
smoke paths after printing and checking them; never remove the read-only input.

**Next:** [choose smoke, fast, or full](../how-to/choose-preset.md).
