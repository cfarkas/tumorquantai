from __future__ import annotations

import importlib.util
import logging
import sys
import types
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "lazyslide_histoplus_wsi_celltype.py"
SPEC = importlib.util.spec_from_file_location("histoplus_worker_zero_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class RaisingSeg:
    def __init__(self, key: str) -> None:
        self.key = key

    def cell_types(self, *args, **kwargs) -> None:
        raise KeyError(self.key)


def arguments() -> Namespace:
    return Namespace(
        histoplus_magnification="20x",
        celltypes_batch_size=2,
        num_workers=0,
        amp=False,
    )


class WorkerZeroRecoveryTests(unittest.TestCase):
    def test_only_missing_class_key_is_converted_to_empty_shapes(self) -> None:
        added: dict[str, object] = {}
        fake_gpd = types.ModuleType("geopandas")
        fake_gpd.GeoSeries = lambda *args, **kwargs: []
        fake_gpd.GeoDataFrame = lambda data, geometry: {"data": data, "geometry": geometry}
        fake_io = types.ModuleType("wsidata.io")

        def add_shapes(wsi, *, key, shapes) -> None:
            added.update({"wsi": wsi, "key": key, "shapes": shapes})

        fake_io.add_shapes = add_shapes
        zs = Namespace(seg=RaisingSeg("class"))
        wsi = object()
        with patch.dict(sys.modules, {"geopandas": fake_gpd, "wsidata.io": fake_io}):
            module.run_histoplus_cell_types(
                zs, wsi, object(), arguments(), "cpu", logging.getLogger("zero-test")
            )
        self.assertIs(added["wsi"], wsi)
        self.assertEqual(added["key"], "cell_types")

    def test_unrelated_keyerror_is_not_hidden(self) -> None:
        zs = Namespace(seg=RaisingSeg("unexpected"))
        with self.assertRaisesRegex(KeyError, "unexpected"):
            module.run_histoplus_cell_types(
                zs, object(), object(), arguments(), "cpu", logging.getLogger("zero-test")
            )


if __name__ == "__main__":
    unittest.main()
