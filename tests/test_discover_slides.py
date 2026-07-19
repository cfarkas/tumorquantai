from __future__ import annotations

import contextlib
import csv
import hashlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "bin" / "discover_slides.py"
SPEC = importlib.util.spec_from_file_location("discover_slides", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
discover = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(discover)


class DiscoverSlidesTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "inputs"
        self.root.mkdir()

    def touch_slide(self, relative: str, payload: bytes = b"slide") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def run_main(self, *arguments: str) -> tuple[int, str]:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            returncode = discover.main(list(arguments))
        return returncode, stderr.getvalue()

    def read_manifest(self, path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))

    def test_identical_basenames_in_different_cases_remain_unique(self) -> None:
        self.touch_slide("case_a/1_L0_rgb.tif")
        self.touch_slide("case_b/1_L0_rgb.tif")
        self.touch_slide("case_a/1_L2_rgb.tif")
        manifest = self.root.parent / "slides.tsv"

        returncode, stderr = self.run_main(
            "--input-root", str(self.root), "--output", str(manifest)
        )
        self.assertEqual(returncode, 0, stderr)
        rows = self.read_manifest(manifest)
        self.assertEqual([row["sample_id"] for row in rows], ["case_a_1", "case_b_1"])
        self.assertEqual(
            [row["relative_path"] for row in rows],
            ["case_a/1_L0_rgb.tif", "case_b/1_L0_rgb.tif"],
        )

    def test_excluded_output_tree_is_never_rediscovered(self) -> None:
        self.touch_slide("case_a/1_L0_rgb.tif")
        output_root = self.root / "generated_results"
        generated = output_root / "case_a" / "pyramidal" / "copy_L0_rgb.tif"
        generated.parent.mkdir(parents=True)
        generated.write_bytes(b"generated")
        manifest = self.root.parent / "slides.tsv"

        returncode, stderr = self.run_main(
            "--input-root",
            str(self.root),
            "--output",
            str(manifest),
            "--exclude-root",
            str(output_root),
        )
        self.assertEqual(returncode, 0, stderr)
        self.assertEqual(len(self.read_manifest(manifest)), 1)

    def test_explicit_sample_sheet_rejects_duplicate_ids(self) -> None:
        self.touch_slide("case_a/1_L0_rgb.tif")
        self.touch_slide("case_b/1_L0_rgb.tif")
        sample_sheet = self.root.parent / "samples.csv"
        sample_sheet.write_text(
            "sample_id,slide_path\npatient_1,case_a/1_L0_rgb.tif\n"
            "patient_1,case_b/1_L0_rgb.tif\n",
            encoding="utf-8",
        )
        manifest = self.root.parent / "slides.tsv"

        returncode, stderr = self.run_main(
            "--input-root",
            str(self.root),
            "--output",
            str(manifest),
            "--sample-sheet",
            str(sample_sheet),
        )
        self.assertEqual(returncode, 2)
        self.assertIn("Duplicate sample IDs", stderr)

    def test_include_filter_uses_collision_safe_sample_id(self) -> None:
        self.touch_slide("case_2/1_L0_rgb.tif")
        self.touch_slide("case_10/1_L0_rgb.tif")
        manifest = self.root.parent / "slides.tsv"

        returncode, stderr = self.run_main(
            "--input-root",
            str(self.root),
            "--output",
            str(manifest),
            "--include",
            "case_10*",
        )
        self.assertEqual(returncode, 0, stderr)
        self.assertEqual([row["sample_id"] for row in self.read_manifest(manifest)], ["case_10_1"])

    def test_optional_l2_is_content_hashed_and_missing_is_explicit(self) -> None:
        self.touch_slide("case_a/1_L0_rgb.tif")
        l2 = self.touch_slide("case_a/1_L2_rgb.tif", b"downsampled pixels")
        self.touch_slide("case_b/1_L0_rgb.tif")
        manifest = self.root.parent / "slides.tsv"

        returncode, stderr = self.run_main(
            "--input-root", str(self.root), "--output", str(manifest),
            "--l2-policy", "optional",
        )
        self.assertEqual(returncode, 0, stderr)
        rows = {row["sample_id"]: row for row in self.read_manifest(manifest)}
        expected = hashlib.sha256(l2.read_bytes()).hexdigest()
        self.assertEqual(rows["case_a_1"]["l2_content_sha256"], expected)
        self.assertEqual(rows["case_a_1"]["l2_fingerprint"], f"sha256:{expected}")
        self.assertEqual(rows["case_a_1"]["l2_exists"], "True")
        self.assertEqual(rows["case_b_1"]["l2_fingerprint"], "missing")
        self.assertEqual(rows["case_b_1"]["l2_exists"], "False")

    def test_required_l2_fails_closed(self) -> None:
        self.touch_slide("case_a/1_L0_rgb.tif")
        manifest = self.root.parent / "slides.tsv"

        returncode, stderr = self.run_main(
            "--input-root", str(self.root), "--output", str(manifest),
            "--l2-policy", "required",
        )
        self.assertEqual(returncode, 2)
        self.assertIn("requires the companion L2", stderr)
        self.assertFalse(manifest.exists())

    def test_l2_content_change_invalidates_fingerprint_with_unchanged_metadata(self) -> None:
        self.touch_slide("case_a/1_L0_rgb.tif")
        l2 = self.touch_slide("case_a/1_L2_rgb.tif", b"A" * 32)
        manifest = self.root.parent / "slides.tsv"
        returncode, stderr = self.run_main(
            "--input-root", str(self.root), "--output", str(manifest),
            "--l2-policy", "optional",
        )
        self.assertEqual(returncode, 0, stderr)
        before_fingerprint = self.read_manifest(manifest)[0]["l2_fingerprint"]
        before_stat = l2.stat()

        l2.write_bytes(b"B" * 32)
        os.utime(l2, ns=(before_stat.st_atime_ns, before_stat.st_mtime_ns))
        returncode, stderr = self.run_main(
            "--input-root", str(self.root), "--output", str(manifest),
            "--l2-policy", "optional",
        )
        self.assertEqual(returncode, 0, stderr)
        after = self.read_manifest(manifest)[0]
        self.assertEqual(after["l2_size_bytes"], "32")
        self.assertEqual(after["l2_mtime_ns"], str(before_stat.st_mtime_ns))
        self.assertNotEqual(after["l2_fingerprint"], before_fingerprint)

    def test_l0_fingerprint_uses_ctime_and_inode_metadata(self) -> None:
        l0 = self.touch_slide("case_a/1_L0_rgb.tif", b"A" * 32)
        manifest = self.root.parent / "slides.tsv"
        returncode, stderr = self.run_main(
            "--input-root", str(self.root), "--output", str(manifest)
        )
        self.assertEqual(returncode, 0, stderr)
        before = self.read_manifest(manifest)[0]
        before_stat = l0.stat()

        l0.write_bytes(b"B" * 32)
        os.utime(l0, ns=(before_stat.st_atime_ns, before_stat.st_mtime_ns))
        returncode, stderr = self.run_main(
            "--input-root", str(self.root), "--output", str(manifest)
        )
        self.assertEqual(returncode, 0, stderr)
        after = self.read_manifest(manifest)[0]
        self.assertEqual(after["size_bytes"], before["size_bytes"])
        self.assertEqual(after["mtime_ns"], before["mtime_ns"])
        self.assertEqual(after["inode"], before["inode"])
        self.assertNotEqual(after["ctime_ns"], before["ctime_ns"])
        self.assertNotEqual(after["fingerprint"], before["fingerprint"])

    def test_l2_hash_rejects_metadata_change_during_read(self) -> None:
        l2 = self.touch_slide("case_a/1_L2_rgb.tif", b"downsampled pixels")
        before = l2.stat()
        after = SimpleNamespace(
            st_dev=before.st_dev,
            st_ino=before.st_ino,
            st_size=before.st_size,
            st_mtime_ns=before.st_mtime_ns,
            st_ctime_ns=before.st_ctime_ns + 1,
        )
        with mock.patch.object(discover.Path, "stat", side_effect=[before, after]):
            with self.assertRaisesRegex(discover.DiscoveryError, "changed while"):
                discover.content_sha256(l2)


    def test_rejects_workflow_reserved_sample_ids(self) -> None:
        self.touch_slide("case_a/1_L0_rgb.tif")
        sample_sheet = self.root.parent / "reserved.csv"
        sample_sheet.write_text(
            "sample_id,slide_path\naggregated_celltypes,case_a/1_L0_rgb.tif\n",
            encoding="utf-8",
        )
        manifest = self.root.parent / "slides.tsv"
        returncode, stderr = self.run_main(
            "--input-root", str(self.root), "--output", str(manifest),
            "--sample-sheet", str(sample_sheet),
        )
        self.assertEqual(returncode, 2)
        self.assertIn("workflow-owned directories", stderr)


    def test_rejects_matrix_header_sample_ids(self) -> None:
        for reserved_id in ("class_id", "cell_type", "slides.json"):
            with self.subTest(reserved_id=reserved_id):
                slide = self.touch_slide(f"{reserved_id}/1_L0_rgb.tif")
                sample_sheet = self.root.parent / f"reserved_{reserved_id}.csv"
                sample_sheet.write_text(
                    f"sample_id,slide_path\n{reserved_id},{slide.relative_to(self.root)}\n",
                    encoding="utf-8",
                )
                manifest = self.root.parent / f"slides_{reserved_id}.tsv"
                returncode, stderr = self.run_main(
                    "--input-root",
                    str(self.root),
                    "--output",
                    str(manifest),
                    "--sample-sheet",
                    str(sample_sheet),
                )
                self.assertEqual(returncode, 2)
                self.assertIn("workflow-owned", stderr)


if __name__ == "__main__":
    unittest.main()
