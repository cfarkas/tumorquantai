from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).parents[1] / "bin" / "aggregate_histoplus_celltypes.py"
SPEC = importlib.util.spec_from_file_location("aggregate_zero_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def write_result(root: Path, slide_id: str, rows, *, declared_zero: bool = False) -> None:
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
        "zero_detections": declared_zero,
        "tile_sampling": {"percent_slide": 10, "random_seed": 7},
    }
    (summary_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


class ZeroDetectionTests(unittest.TestCase):
    def test_declared_zero_is_zero_column_but_undeclared_empty_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_result(root, "detected", [(1, "Cancer cell", 5)])
            write_result(root, "verified_zero", [], declared_zero=True)

            self.assertEqual(module.main(["--input-root", str(root)]), 0)
            counts = pd.read_csv(root / "aggregated_celltypes" / "celltype_counts_by_sample.csv")
            self.assertEqual(counts["detected"].tolist(), [5])
            self.assertEqual(counts["verified_zero"].tolist(), [0])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_result(root, "detected", [(1, "Cancer cell", 5)])
            write_result(root, "ambiguous_empty", [], declared_zero=False)
            self.assertEqual(module.main(["--input-root", str(root)]), 2)


    def test_all_verified_zero_samples_write_empty_row_matrices(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_result(root, "zero_a", [], declared_zero=True)
            write_result(root, "zero_b", [], declared_zero=True)
            self.assertEqual(module.main(["--input-root", str(root)]), 0)
            counts = pd.read_csv(root / "aggregated_celltypes" / "celltype_counts_by_sample.csv")
            self.assertEqual(counts.columns.tolist(), ["class_id", "cell_type", "zero_a", "zero_b"])
            self.assertTrue(counts.empty)


if __name__ == "__main__":
    unittest.main()
