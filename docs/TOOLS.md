# Tool reference

## `run.sh`

User-facing launcher. It validates prerequisites, chooses CPU/GPU, mounts only
input/output/model-cache paths, and invokes the sample-scattered Nextflow
workflow. Run `./run.sh --help` for its current strict options.
`--max-parallel-slides` controls inter-slide concurrency and defaults to 1,
which is safe for a single GPU; `--num-workers` controls only data loading
inside each slide task. Docker profiles allocate `--shm-size 2g` by default to
prevent DataLoader bus errors; the launcher accepts a validated override.
`--full` enforces 100% processing. `--fast` defaults to 10% and may be
combined with `--percent-slide` below 100; `--mode full|fast` provides the
same choices. A standalone `--percent-slide` remains supported.
`--histoplus-revision` accepts only a full 40-hex immutable commit.

## `bin/discover_slides.py`

Creates a TSV/JSON input manifest without opening pixel data:

```bash
python bin/discover_slides.py \
  --input-root /data/exported \
  --output slides.tsv \
  --json slides.json \
  --exclude-root /data/results
```

Default patterns select L0 TIFFs only. Duplicate inferred or explicit sample
IDs fail with an actionable error. The Nextflow wrapper sets `--l2-policy` to
`required` for collage sampling or any run below 100%, and `ignore` for full
runs. Relevant companions are stream-hashed into the manifest so their contents
participate in slide-task cache identity.

## `lazyslide_histoplus_wsi_celltype.py`

The production inference engine. Common single-slide command:

```bash
python lazyslide_histoplus_wsi_celltype.py \
  --input-slide /data/case/1_L0_rgb.tif \
  --output /results/case_1 \
  --mpp 0.5 \
  --device cuda \
  --convert-to-pyramidal \
  --plain-csv
```

Notable controls:

- `--percent-slide`, `--patch-random-seed`: reproducible tile sampling
- `--collage`, `--max-sampled-patches`: sampled-patch exports
- `--histoplus-weight-file`, `--hf-token-file`: model resolution
- `--histoplus-revision`: immutable HistoPLUS repository commit
- `--overlay-*`: cell annotation rendering
- `--export-qupath`: QuPath-compatible annotations
- `--qc-patch-count`: dense QC regions
- `--run-cells-stage`: optional InstanSeg stage before HistoPLUS

HistoPLUS cell typing runs regardless of `--run-cells-stage`.

## `bin/aggregate_histoplus_celltypes.py`

Builds validated cell-type-by-sample raw-count and fraction matrices:

```bash
python bin/aggregate_histoplus_celltypes.py \
  --input-root /results \
  --expected-percent-slide 10
```

The optional mapping CSV has `slide_id,sample_id` columns. Mapping multiple
slides to one sample intentionally sums counts before calculating fractions.
Every slide in the aggregation roster, including failed slides, must be mapped so failures cannot be hidden inside a pooled sample.

Mixed sampling percentages/seeds fail by default because raw-count comparisons
would be misleading. `--allow-mixed-sampling` is an explicit override.
The Nextflow and fast-batch manifests are auto-detected; if both exist, select one explicitly with `--manifest`. A supplied manifest is authoritative: unlisted stale folders and rows with
`selected=false` cannot enter the matrix. Header-only count tables are accepted
only when `summary.json` explicitly declares a verified zero-detection result.

## `bin/lazyslide_histoplus_post_spatial_report.py`

Reads existing coordinates and creates spatial ROI plus UMAP/PCA reports; it
does not rerun the model:

```bash
python bin/lazyslide_histoplus_post_spatial_report.py \
  --output-root /results \
  --num-rois 9 \
  --roi-detail-pages \
  --embedding-method auto
```

If a summary contains a stale/unmounted TIFF path, use `--slide` in single-slide
mode. Polygon-derived embedding features require `--use-npy-polygons` and more
memory.

## `bin/build_cohort_pptx.py`

Builds a compact multi-sample presentation from generated PDFs/PNGs:

```bash
python bin/build_cohort_pptx.py \
  --root /results \
  --out /results/reports/cohort_report.pptx \
  --compact-first-pages \
  --clean-cache \
  --force-render
```

Use the validated standalone aggregator for scientific matrices. The deck's
companion CSVs are presentation conveniences and use samples-as-rows layout.

## `bin/clinical_histoplus_ml.py`

Links a private clinical workbook one-to-one with validated count/fraction
matrices, exports the requested merged dataframe and linkage audit, performs
FDR-adjusted descriptive stratification, and compares prespecified clinical,
HistoPLUS, and combined feature sets with repeated nested cross-validation.
Patient grouping is supported with `--patient-id-column`; all preprocessing and
tuning stay inside training folds. See [the clinical ML guide](CLINICAL_ML.md).

## Current MDS tutorial tools

`bin/download_zenodo_mds.py` reads the strict schema-version-2 authoritative
manifest from the same version-specific Zenodo record, downloads selected MDS
files with resumable transfers, and
verifies size, MD5, and SHA-256. `--expected-count` makes the one-, four-, and
21-slide paths fail closed. Repeating a larger selection safely expands the
local verified roster. Restricted downloads use a mode-0600 token file and are
stored under a mode-0700 root.

`bin/mds_to_tiff.py` converts only internal `DSI0` pixels to canonical L0/L2
BigTIFF. Supply the downloaded MDS manifest so source checksums, MPP, level
count, and dimensions are verified. `--resume` reuses only TIFFs whose source,
settings, geometry, and SHA-256 match `mds_conversion_manifest.json`. Start
with the one-slide dry run in the lymphoma tutorial.

`bin/prepare_zenodo_mds.py` and `bin/zenodo_mds_deposit.py` are curator-only
tools for privacy-sanitized staging and creation of a restricted, unpublished
draft. Preparation requires a matching ordered aggregate SHA-256 over every
`DSI0` stream name, length, and byte in the source and staged copies; the schema-version-2 manifest records it
as `pixel_full_sha256`. The depositor cannot publish.

## Legacy preconverted-TIFF release tools

`bin/prepare_zenodo_lymphoma.py`, `bin/download_zenodo_dataset.py`, and
`bin/zenodo_deposit.py` support the earlier preconverted-TIFF release layout.
They are not used by the current raw-MDS lymphoma tutorial.
