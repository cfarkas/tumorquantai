# Review one public slide

This page explains the files produced by the 1% sample-022 run. Complete
[run one public slide](../start-here/public-slide.md) before using these checks.

## Check the inspection

Open inspection/INSPECTION.html and inspection/inspection_manifest.csv.
Comma-separated values (CSV) in the manifest should identify exactly one
whole-slide image (WSI), its image-pyramid levels L0 and L2 as Tagged Image
File Format (TIFF) files, and source resolution 0.261780 micrometres per pixel
(MPP). L0 is the highest-resolution image used for analysis; L2 is its
lower-resolution companion.

Stop before inference if the sample is duplicated, either image is missing, or
source MPP is absent or inconsistent.

## Check the overlay

Open
results-1-percent/TumorQuantAI_LymphomaWSI_022/overlays/celltypes_overview_and_zoom.png.
This image supports visual quality control (QC): check orientation, tissue
selection, and alignment of predicted points with cells.

HistoPLUS classes are model predictions, not pathologist ground truth. The
public dataset has no diagnostic annotations.

## Check scale and sampling

Open
results-1-percent/TumorQuantAI_LymphomaWSI_022/summary/summary.json.
JSON means JavaScript Object Notation. Confirm:

- source MPP is 0.261780;
- target/model MPP is recorded separately;
- sampling is 1% of detected tissue tiles;
- the random seed is recorded;
- the pinned model revision and container identity are present; and
- the sample is complete.

Source MPP describes the input pixel size. Target MPP describes the scale
presented to the model. Counts from this run describe sampled tiles, not the
whole slide, and must not be multiplied by 100.

## Check the aggregation audit

Open
results-1-percent/aggregated_celltypes/sample_aggregation_audit.csv. It should
contain one included sample and no failed or incomplete sample.

A completed sample may contain zero cells of a class. A failed, missing, or
incomplete sample has no numeric matrix column and cannot be interpreted as
zero.

## Check status or resume

Run this from the repository root. Replace /data only if the example was stored
elsewhere.

~~~bash
export TQA_DATA="/data/tumorquantai-one-slide"

./tumorquantai status "$TQA_DATA/results-1-percent"
./tumorquantai report "$TQA_DATA/results-1-percent"
~~~

If the run was interrupted, repeat the original run command with the same
result and work directories. Nextflow reuses valid cached tasks.

Next, [run four public slides](four-public-slides.md) only after the inspection,
overlay, summary, and audit checks pass.
