# What TumorQuantAI predicts

TumorQuantAI applies HistoPLUS to H&E whole-slide image tissue tiles. For each
detected cell it writes a predicted cell-type class and level-0 pixel
coordinates. It then summarizes detected classes per completed slide and
across a cohort.

The workflow adds reproducibility and audit controls around the model:
deterministic tile sampling, source fingerprints, source/target physical scale,
immutable model revision, container identity, per-slide retry/resume, visual
overlays, and failure-aware aggregation.

TumorQuantAI does not:

- diagnose disease or provide clinical advice;
- establish that a predicted class is pathologist ground truth;
- provide tumor-region segmentation unless a separately validated workflow
  does so;
- infer outcomes, treatment response, or lymphoma subtype;
- establish physical scale when source metadata/provenance is absent; or
- validate biological conclusions.

The public tutorial collection has no diagnostic annotations or pathologist
ground truth. A technically successful run therefore demonstrates workflow
operation, not model performance or clinical validity.

**Next:** read [research limitations](research-limitations.md) and
[review QC overlays](../how-to/review-overlays.md).
