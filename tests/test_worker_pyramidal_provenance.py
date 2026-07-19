from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "lazyslide_histoplus_wsi_celltype.py"
SPEC = importlib.util.spec_from_file_location("histoplus_worker_pyramid_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def arguments() -> Namespace:
    return Namespace(
        convert_to_pyramidal=True,
        pyramidal_root=None,
        pyramidal_tile=512,
        pyramidal_compression="lzw",
        pyramidal_jpeg_q=90,
        overwrite=False,
    )


class PyramidalCacheProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "slide_L0_rgb.tif"
        self.source.write_bytes(b"source-v1")
        self.output = self.root / "result"
        self.job = module.SlideJob("sample", Path("."), "slide_L0_rgb", self.source)
        self.args = arguments()
        self.destination = module.pyramidal_output_path(self.args, self.job, self.output)
        self.sidecar = module.pyramidal_cache_provenance_path(self.destination)
        self.conversion_count = 0
        self.logger = logging.getLogger(f"pyramid-provenance-test-{id(self)}")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def inspect_layout(self, path: Path) -> dict[str, object]:
        path = Path(path)
        is_pyramid = path != self.source and path.is_file() and path.read_bytes().startswith(b"pyramid-")
        return {
            "path": str(path),
            "exists": path.is_file(),
            "n_levels": 2 if is_pyramid else 1,
            "is_tiled": is_pyramid,
            "is_bigtiff": is_pyramid,
            "width": 10,
            "height": 10,
            "error": None,
        }

    def convert(self, _src: Path, temporary_destination: Path, _args: Namespace) -> None:
        self.conversion_count += 1
        Path(temporary_destination).write_bytes(f"pyramid-{self.conversion_count}".encode("ascii"))

    def ensure(self) -> tuple[Path, dict[str, object]]:
        with (
            patch.object(module, "inspect_tiff_layout", side_effect=self.inspect_layout),
            patch.object(module, "_convert_with_pyvips", side_effect=self.convert),
        ):
            return module.ensure_pyramidal_processing_slide(
                self.job,
                self.output,
                self.args,
                self.logger,
            )

    def test_reuses_only_a_valid_pyramid_with_exact_provenance(self) -> None:
        path, summary = self.ensure()
        self.assertEqual(path, self.destination)
        self.assertEqual(summary["converted"], True)
        self.assertEqual(self.conversion_count, 1)
        self.assertEqual(
            json.loads(self.sidecar.read_text(encoding="utf-8")),
            module.pyramidal_cache_provenance(self.source, self.args),
        )

        _path, cached_summary = self.ensure()
        self.assertEqual(cached_summary["backend"], "cached")
        self.assertEqual(self.conversion_count, 1)

        self.destination.write_bytes(b"not-a-valid-pyramid")
        _path, rebuilt_summary = self.ensure()
        self.assertEqual(rebuilt_summary["converted"], True)
        self.assertEqual(self.conversion_count, 2)

    def test_missing_corrupt_and_mismatched_sidecars_rebuild(self) -> None:
        self.ensure()

        self.sidecar.unlink()
        self.ensure()
        self.assertEqual(self.conversion_count, 2)

        self.sidecar.write_text("{broken", encoding="utf-8")
        self.ensure()
        self.assertEqual(self.conversion_count, 3)

        mismatched = module.pyramidal_cache_provenance(self.source, self.args)
        mismatched["conversion"]["tile"] = 1024
        self.sidecar.write_text(json.dumps(mismatched), encoding="utf-8")
        self.ensure()
        self.assertEqual(self.conversion_count, 4)

    def test_source_or_conversion_change_rebuilds_and_sidecar_is_published_last(self) -> None:
        real_atomic_write = module.write_json_atomic
        publication_events: list[str] = []

        def checked_atomic_write(path: Path, payload: dict[str, object]) -> None:
            self.assertTrue(self.destination.is_file())
            self.assertTrue(module.is_tiled_pyramidal_tiff(self.inspect_layout(self.destination)))
            publication_events.append("sidecar")
            real_atomic_write(path, payload)

        with patch.object(module, "write_json_atomic", side_effect=checked_atomic_write):
            self.ensure()
        self.assertEqual(publication_events, ["sidecar"])

        source_stat = self.source.stat()
        self.source.write_bytes(b"source-v2")
        os.utime(
            self.source,
            ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
        )
        self.ensure()
        self.assertEqual(self.conversion_count, 2)

        self.args.pyramidal_tile = 1024
        self.ensure()
        self.assertEqual(self.conversion_count, 3)
        sidecar = json.loads(self.sidecar.read_text(encoding="utf-8"))
        self.assertEqual(sidecar["source_l0"], module.input_file_fingerprint(self.source))
        self.assertEqual(sidecar["conversion"]["tile"], 1024)


if __name__ == "__main__":
    unittest.main()
