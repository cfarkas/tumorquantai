from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).parents[1] / "bin" / "clinical_histoplus_ml.py"
SPEC = importlib.util.spec_from_file_location("clinical_histoplus_ml_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class ClinicalHistoplusMlTests(unittest.TestCase):
    def test_safe_slide_id_normalization_preserves_specimen_tokens(self) -> None:
        self.assertEqual(module.normalize_slide_id(" STUDY_123-1C2_HE_1.tif "), "STUDY-123-1C2")
        self.assertNotEqual(
            module.normalize_slide_id("STUDY-123-1C2_HE_1"),
            module.normalize_slide_id("STUDY-123-2C2_HE_1"),
        )

    def test_end_to_end_synthetic_nested_cv_output_contract(self) -> None:
        rng = np.random.default_rng(7)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            n_completed = 30
            n_failed = 2
            clinical_ids = [f"CASE-{index:03d}" for index in range(n_completed + n_failed)]
            outcome = np.array([0, 1] * ((n_completed + n_failed) // 2))
            clinical = pd.DataFrame(
                {
                    "sample": clinical_ids,
                    "status": np.where(outcome == 1, "Dead", "Alive"),
                    "age": 50 + 8 * outcome + rng.normal(0, 5, len(outcome)),
                    "sex": np.where(np.arange(len(outcome)) % 3 == 0, "F", "M"),
                }
            )
            clinical.loc[3, "age"] = np.nan
            clinical_path = root / "clinical.xlsx"
            clinical.to_excel(clinical_path, index=False, sheet_name="cohort")

            sample_columns = [f"CASE_{index:03d}_HE_1" for index in range(n_completed)]
            count_rows = []
            fraction_rows = []
            for class_id, cell_type in [(1, "Cancer cell"), (2, "Lymphocytes"), (3, "Fibroblasts")]:
                counts = rng.integers(1, 25, n_completed) + outcome[:n_completed] * class_id
                count_rows.append([class_id, cell_type, *counts])
            counts_table = pd.DataFrame(
                count_rows, columns=["class_id", "cell_type", *sample_columns]
            )
            totals = counts_table.loc[:, sample_columns].sum(axis=0)
            for _, row in counts_table.iterrows():
                fraction_rows.append(
                    [row["class_id"], row["cell_type"], *[row[sample] / totals[sample] for sample in sample_columns]]
                )
            fractions_table = pd.DataFrame(
                fraction_rows, columns=["class_id", "cell_type", *sample_columns]
            )
            counts_path = root / "counts.csv"
            fractions_path = root / "fractions.csv"
            counts_table.to_csv(counts_path, index=False)
            fractions_table.to_csv(fractions_path, index=False)

            audit = pd.DataFrame(
                {
                    "slide_id": [*sample_columns, "CASE_030_HE_1", "CASE_031_HE_1"],
                    "included": [True] * n_completed + [False] * n_failed,
                }
            )
            audit_path = root / "audit.csv"
            audit.to_csv(audit_path, index=False)
            output = root / "results"
            returncode = module.main(
                [
                    "--clinical-xlsx", str(clinical_path),
                    "--clinical-sheet", "cohort",
                    "--sample-id-column", "sample",
                    "--outcome-column", "status",
                    "--positive-label", "Dead",
                    "--negative-label", "Alive",
                    "--clinical-feature", "age",
                    "--clinical-feature", "sex",
                    "--numeric-clinical-feature", "age",
                    "--categorical-clinical-feature", "sex",
                    "--stratification-feature", "age",
                    "--stratification-feature", "sex",
                    "--counts-matrix", str(counts_path),
                    "--fractions-matrix", str(fractions_path),
                    "--aggregation-audit", str(audit_path),
                    "--output-dir", str(output),
                    "--feature-sets", "clinical,histoplus_fractions,combined_fractions",
                    "--models", "dummy,elastic_net",
                    "--outer-splits", "3",
                    "--outer-repeats", "1",
                    "--inner-splits", "2",
                    "--bootstrap-repeats", "20",
                    "--permutation-repeats", "0",
                    "--seed", "7",
                    "--n-jobs", "1",
                ]
            )
            self.assertEqual(returncode, 0)
            required = {
                "analysis_cohort.csv",
                "linked_clinical_histoplus_full.csv",
                "linked_clinical_histoplus_all.csv",
                "linkage_audit.csv",
                "univariate_stratification.csv",
                "oof_predictions.csv",
                "summary_metrics.csv",
                "run_manifest.json",
            }
            self.assertTrue(required.issubset({path.name for path in output.iterdir()}))
            predictions = pd.read_csv(output / "oof_predictions.csv")
            self.assertEqual(len(predictions), n_completed * 3 * 2)
            self.assertTrue(predictions["y_probability"].between(0, 1).all())
            self.assertTrue(
                predictions.groupby(["analysis_id", "feature_set", "model"]).size().eq(1).all()
            )
            linkage = pd.read_csv(output / "linkage_audit.csv")
            self.assertEqual(int(linkage["analysis_included"].sum()), n_completed)
            self.assertEqual(int((~linkage["analysis_included"]).sum()), n_failed)
            all_roster = pd.read_csv(output / "linked_clinical_histoplus_all.csv")
            self.assertEqual(len(all_roster), n_completed + n_failed)
            self.assertEqual(
                int(all_roster["LINKAGE__analysis_included"].sum()), n_completed
            )
            failed_roster = all_roster.loc[
                ~all_roster["LINKAGE__analysis_included"].astype(bool)
            ]
            histoplus_columns = [
                column for column in all_roster if column.startswith("HISTO_")
            ]
            self.assertTrue(failed_roster[histoplus_columns].isna().all().all())
            manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["cohort"]["n_analysis_samples"], n_completed)
            self.assertTrue((output / "figures" / "oof_calibration.png").is_file())

            histoplus_only_output = root / "histoplus_only_results"
            histoplus_only_returncode = module.main(
                [
                    "--clinical-xlsx", str(clinical_path),
                    "--clinical-sheet", "cohort",
                    "--sample-id-column", "sample",
                    "--outcome-column", "status",
                    "--positive-label", "Dead",
                    "--negative-label", "Alive",
                    "--counts-matrix", str(counts_path),
                    "--fractions-matrix", str(fractions_path),
                    "--aggregation-audit", str(audit_path),
                    "--output-dir", str(histoplus_only_output),
                    "--feature-sets", "histoplus_log_counts",
                    "--models", "dummy",
                    "--outer-splits", "3",
                    "--outer-repeats", "1",
                    "--inner-splits", "2",
                    "--bootstrap-repeats", "5",
                    "--permutation-repeats", "0",
                    "--seed", "7",
                    "--n-jobs", "1",
                ]
            )
            self.assertEqual(histoplus_only_returncode, 0)
            empty_incremental = pd.read_csv(histoplus_only_output / "incremental_value.csv")
            self.assertTrue(empty_incremental.empty)
            self.assertEqual(
                empty_incremental.columns.tolist(), list(module.INCREMENTAL_VALUE_COLUMNS)
            )
            report = (histoplus_only_output / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("not available", report)
            self.assertFalse(
                (histoplus_only_output / "figures" / "oof_calibration.png").exists()
            )



    def test_sample_map_audit_links_matrix_sample_id_and_validates_pools(self) -> None:
        clinical = pd.DataFrame(
            {"sample": ["PATIENT-001"], "status": ["Dead"], "age": [60]}
        )
        one_to_one_audit = pd.DataFrame(
            {
                "slide_id": ["SLIDE-A"],
                "sample_id": ["PATIENT_001"],
                "included": [True],
            }
        )
        linkage, eligible, outcome_counts = module.build_linkage(
            clinical,
            "sample",
            "status",
            "Dead",
            "Alive",
            ["PATIENT_001"],
            one_to_one_audit,
        )
        self.assertEqual(eligible.index.tolist(), ["PATIENT_001"])
        self.assertTrue(bool(linkage.loc[0, "analysis_included"]))
        self.assertEqual(outcome_counts, {"negative": 0, "positive": 1})

        pooled_audit = pd.DataFrame(
            {
                "slide_id": ["SLIDE-A", "SLIDE-B"],
                "sample_id": ["PATIENT_001", "PATIENT_001"],
                "included": [True, True],
            }
        )
        pooled_linkage, pooled_eligible, _ = module.build_linkage(
            clinical,
            "sample",
            "status",
            "Dead",
            "Alive",
            ["PATIENT_001"],
            pooled_audit,
        )
        self.assertEqual(pooled_eligible.index.tolist(), ["PATIENT_001"])
        self.assertEqual(int(pooled_linkage.loc[0, "aggregation_slide_count"]), 2)
        self.assertTrue(bool(pooled_linkage.loc[0, "pooled_slides"]))

        partial_pool = pooled_audit.copy()
        partial_pool["included"] = [True, False]
        with self.assertRaisesRegex(module.AnalysisError, "both included and excluded slides"):
            module.build_linkage(
                clinical,
                "sample",
                "status",
                "Dead",
                "Alive",
                ["PATIENT_001"],
                partial_pool,
            )

    def test_grouped_cv_respects_groups_and_validates_independent_support(self) -> None:
        y = np.asarray([0, 0, 0, 0, 1, 1, 1, 1])
        groups = np.asarray(["n1", "n1", "n2", "n2", "p1", "p1", "p2", "p2"])
        splits = module.build_outer_splits(y, groups, 2, 2, 11, True)
        self.assertEqual(len(splits), 4)
        for _, _, train, test in splits:
            self.assertFalse(set(groups[train]).intersection(groups[test]))
            self.assertEqual(set(y[train]), {0, 1})
            self.assertEqual(set(y[test]), {0, 1})

        with self.assertRaisesRegex(module.AnalysisError, "conflicting outcome labels"):
            module.build_outer_splits(
                np.asarray([0, 1, 0, 1]),
                np.asarray(["mixed", "mixed", "negative", "positive"]),
                2,
                1,
                7,
                True,
            )
        with self.assertRaisesRegex(module.AnalysisError, "independent patient-group counts"):
            module.build_inner_splits(
                np.asarray([0, 0, 0, 1, 1, 1]),
                np.asarray(["n1", "n1", "n1", "p1", "p2", "p2"]),
                2,
                7,
                grouped=True,
                context="Test inner CV",
            )

    def test_group_bootstrap_samples_complete_clusters_and_reports_unit(self) -> None:
        y = np.asarray([0, 0, 0, 0, 1, 1, 1, 1])
        group_values = np.asarray(["n1", "n1", "n2", "n2", "p1", "p1", "p2", "p2"])
        rng = np.random.default_rng(19)
        for _ in range(20):
            sampled = module.stratified_bootstrap_indices(y, group_values, rng)
            multiplicities = np.bincount(sampled, minlength=len(y))
            for left, right in ((0, 1), (2, 3), (4, 5), (6, 7)):
                self.assertEqual(multiplicities[left], multiplicities[right])

        analysis_ids = [f"S{index}" for index in range(len(y))]
        predictions = pd.DataFrame(
            {
                "analysis_id": analysis_ids,
                "feature_set": "histoplus_fractions",
                "model": "dummy",
                "y_true": y,
                "y_probability": np.where(y == 1, 0.6, 0.4),
            }
        )
        metrics = module.calculate_metrics(y, predictions["y_probability"].to_numpy())
        fold_metrics = pd.DataFrame(
            [{"feature_set": "histoplus_fractions", "model": "dummy", **metrics}]
        )
        group_series = pd.Series(group_values, index=analysis_ids)
        summary, _ = module.bootstrap_metric_intervals(
            predictions, fold_metrics, 10, 7, groups=group_series
        )
        self.assertEqual(set(summary["bootstrap_unit"]), {"patient_group"})
        self.assertEqual(set(summary["n_independent_groups"]), {4})

        clinical_predictions = predictions.copy()
        clinical_predictions["feature_set"] = "clinical"
        clinical_predictions["y_probability"] = np.where(y == 1, 0.55, 0.45)
        paired_input = pd.concat([predictions, clinical_predictions], ignore_index=True)
        paired = module.paired_incremental_value(
            paired_input, 10, 7, groups=group_series
        )
        self.assertFalse(paired.empty)
        conflicting_groups = pd.Series("mixed", index=analysis_ids)
        with self.assertRaisesRegex(module.AnalysisError, "conflicting outcome labels"):
            module.paired_incremental_value(
                paired_input, 2, 7, groups=conflicting_groups
            )

    def test_single_feature_set_empty_incremental_schema_and_report(self) -> None:
        averaged = pd.DataFrame(
            {
                "analysis_id": ["n1", "n2", "p1", "p2"],
                "feature_set": "histoplus_fractions",
                "model": "dummy",
                "y_true": [0, 0, 1, 1],
                "y_probability": [0.3, 0.4, 0.6, 0.7],
            }
        )
        incremental = module.paired_incremental_value(averaged, 5, 7)
        self.assertTrue(incremental.empty)
        self.assertEqual(incremental.columns.tolist(), list(module.INCREMENTAL_VALUE_COLUMNS))

        point = module.calculate_metrics(
            averaged["y_true"].to_numpy(), averaged["y_probability"].to_numpy()
        )
        summary = pd.DataFrame(
            [
                {
                    "feature_set": "histoplus_fractions",
                    "model": "dummy",
                    "metric": metric,
                    "point_estimate": point[metric],
                    "bootstrap_ci_low": point[metric],
                    "bootstrap_ci_high": point[metric],
                }
                for metric in module.METRIC_NAMES
            ]
        )
        stratification = pd.DataFrame(columns=["fdr_bh_q_value"])
        args = module.argparse.Namespace(
            positive_label="Dead",
            negative_label="Alive",
            outer_splits=2,
            outer_repeats=1,
            inner_splits=2,
        )
        report = module.render_analysis_report(
            summary,
            incremental,
            stratification,
            {
                "n_analysis_samples": 4,
                "n_positive": 2,
                "n_negative": 2,
                "n_linkage_excluded": 0,
            },
            args,
        )
        self.assertIn("not available", report)
        self.assertIn("Clinical | not run", report)

    def test_empty_histoplus_stratification_and_composition_are_valid(self) -> None:
        ids = ["n1", "p1"]
        empty = pd.DataFrame(index=ids)
        y = pd.Series([0, 1], index=ids)
        result = module.univariate_stratification(empty, [], empty, empty, y)
        self.assertTrue(result.empty)
        self.assertIn("fdr_bh_q_value", result.columns)
        with tempfile.TemporaryDirectory() as temporary:
            module.plot_histoplus_composition(
                empty,
                pd.DataFrame(columns=["class_id", "cell_type"]),
                y,
                Path(temporary),
            )
            self.assertFalse((Path(temporary) / "figures").exists())

    def test_explicit_clinical_types_are_required_and_exclusive(self) -> None:
        with self.assertRaisesRegex(module.AnalysisError, "requires exactly one explicit type"):
            module.clinical_feature_type_map(["age"], [], [])
        with self.assertRaisesRegex(module.AnalysisError, "both numeric and categorical"):
            module.clinical_feature_type_map(["age"], ["age"], ["age"])
        self.assertEqual(
            module.clinical_feature_type_map(["age", "sex"], ["age"], ["sex"]),
            {"age": "numeric", "sex": "categorical"},
        )
        with self.assertRaisesRegex(module.AnalysisError, "declared numeric"):
            module.prepare_clinical_features(
                pd.DataFrame({"age": [50, "unknown"]}),
                ["age"],
                {"age": "numeric"},
                20,
            )

    def test_repeated_patient_rows_require_upstream_pooling(self) -> None:
        with self.assertRaisesRegex(module.AnalysisError, "exactly one matrix sample per patient"):
            module.prepare_patient_groups(pd.Series(["P1", "P1", "P2"]))

    def test_grouped_summary_equally_weights_unequal_patient_clusters(self) -> None:
        y = np.asarray([0, 0, 0, 0, 1, 1, 1, 1])
        probabilities = np.asarray([0.9, 0.9, 0.9, 0.1, 0.9, 0.1, 0.1, 0.1])
        analysis_ids = [f"U{index}" for index in range(len(y))]
        group_values = ["n_big", "n_big", "n_big", "n_small", "p_big", "p_small", "p_small", "p_small"]
        predictions = pd.DataFrame(
            {
                "analysis_id": analysis_ids,
                "feature_set": "histoplus_fractions",
                "model": "dummy",
                "y_true": y,
                "y_probability": probabilities,
            }
        )
        specimen_metrics = module.calculate_metrics(y, probabilities)
        fold_metrics = pd.DataFrame(
            [{"feature_set": "histoplus_fractions", "model": "dummy", **specimen_metrics}]
        )
        groups = pd.Series(group_values, index=analysis_ids)
        summary, averaged = module.bootstrap_metric_intervals(
            predictions, fold_metrics, 10, 5, groups=groups
        )
        brier = summary.loc[summary["metric"] == "brier"].iloc[0]
        self.assertAlmostEqual(float(brier["point_estimate"]), 0.41, places=12)
        self.assertEqual(int(brier["n_analysis_samples"]), 8)
        self.assertEqual(int(brier["n_evaluation_units"]), 4)
        self.assertEqual(brier["evaluation_unit"], "patient_group")
        self.assertEqual(len(averaged), 8)

    def test_grouped_specimen_stratification_suppresses_inference(self) -> None:
        ids = ["S1", "S2", "S3", "S4"]
        clinical = pd.DataFrame({"age": [40, 50, 60, 70]}, index=ids)
        empty = pd.DataFrame(index=ids)
        y = pd.Series([0, 0, 1, 1], index=ids)
        result = module.univariate_stratification(
            clinical, ["age"], empty, empty, y, inferential=False
        )
        self.assertTrue(result["p_value"].isna().all())
        self.assertTrue(result["fdr_bh_q_value"].isna().all())
        self.assertEqual(
            set(result["test"]), {"not_tested_grouped_specimen_descriptive"}
        )
        probabilities = np.asarray([0.2, 0.3, 0.7, 0.8])
        point = module.calculate_metrics(y.to_numpy(), probabilities)
        summary = pd.DataFrame(
            [
                {
                    "feature_set": "histoplus_fractions",
                    "model": "dummy",
                    "metric": metric,
                    "point_estimate": point[metric],
                    "bootstrap_ci_low": point[metric],
                    "bootstrap_ci_high": point[metric],
                }
                for metric in module.METRIC_NAMES
            ]
        )
        report = module.render_analysis_report(
            summary,
            pd.DataFrame(columns=module.INCREMENTAL_VALUE_COLUMNS),
            result,
            {
                "n_analysis_samples": 4,
                "n_positive": 2,
                "n_negative": 2,
                "n_linkage_excluded": 0,
                "evaluation_unit": "patient_group",
                "n_evaluation_units": 2,
                "n_positive_evaluation_units": 1,
                "n_negative_evaluation_units": 1,
            },
            module.argparse.Namespace(
                positive_label="Dead",
                negative_label="Alive",
                outer_splits=2,
                outer_repeats=1,
                inner_splits=2,
            ),
        )
        self.assertIn("Inferential p-values and FDR q-values were suppressed", report)

    def test_fraction_matrix_must_match_count_normalization(self) -> None:
        counts = pd.DataFrame([[2.0, 1.0], [2.0, 3.0]], index=["A", "B"])
        fractions = pd.DataFrame([[2 / 3, 1 / 3], [0.4, 0.6]], index=["A", "B"])
        metadata = pd.DataFrame(
            {"class_id": [1, 2], "cell_type": ["Cancer", "Lymphocyte"]}
        )
        module.validate_histoplus_inputs(counts, fractions, metadata, metadata.copy())
        mismatched = fractions.copy()
        mismatched.iloc[0] = [0.6, 0.4]
        with self.assertRaisesRegex(module.AnalysisError, "same aggregation run"):
            module.validate_histoplus_inputs(
                counts, mismatched, metadata, metadata.copy()
            )

if __name__ == "__main__":
    unittest.main()
