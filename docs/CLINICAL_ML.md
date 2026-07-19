# Exploratory clinical and HistoPLUS machine learning

This guide describes a privacy-preserving way to compare clinical variables,
HistoPLUS cell-type measurements, and their combination with
`bin/clinical_histoplus_ml.py`. The runner is exploratory. It is not a clinical
decision-support system, a medical device, evidence of causality, or a
substitute for independent validation.

Model validity depends on the endpoint, cohort definition, prediction time,
feature availability, linkage quality, and evaluation design. Review those
choices with the study's clinical, statistical, and data-governance teams
before running the analysis.

## Required inputs and options

Keep identifiable source data outside this repository. Use a minimum,
de-identified analysis workbook and controlled output storage.

The runner requires:

1. A clinical Excel workbook selected with `--clinical-xlsx`. Use the optional
   `--clinical-sheet` to select a worksheet explicitly; otherwise the first
   worksheet is used. It must contain one row per linked matrix sample. Related slides must first be
   pooled to one matrix sample per patient before using `--patient-id-column`.
2. A reviewed slide/sample key named by `--sample-id-column`. It is linked to
   the sample columns in the HistoPLUS matrices.
3. An optional validated patient or case key named by `--patient-id-column`.
   Each value must occur once in the linked modeling table; repeated values fail
   with upstream `--sample-map` pooling guidance.
4. A binary label named by `--outcome-column`, with its two accepted values
   declared using `--positive-label` and `--negative-label`.
5. Prespecified predictors, each supplied with a separate
   `--clinical-feature`, when `clinical` or `combined_fractions` is selected.
   Every modeled column must also be declared exactly once with repeated
   `--numeric-clinical-feature` or `--categorical-clinical-feature`; the runner
   never infers modeled feature types from the full cohort.
   HistoPLUS-only feature-set subsets do not require clinical predictors. Do not
   select columns after inspecting held-out performance.
   Descriptive-only variables may be supplied separately with repeated
   `--stratification-feature`; they are never added to the model unless also
   named by `--clinical-feature`.
6. Both matrices produced by `bin/aggregate_histoplus_celltypes.py`:

   - `celltype_counts_by_sample.csv`, supplied with `--counts-matrix`;
   - `celltype_fractions_by_sample.csv`, supplied with `--fractions-matrix`.

7. `sample_aggregation_audit.csv`, supplied with `--aggregation-audit`. This
   distinguishes valid completed samples from failed or missing inference.
8. A controlled `--output-dir`.

Evaluation is controlled by `--outer-splits`, `--outer-repeats`,
`--inner-splits`, `--bootstrap-repeats`, `--permutation-repeats`,
`--seed`, and `--n-jobs`. Optional `--feature-sets` and `--models`
arguments restrict a comparison only when that restriction was prespecified.
`--clr-pseudocount` controls the declared CLR pseudocount, while
`--min-category-frequency` and `--max-categorical-levels` constrain
clinical encoding.
Split and bootstrap counts must be supportable by the number of independent
analysis units in each class. With `--patient-id-column`, feasibility is checked
using patient-group counts rather than slide counts; larger numbers do not
compensate for a small cohort.

Supply `--patient-id-column` for a validated patient or case key. The modeling
table must contain exactly one row per patient group. Pool related slides
upstream with `bin/aggregate_histoplus_celltypes.py --sample-map`; repeated
patient rows fail closed so tuning, training, and evaluation use one patient once.
The runner then uses stratified group-aware outer and inner folds. Without it,
every linked sample is treated as independent. Omit it only
when that assumption has been verified; row-level random splitting of related
samples is not acceptable.

## Privacy-safe linkage

Prefer exact linkage using a crosswalk reviewed by the data custodian. Keep
that crosswalk in restricted storage even when its IDs are pseudonymous.

If formatting normalization is necessary, make it conservative and
deterministic:

1. Apply Unicode NFKC normalization, trim whitespace, and use a consistent
   case.
2. Remove only documented terminal file extensions and technical acquisition
   suffixes.
