from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest


BIN_DIR = Path(__file__).parents[1] / "bin"
sys.path.insert(0, str(BIN_DIR))
MODULE_PATH = BIN_DIR / "mds_to_tiff.py"
SPEC = importlib.util.spec_from_file_location("mds_to_tiff", MODULE_PATH)
assert SPEC and SPEC.loader
mds_to_tiff = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mds_to_tiff
SPEC.loader.exec_module(mds_to_tiff)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0_0", (0, 0)),
        ("12_34", (12, 34)),
        ("-1_0", None),
        ("1", None),
        ("x_2", None),
        ("1_2_3", None),
    ],
)
def test_parse_tile_name(value: str, expected: tuple[int, int] | None) -> None:
    assert mds_to_tiff.parse_tile_name(value) == expected


def test_numeric_levels_sort_highest_scale_first() -> None:
    values = ["0.0625", "1", "0.25", "metadata"]
    assert sorted(values, key=mds_to_tiff.level_sort_key) == [
        "1",
        "0.25",
        "0.0625",
        "metadata",
    ]


def test_validate_mpp() -> None:
    assert mds_to_tiff.validate_mpp(0.26178) == pytest.approx(0.26178)
    with pytest.raises(mds_to_tiff.MdsExportError):
        mds_to_tiff.validate_mpp(0)


def test_compression_settings() -> None:
    assert mds_to_tiff.compression_settings("none", 6) == (None, None)
    assert mds_to_tiff.compression_settings("deflate", 7) == (
        "deflate",
        {"level": 7},
    )
    with pytest.raises(mds_to_tiff.MdsExportError):
        mds_to_tiff.compression_settings("deflate", 10)


def test_sample_id_for_nested_raw_layout(tmp_path: Path) -> None:
    nested = tmp_path / "TumorQuantAI_LymphomaWSI_022" / "1.mds"
    nested.parent.mkdir()
    nested.write_bytes(b"fixture")
    assert mds_to_tiff.sample_id_for(nested) == "TumorQuantAI_LymphomaWSI_022"


def test_write_samples_uses_canonical_tiff_path(tmp_path: Path) -> None:
    rows = [{"level": 0, "sample_id": "TumorQuantAI_LymphomaWSI_022"}]
    path = mds_to_tiff.write_samples(tmp_path, rows)
    assert path.read_text(encoding="utf-8").splitlines() == [
        "sample_id,slide_path",
        "TumorQuantAI_LymphomaWSI_022,"
        "TumorQuantAI_LymphomaWSI_022/1_L0_rgb.tif",
    ]


def test_select_inputs_uses_requested_alias_order(tmp_path: Path) -> None:
    paths = []
    for alias in (
        "TumorQuantAI_LymphomaWSI_001",
        "TumorQuantAI_LymphomaWSI_022",
    ):
        path = tmp_path / alias / "1.mds"
        path.parent.mkdir()
        path.write_bytes(b"fixture")
        paths.append(path)
    selected = mds_to_tiff.select_inputs(
        paths, ["TumorQuantAI_LymphomaWSI_022"]
    )
    assert selected == [paths[1]]


class FakeMdsPixels:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.levels = (
            mds_to_tiff.MdsLevel(0, "1", 1, 1, 16, 16),
            mds_to_tiff.MdsLevel(1, "0.5", 1, 1, 16, 16),
            mds_to_tiff.MdsLevel(2, "0.25", 1, 1, 16, 16),
        )

    def __enter__(self) -> "FakeMdsPixels":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def iter_level_tiles(
        self, level: mds_to_tiff.MdsLevel
    ):
        value = 10 + level.index
        yield np.full((16, 16, 3), value, dtype=np.uint8)


def run_args(raw: Path, output: Path) -> argparse.Namespace:
    return argparse.Namespace(
        input=raw,
        output_dir=output,
        manifest=None,
        levels=[0, 2],
        sample_id=[],
        expected_count=1,
        source_mpp=0.25,
        compression="none",
        compression_level=6,
        resume=True,
        overwrite=False,
        dry_run=False,
    )


def test_conversion_is_resumable_and_keeps_complete_roster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alias = "TumorQuantAI_LymphomaWSI_001"
    raw = tmp_path / "raw"
    source = raw / alias / "1.mds"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"synthetic MDS identity")
    output = tmp_path / "slides"
    monkeypatch.setattr(mds_to_tiff, "MdsPixels", FakeMdsPixels)

    first = mds_to_tiff.run(run_args(raw, output))
    assert {row["status"] for row in first} == {"exported"}
    assert (output / alias / "1_L0_rgb.tif").is_file()
    assert (output / alias / "1_L2_rgb.tif").is_file()
    assert alias in (output / "samples.csv").read_text(encoding="utf-8")

    second = mds_to_tiff.run(run_args(raw, output))
    assert {row["status"] for row in second} == {"verified-existing"}
    state = json.loads(
        (output / mds_to_tiff.CONVERSION_MANIFEST_NAME).read_text(
            encoding="utf-8"
        )
    )
    assert len(state["entries"]) == 2
    assert all(entry["output_sha256"] for entry in state["entries"])


def test_expected_slide_count_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alias = "TumorQuantAI_LymphomaWSI_001"
    source = tmp_path / "raw" / alias / "1.mds"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fixture")
    args = run_args(source.parent.parent, tmp_path / "slides")
    args.expected_count = 4
    monkeypatch.setattr(mds_to_tiff, "MdsPixels", FakeMdsPixels)
    with pytest.raises(mds_to_tiff.MdsExportError, match="Expected 4"):
        mds_to_tiff.run(args)


def test_conversion_rejects_nested_output_parent_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alias = "TumorQuantAI_LymphomaWSI_001"
    raw = tmp_path / "raw"
    source = raw / alias / "1.mds"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fixture")
    output = tmp_path / "slides"
    outside = tmp_path / "outside"
    output.mkdir()
    outside.mkdir()
    (output / alias).symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(mds_to_tiff, "MdsPixels", FakeMdsPixels)

    with pytest.raises(mds_to_tiff.MdsExportError, match="symlink in output path"):
        mds_to_tiff.run(run_args(raw, output))

    assert not (outside / "1_L0_rgb.tif").exists()
    assert not (outside / "1_L2_rgb.tif").exists()


def test_resume_rejects_changed_output_checksum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alias = "TumorQuantAI_LymphomaWSI_001"
    raw = tmp_path / "raw"
    source = raw / alias / "1.mds"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fixture")
    output = tmp_path / "slides"
    monkeypatch.setattr(mds_to_tiff, "MdsPixels", FakeMdsPixels)
    mds_to_tiff.run(run_args(raw, output))
    target = output / alias / "1_L0_rgb.tif"
    with target.open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(mds_to_tiff.MdsExportError, match="checksum"):
        mds_to_tiff.run(run_args(raw, output))
