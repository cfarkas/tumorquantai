# Glossary

## WSI

**Whole-slide image.** A high-resolution digital representation of a glass
histology slide.

## H&E

**Haematoxylin and eosin.** A common histology stain. TumorQuantAI does not
replace stain or image-quality review.

## L0

The primary, highest-resolution exported image used for analysis.

## L2

A lower-resolution companion used by sampled-patch and overview artifacts. It
is not analyzed as a separate sample.

## MPP

**Micrometres per pixel.** A physical pixel-size measurement.
`--source-mpp` in the beginner CLI (legacy `run.sh --slide-mpp`) describes the
source image; engine `--mpp` describes the target model tile scale.

## Tissue tile

A rectangular image region selected after tissue detection. Fast mode processes
a seeded subset; full mode processes all detected tissue tiles.

## Fast mode

A reproducible sampled-tile run. It defaults to 10% and can use another
percentage below 100.

## Full mode

Processing of 100% of detected tissue tiles. It may take substantially more
time and storage.

## Sample

The stable identifier used for one slide column in output tables. Multiple
slides should be pooled into one biological sample only with an explicit,
audited sample map.

## Cell type

The HistoPLUS-predicted class assigned to a detected cell. It is a model output,
not pathologist ground truth.

## Count matrix

A CSV with cell types as rows and completed samples as columns. Values are
detected cells in the processed tissue tiles.

## Fraction matrix

The count matrix normalized within each nonempty sample. Each nonempty sample
column sums to one.

## Biological zero

A class absent from a completed sample, recorded as zero. This differs from an
incomplete or failed sample.

## Audit table

`sample_aggregation_audit.csv`, which records included, failed, missing, and
incomplete samples plus sampling metadata.

## Resume

Nextflow's reuse of valid completed tasks when inputs and parameters have not
changed. TumorQuantAI enables it by default.

## Smoke test

A deliberately small first run, usually one slide at 1%, used to verify the
environment, scale, visual alignment, outputs, and resume behavior.

## Model weight

A learned parameter file used by a model during inference. HistoPLUS weights
are gated and are not included in TumorQuantAI. An authorized local weight is
referenced read-only and never copied to outputs.

## Container

A packaged runtime filesystem used to keep software dependencies reproducible.
TumorQuantAI pins CPU/GPU container images by immutable digest. A container
does not include the gated model weight or study slides.

## Work directory

Nextflow's resumable task/cache area. It can be much larger than final results.
The beginner CLI keeps it on the selected output-associated filesystem by
default. Retain it while resume is useful.

## Structural demo

A credential-free run made from synthetic fixtures and a stub worker. It tests
software structure, failure auditing, aggregation, status, and reporting; its
counts/images have no biological or validation meaning.

## Clinical ML

Optional exploratory linkage of private clinical variables and validated
TumorQuantAI matrices. It is not a diagnostic or survival-prediction product.
