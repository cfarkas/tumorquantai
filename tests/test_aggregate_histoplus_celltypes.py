from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).parents[1] / "bin" / "aggregate_histoplus_celltypes.py"
SPEC = importlib.util.spec_from_file_location("aggregate_histoplus_celltypes", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
aggregate_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(aggregate_module)


def write_slide(
    root: Path,
    slide_id: str,
    rows: list[tuple[int, str, int]],
    *,
    percent_slide: float = 10.0,
    seed: int | None = 123,
) -> None:
    cell_dir = root / slide_id / "cell_types"
    summary_dir = root / slide_id / "summary"
    cell_dir.mkdir(parents=True)
    summary_dir.mkdir(parents=True)
    pd.DataFrame(rows, columns=["class_id", "class_name", "count"]).to_csv(
        cell_dir / "class_counts.csv", index=False
    )
    summary = {
        "slide_id": slide_id,
        "n_cells": sum(row[2] for row in rows),
        "tile_sampling": {
            "percent_slide": percent_slide,
            "random_seed": seed,
            "n_tiles_total": 100,
            "n_tiles_sampled": 10,
        },
    }
    (summary_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


def write_manifest(root: Path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows).to_csv(root / "fast_batch_manifest.csv", index=False)


class AggregateHistoplusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.temp_path = Path(self.temporary_directory.name)

    def run_main(self, arguments: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            returncode = aggregate_module.main(arguments)
        return returncode, stdout.getvalue(), stderr.getvalue()

    def test_builds_feature_by_sample_matrices_and_audits_failure(self) -> None:
        root = self.temp_path / "results"
        root.mkdir()
        write_slide(root, "sample_2", [(1, "Cancer cell", 5), (3, "Fibroblasts", 5)])
        write_slide(root, "sample_10", [(1, "Cancer cell", 10), (2, "Lymphocytes", 2)])
        write_manifest(
            root,
            [
                {"slide_id": "sample_2", "completed": True, "returncode": 0},
                {"slide_id": "sample_10", "completed": True, "returncode": 0},
                {"slide_id": "failed_1", "completed": False, "returncode": 1},
            ],
        )

        returncode, _, stderr = self.run_main(
            ["--input-root", str(root), "--expected-percent-slide", "10"]
        )
        self.assertEqual(returncode, 0, stderr)

        output = root / "aggregated_celltypes"
        counts = pd.read_csv(output / "celltype_counts_by_sample.csv")
        self.assertEqual(
            counts.columns.tolist(),
            ["class_id", "cell_type", "sample_2", "sample_10"],
        )
        self.assertEqual(
            counts[["class_id", "cell_type"]].values.tolist(),
            [[1, "Cancer cell"], [2, "Lymphocytes"], [3, "Fibroblasts"]],
        )
        self.assertEqual(
            counts[["sample_2", "sample_10"]].values.tolist(),
            [[5, 10], [0, 2], [5, 0]],
        )

        fractions = pd.read_csv(output / "celltype_fractions_by_sample.csv")
        self.assertEqual(
            fractions[["sample_2", "sample_10"]].sum().round(12).tolist(),
            [1.0, 1.0],
        )

        audit = pd.read_csv(output / "sample_aggregation_audit.csv")
        failed = audit.loc[audit["slide_id"] == "failed_1"].iloc[0]
        self.assertFalse(bool(failed["included"]))
        self.assertEqual(failed["status"], "excluded_incomplete")
        self.assertTrue(pd.isna(failed["total_cells"]))

    def test_sample_map_intentionally_pools_slides(self) -> None:
        root = self.temp_path / "results"
        root.mkdir()
        write_slide(root, "slide_a", [(1, "Cancer cell", 4), (2, "Lymphocytes", 1)])
        write_slide(root, "slide_b", [(1, "Cancer cell", 6), (3, "Fibroblasts", 2)])
        sample_map = self.temp_path / "sample_map.csv"
        pd.DataFrame(
            {
                "slide_id": ["slide_a", "slide_b"],
                "sample_id": ["patient_1", "patient_1"],
            }
        ).to_csv(sample_map, index=False)

        returncode, _, stderr = self.run_main(
            ["--input-root", str(root), "--sample-map", str(sample_map)]
        )
        self.assertEqual(returncode, 0, stderr)
        counts = pd.read_csv(root / "aggregated_celltypes" / "celltype_counts_by_sample.csv")
        self.assertEqual(counts.columns.tolist(), ["class_id", "cell_type", "patient_1"])
        self.assertEqual(counts["patient_1"].tolist(), [10, 1, 2])

    def test_rejects_duplicate_class_rows(self) -> None:
        root = self.temp_path / "results"
        root.mkdir()
        write_slide(
            root,
            "sample_1",
            [(1, "Cancer cell", 4), (1, "Cancer cell", 6)],
        )

        returncode, _, stderr = self.run_main(["--input-root", str(root)])
        self.assertEqual(returncode, 2)
        self.assertIn("duplicate class rows", stderr)

    def test_rejects_mixed_sampling_by_default(self) -> None:
        root = self.temp_path / "results"
        root.mkdir()
        write_slide(root, "sample_1", [(1, "Cancer cell", 4)], percent_slide=10)
        write_slide(root, "sample_2", [(1, "Cancer cell", 5)], percent_slide=100)

        returncode, _, stderr = self.run_main(["--input-root", str(root)])
        self.assertEqual(returncode, 2)
        self.assertIn("mixed tile sampling settings", stderr)

    def test_ignores_nested_noncanonical_count_tables(self) -> None:
        root = self.temp_path / "results"
        root.mkdir()
        write_slide(root, "sample_1", [(1, "Cancer cell", 4)])
        nested = root / "sample_1" / "qc_patches" / "patch_1" / "cell_types"
        nested.mkdir(parents=True)
        pd.DataFrame(
            [(99, "Not a slide-level class", 999)],
            columns=["class_id", "class_name", "count"],
        ).to_csv(nested / "class_counts.csv", index=False)

        returncode, _, stderr = self.run_main(["--input-root", str(root)])
        self.assertEqual(returncode, 0, stderr)
        counts = pd.read_csv(root / "aggregated_celltypes" / "celltype_counts_by_sample.csv")
        self.assertEqual(counts["class_id"].tolist(), [1])


    def test_all_failed_manifest_still_writes_empty_matrices_and_audit(self) -> None:
        root = self.temp_path / "results"
        root.mkdir()
        write_manifest(
            root,
            [{"slide_id": "failed_1", "completed": False, "returncode": 1}],
        )

        returncode, _, stderr = self.run_main(["--input-root", str(root)])
        self.assertEqual(returncode, 0, stderr)
        output = root / "aggregated_celltypes"
        counts = pd.read_csv(output / "celltype_counts_by_sample.csv")
        self.assertEqual(counts.columns.tolist(), ["class_id", "cell_type"])
        self.assertTrue(counts.empty)
        audit = pd.read_csv(output / "sample_aggregation_audit.csv")
        self.assertEqual(audit["slide_id"].tolist(), ["failed_1"])
        self.assertFalse(bool(audit.iloc[0]["included"]))

    def test_sampled_slide_without_seed_metadata_fails_closed(self) -> None:
        root = self.temp_path / "results"
        root.mkdir()
        write_slide(root, "sample_1", [(1, "Cancer cell", 4)], percent_slide=10, seed=None)

        returncode, _, stderr = self.run_main(["--input-root", str(root)])
        self.assertEqual(returncode, 2)
        self.assertIn("missing random_seed", stderr)

    def test_sample_map_covers_failed_roster_without_creating_zero_columns(self) -> None:
        root = self.temp_path / "results"
        root.mkdir()
        write_slide(root, "slide_ok", [(1, "Cancer cell", 4)])
        write_manifest(
            root,
            [
                {"slide_id": "slide_ok", "completed": True, "returncode": 0},
                {"slide_id": "slide_failed", "completed": False, "returncode": 1},
            ],
        )
        sample_map = self.temp_path / "sample_map.csv"
        pd.DataFrame(
            {"slide_id": ["slide_ok"], "sample_id": ["patient_1"]}
        ).to_csv(sample_map, index=False)
        returncode, _, stderr = self.run_main(
            ["--input-root", str(root), "--sample-map", str(sample_map)]
        )
        self.assertEqual(returncode, 2)
        self.assertIn("aggregation-roster", stderr)

        pd.DataFrame(
            {
                "slide_id": ["slide_ok", "slide_failed"],
                "sample_id": ["patient_1", "patient_1"],
            }
        ).to_csv(sample_map, index=False)
        returncode, _, stderr = self.run_main(
            ["--input-root", str(root), "--sample-map", str(sample_map)]
        )
        self.assertEqual(returncode, 0, stderr)
        output = root / "aggregated_celltypes"
        counts = pd.read_csv(output / "celltype_counts_by_sample.csv")
        self.assertEqual(counts.columns.tolist(), ["class_id", "cell_type", "patient_1"])
        audit = pd.read_csv(output / "sample_aggregation_audit.csv")
        self.assertEqual(set(audit["sample_id"]), {"patient_1"})
        self.assertEqual(audit["included"].tolist(), [False, True])


    def test_sample_map_rejects_matrix_header_sample_id(self) -> None:
        root = self.temp_path / "results"
        root.mkdir()
        write_slide(root, "slide_1", [(1, "Cancer cell", 4)])
        sample_map = self.temp_path / "reserved_map.csv"
        pd.DataFrame(
            {"slide_id": ["slide_1"], "sample_id": ["Class_ID"]}
        ).to_csv(sample_map, index=False)

        returncode, _, stderr = self.run_main(
            ["--input-root", str(root), "--sample-map", str(sample_map)]
        )
        self.assertEqual(returncode, 2)
        self.assertIn("matrix-header-reserved", stderr)


    def test_unmapped_slide_id_cannot_collide_with_matrix_headers(self) -> None:
        root = self.temp_path / "results"
        root.mkdir()
        write_slide(root, "cell_type", [(1, "Cancer cell", 4)])

        returncode, _, stderr = self.run_main(["--input-root", str(root)])
        self.assertEqual(returncode, 2)
        self.assertIn("matrix index headers", stderr)


if __name__ == "__main__":
    unittest.main()
