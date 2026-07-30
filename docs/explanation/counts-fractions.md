# Counts versus fractions

`celltype_counts_by_sample.csv` contains raw detected-cell counts in the tissue
tiles actually processed. Cell types are rows; completed samples are columns.

`celltype_fractions_by_sample.csv` divides each class count by all detected
cells in that completed sample. A nonempty column sums to one. A verified
zero-detection completed sample has zero fractions and sums to zero.

Fractions can make composition easier to compare across samples with different
detected-cell totals, but they do not correct:

- biased or unrepresentative tile sampling;
- different tissue regions or preparation quality;
- incorrect MPP;
- model error;
- batch effects; or
- failed/missing samples.

For sampled runs, counts are not whole-slide estimates. Do not multiply them by
the inverse sampling percentage. Before analysis, check that sampling
percentage and seed are consistent and inspect
`sample_aggregation_audit.csv`.

`celltype_counts_long.csv` is a tidy representation with `slide_id`,
`sample_id`, `class_id`, `cell_type`, and `count` for included results.

**Next:** learn why a [failed sample is not a biological zero](failed-vs-zero.md).