3. Collapse runs of whitespace, underscore, and hyphen to one separator.
4. Preserve accession prefixes, block/cassette tokens, and all other core ID
   components.
5. Reject empty keys, duplicate keys, and ambiguous relationships.

Do not use fuzzy matching, partial accessions, row order, names, birth dates,
or other identifying fields. Do not remove prefixes merely to improve the
match rate. A shareable linkage report should contain counts only: total,
uniquely matched, unmatched on each side, ambiguous, and duplicated.

A linkage operation should fail closed:

```python
linked = matrix_samples.merge(
    clinical_rows,
    on="normalized_sample_id",
    how="left",
    validate="one_to_one",
    indicator=True,
)
if not linked["_merge"].eq("both").all():
    raise ValueError("Incomplete linkage; inspect the private linkage audit")
```

Clinical rows without completed HistoPLUS output may remain in a linkage audit,
but they must not become artificial all-zero matrix columns. Conversely,
HistoPLUS samples without an eligible clinical label must not enter supervised
evaluation.

When `sample_aggregation_audit.csv` contains `sample_id`, the runner links the
clinical key and matrix columns through that field; otherwise it retains exact
slide-ID linkage. One-to-one mappings and fully completed pools are supported. A
pooled `sample_id` containing both included and excluded source slides fails
closed because the resulting partial biological sample is not comparable. The
clinical workbook must contain exactly one row for each pooled matrix sample.

## Four paired feature-set comparisons

The runner evaluates four named feature sets:

- `clinical`: only the repeated `--clinical-feature` columns;
- `histoplus_fractions`: centered-log-ratio (CLR) transformed fractions
  plus an explicit zero-detection indicator;
- `histoplus_log_counts`: `log1p`-transformed counts plus the
  zero-detection indicator;
- `combined_fractions`: clinical predictors plus the CLR fraction
  features and zero-detection indicator.

When all four feature sets are selected, their comparisons must use the same
eligible rows, labels, outer folds, inner folds, preprocessing rules, metrics, and tuning budget. This permits
paired comparison of out-of-fold predictions. Report every feature set and the
paired performance differences with uncertainty; do not present only the
winner.
If a prespecified subset omits a candidate/reference pair,
`incremental_value.csv` remains a valid header-only table and `REPORT.md` marks
the comparison as not available.

For sampled-slide runs, raw counts are detections in sampled tissue tiles, not
full-slide abundance estimates. Log transformation reduces scale but does not
remove differences in sampled area or tissue content. Fractions are generally
safer for composition comparisons, but they remain compositional and can be
affected by tissue selection, sampling quality, and zero detections. Document
the sampling percentage and seed, and do not mix incompatible runs.

Missing inference is not biological zero. Use the aggregation audit to exclude
incomplete slides. Fit all clinical missing-data handling inside the training
portion of each fold.

## Binary vital status, fixed horizons, and censoring

The runner is a binary classifier; it is not a survival-analysis program. A
single current `alive`/`dead` value measured after unequal follow-up is not a
well-defined fixed-horizon endpoint. Treating every currently alive person as
negative ignores censoring and can make the model learn follow-up duration or
calendar time.

For a binary endpoint at a prespecified horizon `T`:

- positive: the event occurred on or before `T`;
- negative: event-free status is confirmed through at least `T`;
- unknown: no event is recorded, but follow-up ends before `T`.

Exclude the unknown group from the fixed-horizon classifier. Never relabel it
as event-free. Choose `T` from the clinical question before model evaluation,
and report exclusions caused by insufficient follow-up.

If valid event and censoring times are available, use a survival method and
survival-appropriate metrics such as a censoring-aware concordance index,
time-dependent AUC, integrated Brier score, and calibration at prespecified
times. Ordinary AUROC on last-known vital status is not a substitute. If only
binary vital status is available, label the result explicitly as exploratory
and do not describe it as a survival or fixed-horizon prognosis model.

## Leakage prevention

Define the intended prediction time first. A feature is eligible only if it
would have been known then. Post-outcome variables, future treatment,
follow-up duration, and variables measured after the prediction time are
leakage unless the estimand explicitly starts later.

