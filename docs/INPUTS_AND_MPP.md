# Inputs, L0/L2, and MPP

This page explains the two concepts that most often cause an incorrect first
run: which image is analyzed and what physical resolution to use.

## The standard portable layout

```text
/data/slides/
├── case_001/
│   ├── 1_L0_rgb.tif
│   └── 1_L2_rgb.tif
└── case_002/
    ├── 1_L0_rgb.tif
    └── 1_L2_rgb.tif
```

- **L0** is the primary, highest-resolution exported image. TumorQuantAI
  analyzes it.
- **L2** is a lower-resolution companion used by sampled-patch and overview
  artifacts.

By default, discovery selects only `*_L0_rgb.tif` and `*_L0_rgb.tiff`.
Companion files are not separate samples.

When processing less than 100%, or when requesting a collage, the matching L2
companion is required. Discovery stops before inference if a requested
companion is missing.

## Discover the exact roster

```bash
./run.sh \
  --input-dir /data/slides \
  --output-dir /data/discovery \
  --dry-run
```

Inspect `workflow_metadata/slides.tsv`. Do this before every new cohort or input
layout.

For unusual filenames, repeat `--pattern`:

```bash
./run.sh \
  --input-dir /data/slides \
  --pattern '*.svs' \
  --pattern '*.ome.tif' \
  --dry-run
```

Use a dedicated input directory. A broad `*.tif` pattern can select thumbnails,
companions, or generated images.

## Sample IDs

For the standard folder example, inferred IDs are `case_001_1` and
`case_002_1`. Use an explicit sample sheet when names need to be controlled:

```csv
sample_id,slide_path
sample_001_block_a,case_001/1_L0_rgb.tif
sample_002_block_a,case_002/1_L0_rgb.tif
```

```bash
./run.sh \
  --input-dir /data/slides \
  --sample-sheet /data/slides/samples.csv \
  --dry-run
```

Paths may be relative to `--input-dir` or absolute. Duplicate IDs and duplicate
slide paths are rejected.

Use neutral study aliases in public examples. Do not commit patient names,
accession numbers, clinical workbooks, or sample-level results.

## What MPP means

MPP is the physical pixel size in micrometres per pixel.

| Setting | Meaning |
| --- | --- |
| `--slide-mpp` | Verified physical resolution of the source L0 image |
| `--mpp` | Target physical resolution of model tiles; default `0.5` |

The target model MPP does not repair missing source metadata. TumorQuantAI must
know the source scale before it can construct tiles at the requested target
scale.

## How to obtain source MPP

Use, in priority order:

1. the scanner or export provenance supplied by the imaging facility;
2. a trusted sidecar created by the export process; or
3. reliable embedded TIFF/OpenSlide metadata.

You can inspect available properties:

```bash
openslide-show-properties /data/slides/case_001/1_L0_rgb.tif \
  | grep -Ei 'mpp|resolution|objective'
```

Generic TIFF resolution tags may describe display DPI rather than tissue
micrometres per pixel. If the imaging facility cannot confirm the physical
scale, stop and resolve it before inference.

## MPP examples are not universal defaults

A value that is correct for one scanner/export can be wrong for another.
Documentation therefore prompts for a verified value:

```bash
read -rp "Verified source L0 MPP: " SOURCE_MPP
```

Then pass:

```bash
--slide-mpp "$SOURCE_MPP" --mpp 0.5
```

The generated manifest and per-slide summary retain the source/target MPP for
audit.

## Motic MDS inputs

For the lymphoma teaching dataset, convert privacy-sanitized MDS files with the
bundled open reader:

```bash
python bin/mds_to_tiff.py \
  --input /data/raw \
  --manifest /data/tumorquantai_lymphoma_mds_manifest.csv \
  --output-dir /data/slides \
  --levels 0 2 \
  --expected-count 21
```

The converter reads only internal `DSI0` pixel tiles and writes the canonical
L0/L2 layout. The schema-version-2 manifest binds the input to its whole-file
checksums, geometry, MPP, and full aggregate `DSI0` digest produced during
privacy sanitization. Other MDS collections still require a verified source
MPP and a privacy review; do not assume that their embedded labels are safe.
