from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).parents[1] / "bin" / "aggregate_histoplus_celltypes.py"
SPEC = importlib.util.spec_from_file_location("aggregate_manifest_scope_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def write_result(root: Path, slide_id: str, count: int = 5) -> None:
    cell_dir = root / slide_id / "cell_types"
    summary_dir = root / slide_id / "summary"
    cell_dir.mkdir(parents=True)
    summary_dir.mkdir(parents=True)
    pd.DataFrame([(1, "Cancer cell", count)], columns=["class_id", "class_name", "count"]).to_csv(
        cell_dir / "class_counts.csv", index=False
    )
    (summary_dir / "summary.json").write_text(
        json.dumps(
            {
                "slide_id": slide_id,
                "n_cells": count,
                "tile_sampling": {"percent_slide": 10, "random_seed": 7},
            }
        ),
        encoding="utf-8",
    )


class ManifestScopeTests(unittest.TestCase):
    def test_manifest_excludes_unlisted_stale_folder_and_selected_false(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_result(root, "selected")
            write_result(root, "unselected")
            write_result(root, "stale")
            manifest = root / "manifest.csv"
            pd.DataFrame(
                [
                    {"slide_id": "selected", "selected": True, "completed": True, "returncode": 0},
                    {"slide_id": "unselected", "selected": False, "completed": True, "returncode": 0},
                ]
            ).to_csv(manifest, index=False)

            self.assertEqual(
                module.main(["--input-root", str(root), "--manifest", str(manifest)]), 0
            )
            counts = pd.read_csv(root / "aggregated_celltypes" / "celltype_counts_by_sample.csv")
            self.assertEqual(counts.columns.tolist(), ["class_id", "cell_type", "selected"])
            audit = pd.read_csv(root / "aggregated_celltypes" / "sample_aggregation_audit.csv")
            self.assertEqual(set(audit["slide_id"]), {"selected", "unselected"})
            self.assertEqual(
                audit.loc[audit["slide_id"] == "unselected", "status"].iloc[0],
                "excluded_unselected",
            )

    def test_extra_sample_map_rows_do_not_create_zero_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "results"
            root.mkdir()
            write_result(root, "included")
            sample_map = Path(temporary) / "sample_map.csv"
            pd.DataFrame(
                {
                    "slide_id": ["included", "failed_or_unrelated"],
                    "sample_id": ["patient_1", "patient_2"],
                }
            ).to_csv(sample_map, index=False)

            self.assertEqual(
                module.main(["--input-root", str(root), "--sample-map", str(sample_map)]), 0
            )
            counts = pd.read_csv(root / "aggregated_celltypes" / "celltype_counts_by_sample.csv")
            self.assertEqual(counts.columns.tolist(), ["class_id", "cell_type", "patient_1"])


if __name__ == "__main__":
    unittest.main()