Fit every data-dependent operation inside the relevant training fold:

- missing-value imputation;
- categorical encoding and scaling;
- low-variance filtering and feature selection;
- count transforms, PCA, or other dimension reduction;
- batch correction;
- class weighting or resampling;
- hyperparameter and decision-threshold selection;
- probability calibration.

Never run these once on the complete cohort. Never use slide IDs, patient IDs,
folder names, free-text notes, acquisition dates, linkage keys, or the outcome
itself as predictors. Keep duplicate or related specimens in the same fold.
When sites, scanners, or calendar periods are important sources of shift,
reserve a site- or time-separated validation cohort when possible.

## Nested cross-validation

Nested cross-validation separates model selection from performance estimation:

1. Outer stratified splits create untouched test folds. When
   `--patient-id-column` is supplied, these are stratified group folds.
2. For each outer training set, inner splits perform all preprocessing,
   feature handling, and hyperparameter selection, using the same patient
   grouping rule.
3. The selected pipeline is refit on the full outer training set.
4. It predicts that outer test set exactly once.
5. Outer-fold predictions are combined to give out-of-fold predictions for all
   eligible independent samples.

`--outer-repeats` measures sensitivity to repeated partitions; repeats do not
create new patients or increase the effective sample size. If a sufficiently
large external or temporal test set exists, keep it untouched until the full
pipeline, endpoint, horizon, and threshold are locked.

For binary outcomes, report prevalence, AUROC, AUPRC, balanced accuracy,
sensitivity, specificity, Brier score, and calibration. Any classification
threshold must be chosen without using the outer test fold. Bootstrap samples
and confidence intervals respect the independent analysis unit: when a patient
grouping key is supplied, whole groups are sampled within outcome strata for
both single-model intervals and paired incremental-value intervals. With a
small cohort, prefer parsimonious models and modest tuning grids.
Repeated-run OOF probabilities are first averaged per linked sample and, in
grouped mode, per patient; point metrics, deltas, curves, and bootstrap intervals
therefore weight every patient equally. Raw `oof_predictions.csv` remains
specimen-level for private auditing.

## Outputs and disclosure boundaries

The runner writes the following artifacts directly under `--output-dir`:

```text
clinical_ml_results/
├── analysis_cohort.csv
├── linked_clinical_histoplus_full.csv
├── linked_clinical_histoplus_all.csv
├── linkage_audit.csv
├── feature_manifest.csv
├── clinical_missingness.csv
├── univariate_stratification.csv
├── oof_predictions.csv
├── oof_predictions_averaged.csv
├── fold_metrics.csv
├── summary_metrics.csv
├── incremental_value.csv
├── model_selection.csv
├── heldout_permutation_importance.csv
├── fold_assignments.csv
├── run_manifest.json
├── REPORT.md
└── figures/
    ├── cohort_flow.{png,pdf}
    ├── histoplus_fraction_stratification.{png,pdf}
    ├── histoplus_clr_pca.{png,pdf}
    ├── model_performance.{png,pdf}
    ├── oof_roc_pr_curves.{png,pdf}
    ├── oof_calibration.{png,pdf}
    └── heldout_permutation_importance.{png,pdf}
```

`run_manifest.json` records input checksums, dependency versions, endpoint
mapping, feature sets, models, cohort counts, CV settings, and limitations.
`REPORT.md` contains aggregate results and interpretation guardrails; it is
not a clinical report.
`linked_clinical_histoplus_all.csv` preserves every workbook row and adds
linkage flags plus HistoPLUS columns; failed or unmatched rows retain NA rather
than artificial zeros. `analysis_cohort.csv` remains the eligible modeling set.
Brier score is always reported as an aggregate calibration metric. The OOF
reliability figure is written only when a non-dummy model is selected. The
composition figure requires at least one discovered cell type, PCA requires at
least two, and permutation importance requires a non-dummy model with positive
`--permutation-repeats`. These conditional files may therefore be absent.
`univariate_stratification.csv` is descriptive and must never be used to
select features after seeing the full cohort. If repeated grouped specimens
are encountered in lower-level use, inferential p-values and FDR q-values are
suppressed rather than treating specimens as independent.

