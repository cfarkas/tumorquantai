# Sampling and reproducibility

A tissue tile is an image region selected after tissue detection. TumorQuantAI
offers:

- `smoke`: a seeded 1% subset for one first slide;
- `fast`: a seeded 10% subset by default; and
- `full`: 100% of detected tissue tiles.

Sampling is deterministic when the input fingerprint, tissue-selection
settings, percentage, and random seed are unchanged. The summary records the
seed plus sampled/total tile counts.

Deterministic does not mean representative. A 1% or 10% subset can miss spatial
heterogeneity. Visual QC, scientific design, and sensitivity analyses remain
the researcher's responsibility.

Raw fast-mode counts are detections in sampled tiles. They are not validated
whole-slide estimates and TumorQuantAI does not multiply them by
`100 / percent_slide`. Keep fast and full in separate outputs and do not compare
raw counts across different sampled areas as though their denominators match.

Resume reuses a cached task only when relevant inputs and settings still match.
Changing sampling, seed, source MPP, model identity, or a source fingerprint
should invalidate affected work.

**Next:** understand [counts versus fractions](counts-fractions.md).
