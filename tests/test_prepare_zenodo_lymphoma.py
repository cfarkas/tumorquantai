from __future__ import annotations

import csv
import importlib.util
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import tifffile


SCRIPT = Path(__file__).parents[1] / "bin" / "prepare_zenodo_lymphoma.py"
SPEC = importlib.util.spec_from_file_location("prepare_zenodo_lymphoma", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
prepare = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = prepare
SPEC.loader.exec_module(prepare)


class PrepareZenodoLymphomaTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def make_tiff(self, relative: str, value: int = 0, description: str | None = None) -> Path:
        path = self.root / "exports" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        pixels = np.full((12, 16, 3), value, dtype=np.uint8)
        tifffile.imwrite(path, pixels, photometric="rgb", description=description)
        return path

    def write_manifest(self, rows: list[dict[str, object]]) -> Path:
        path = self.root / "export_manifest.csv"
        columns = (
            "slide_id",
            "source_path",
            "relative_parent",
            "level",
            "output_path",
            "status",
            "error_message",
        )
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def pair_rows(self, slide_id: str, parent: str, seed: int) -> list[dict[str, object]]:
        rows = []
        for level in (0, 2):
            path = self.make_tiff(f"{parent}/1_L{level}_rgb.tif", seed + level)
            rows.append(
                {
                    "slide_id": slide_id,
                    "source_path": f"/private/raw/{parent}/1.mds",
                    "relative_parent": parent,
                    "level": level,
                    "output_path": path,
                    "status": "exported",
                    "error_message": "",
                }
            )
        return rows

    def test_prepares_deterministic_aliases_without_copying_or_identifier_leakage(self) -> None:
        manifest = self.write_manifest(
            self.pair_rows("case-10-private", "case-10-private", 10)
            + self.pair_rows("case-2-private", "case-2-private", 2)
        )
        public_dir = self.root / "public"
        private_mapping = self.root / "private" / "source_mapping.csv"

        result = prepare.prepare(
            manifest,
            public_dir,
            private_mapping,
            source_mpp=0.261780,
            expected_pairs=2,
        )

        self.assertEqual(result["pair_count"], 2)
        self.assertEqual(result["file_count"], 4)
        with (public_dir / prepare.PUBLIC_MANIFEST).open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            public_rows = list(csv.DictReader(handle))
        self.assertEqual(
            [row["alias"] for row in public_rows],
            [
                "TumorQuantAI_LymphomaWSI_001",
                "TumorQuantAI_LymphomaWSI_001",
                "TumorQuantAI_LymphomaWSI_002",
                "TumorQuantAI_LymphomaWSI_002",
            ],
        )
        self.assertEqual([row["level"] for row in public_rows], ["0", "2", "0", "2"])
        public_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in public_dir.iterdir()
            if path.is_file()
        )
        self.assertNotIn("case-2-private", public_text)
        self.assertNotIn("case-10-private", public_text)
        self.assertFalse(any(path.suffix == ".tif" for path in public_dir.iterdir()))
        self.assertEqual(stat.S_IMODE(private_mapping.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(public_dir.stat().st_mode), 0o755)
        self.assertIn("case-2-private", private_mapping.read_text(encoding="utf-8"))
        with private_mapping.open("r", encoding="utf-8", newline="") as handle:
            private_rows = list(csv.DictReader(handle))
        self.assertEqual(
            [(row["alias"], row["slide_id"]) for row in private_rows[::2]],
            [
                ("TumorQuantAI_LymphomaWSI_001", "case-10-private"),
                ("TumorQuantAI_LymphomaWSI_002", "case-2-private"),
            ],
        )
        sample_lines = (public_dir / prepare.PUBLIC_SAMPLES).read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(len(sample_lines), 3)
        with (public_dir / prepare.PUBLIC_SAMPLES).open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            sample_rows = list(csv.DictReader(handle))
        self.assertEqual(
            [row["slide_path"] for row in sample_rows],
            [
                "TumorQuantAI_LymphomaWSI_001/1_L0_rgb.tif",
                "TumorQuantAI_LymphomaWSI_002/1_L0_rgb.tif",
            ],
        )

    def test_rejects_private_mapping_inside_public_tree(self) -> None:
        manifest = self.write_manifest(self.pair_rows("private-1", "private-1", 1))
        with self.assertRaisesRegex(prepare.PreparationError, "outside --public-output"):
            prepare.prepare(
                manifest,
                self.root / "public",
                self.root / "public" / "private.csv",
                source_mpp=0.261780,
            )

    def test_rejects_incomplete_exported_pair(self) -> None:
        rows = self.pair_rows("private-1", "private-1", 1)
        manifest = self.write_manifest(rows[:1])
        with self.assertRaisesRegex(prepare.PreparationError, "without exactly one"):
            prepare.prepare(
                manifest,
                self.root / "public",
                self.root / "private.csv",
                source_mpp=0.261780,
            )

    def test_rejects_source_identifier_embedded_in_tiff_metadata(self) -> None:
        slide_id = "ACCESSION-PRIVATE-123"
        rows = []
        for level in (0, 2):
            path = self.make_tiff(
                f"private/1_L{level}_rgb.tif",
                level,
                description=f"Scanner record {slide_id}",
            )
            rows.append(
                {
                    "slide_id": slide_id,
                    "source_path": "/private/raw/ACCESSION-PRIVATE-123/1.mds",
                    "relative_parent": "ACCESSION-PRIVATE-123",
                    "level": level,
                    "output_path": path,
                    "status": "exported",
                    "error_message": "",
                }
            )
        manifest = self.write_manifest(rows)
        with self.assertRaisesRegex(prepare.PreparationError, "privacy validation"):
            prepare.prepare(
                manifest,
                self.root / "public",
                self.root / "private.csv",
                source_mpp=0.261780,
            )

    def test_expected_pair_count_fails_closed(self) -> None:
        manifest = self.write_manifest(self.pair_rows("private-1", "private-1", 1))
        with self.assertRaisesRegex(prepare.PreparationError, "Expected 22"):
            prepare.prepare(
                manifest,
                self.root / "public",
                self.root / "private.csv",
                source_mpp=0.261780,
                expected_pairs=22,
            )

    def test_overwrite_refuses_unknown_public_content_without_touching_private_mapping(self) -> None:
        manifest = self.write_manifest(self.pair_rows("private-1", "private-1", 1))
        public_dir = self.root / "public"
        private_mapping = self.root / "private.csv"
        prepare.prepare(
            manifest, public_dir, private_mapping, source_mpp=0.261780
        )
        sentinel = public_dir / "DO_NOT_DELETE.txt"
        sentinel.write_text("belongs to user\n", encoding="utf-8")
        previous_private = private_mapping.read_bytes()

        with self.assertRaisesRegex(prepare.PreparationError, "Refusing --overwrite"):
            prepare.prepare(
                manifest,
                public_dir,
                private_mapping,
                source_mpp=0.261780,
                overwrite=True,
            )

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "belongs to user\n")
        self.assertEqual(private_mapping.read_bytes(), previous_private)

    def test_overwrite_accepts_intact_generated_output(self) -> None:
        manifest = self.write_manifest(self.pair_rows("private-1", "private-1", 1))
        public_dir = self.root / "public"
        private_mapping = self.root / "private.csv"
        prepare.prepare(
            manifest, public_dir, private_mapping, source_mpp=0.261780
        )
        result = prepare.prepare(
            manifest,
            public_dir,
            private_mapping,
            source_mpp=0.261780,
            overwrite=True,
        )
        self.assertEqual(result["pair_count"], 1)
        self.assertEqual(
            {path.name for path in public_dir.iterdir()},
            prepare.GENERATED_PUBLIC_FILES,
        )

    def test_rejects_identifier_in_later_tiff_page(self) -> None:
        slide_id = "ACCESSION-PRIVATE-PAGE-TWO"
        l0 = self.root / "exports" / "private" / "1_L0_rgb.tif"
        l0.parent.mkdir(parents=True, exist_ok=True)
        pixels = np.zeros((12, 16, 3), dtype=np.uint8)
        with tifffile.TiffWriter(l0) as writer:
            writer.write(pixels, photometric="rgb")
            writer.write(
                pixels,
                photometric="rgb",
                description=f"Scanner record {slide_id}",
            )
        l2 = self.make_tiff("private/1_L2_rgb.tif")
        rows = [
            {
                "slide_id": slide_id,
                "source_path": f"/private/raw/{slide_id}/1.mds",
                "relative_parent": slide_id,
                "level": level,
                "output_path": path,
                "status": "exported",
                "error_message": "",
            }
            for level, path in ((0, l0), (2, l2))
        ]
        manifest = self.write_manifest(rows)
        with self.assertRaisesRegex(prepare.PreparationError, r"page\[1\]"):
            prepare.prepare(
                manifest,
                self.root / "public",
                self.root / "private.csv",
                source_mpp=0.261780,
            )


if __name__ == "__main__":
    unittest.main()