Treat the entire output directory as private. In particular,
`analysis_cohort.csv`, `linked_clinical_histoplus_full.csv`,
`linked_clinical_histoplus_all.csv`, `linkage_audit.csv`, both
out-of-fold prediction files,
and `fold_assignments.csv` contain row-level sample information. Only reviewed,
aggregate linkage and performance summaries should leave controlled storage.
Do not commit the workbook or generated analysis outputs to Git.

## Local command template

The feature names and labels below are generic placeholders; replace them with
the reviewed columns and values from the de-identified worksheet:

```bash
python bin/clinical_histoplus_ml.py \
  --clinical-xlsx /secure/inputs/clinical_deidentified.xlsx \
  --clinical-sheet analysis \
  --sample-id-column sample_id \
  --patient-id-column patient_group_id \
  --outcome-column outcome_at_horizon \
  --positive-label event \
  --negative-label event_free \
  --clinical-feature age_at_index \
  --clinical-feature stage_at_index \
  --numeric-clinical-feature age_at_index \
  --categorical-clinical-feature stage_at_index \
  --stratification-feature treatment_group \
  --counts-matrix /secure/inputs/celltype_counts_by_sample.csv \
  --fractions-matrix /secure/inputs/celltype_fractions_by_sample.csv \
  --aggregation-audit /secure/inputs/sample_aggregation_audit.csv \
  --feature-sets clinical,histoplus_fractions,histoplus_log_counts,combined_fractions \
  --models dummy,elastic_net,random_forest \
  --output-dir /secure/outputs/clinical_ml_results \
  --outer-splits 5 \
  --outer-repeats 5 \
  --inner-splits 4 \
  --bootstrap-repeats 2000 \
  --permutation-repeats 5 \
  --seed 20260715 \
  --n-jobs 4
```

Treat the split and repeat counts as examples, not defaults. Reduce them when
minority-class counts cannot support every fold.

## Docker command template

The default published WSI runtime digests predate this optional clinical tool.
Build the current checkout before using the in-container path below; for a
shared release, push that image and replace the local tag with its immutable
registry digest. Mount inputs read-only and keep outputs on a controlled mount:

```bash
docker build --build-arg FLAVOR=cpu -t tumorquantai:0.4.0-cpu .
IMAGE=tumorquantai:0.4.0-cpu

docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -v /secure/inputs:/inputs:ro \
  -v /secure/outputs:/outputs \
  "$IMAGE" \
  python /opt/lazyslide/bin/clinical_histoplus_ml.py \
    --clinical-xlsx /inputs/clinical_deidentified.xlsx \
    --clinical-sheet analysis \
    --sample-id-column sample_id \
    --patient-id-column patient_group_id \
    --outcome-column outcome_at_horizon \
    --positive-label event \
    --negative-label event_free \
    --clinical-feature age_at_index \
    --clinical-feature stage_at_index \
    --numeric-clinical-feature age_at_index \
    --categorical-clinical-feature stage_at_index \
    --stratification-feature treatment_group \
    --counts-matrix /inputs/celltype_counts_by_sample.csv \
    --fractions-matrix /inputs/celltype_fractions_by_sample.csv \
    --aggregation-audit /inputs/sample_aggregation_audit.csv \
    --feature-sets clinical,histoplus_fractions,histoplus_log_counts,combined_fractions \
    --models dummy,elastic_net,random_forest \
    --output-dir /outputs/clinical_ml_results \
    --outer-splits 5 \
    --outer-repeats 5 \
    --inner-splits 4 \
    --bootstrap-repeats 2000 \
    --permutation-repeats 5 \
    --seed 20260715 \
    --n-jobs 4
```

Before interpreting any run, verify the private linkage audit, cohort flow,
per-fold class counts, out-of-fold coverage, repeated-sample separation, and
calibration. Performance estimates without those checks are incomplete.
