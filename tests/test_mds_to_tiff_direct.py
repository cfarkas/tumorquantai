from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest


BIN_DIR = Path(__file__).parents[1] / "bin"
sys.path.insert(0, str(BIN_DIR))
MODULE_PATH = BIN_DIR / "mds_to_tiff.py"
SPEC = importlib.util.spec_from_file_location("mds_to_tiff_direct", MODULE_PATH)
assert SPEC and SPEC.loader
mds_to_tiff = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mds_to_tiff
SPEC.loader.exec_module(mds_to_tiff)


FIELDNAMES = (
    "schema_version",
    "alias",
    "zenodo_filename",
    "size_bytes",
    "sha256",
    "md5",
    "source_mpp",
    "level_count",
    "level_dimensions",
    "pixel_stream_count",
    "pixel_sample_sha256",
    "pixel_full_sha256",
    "sanitization_profile",
)


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

    def iter_level_tiles(self, level: mds_to_tiff.MdsLevel):
        yield np.full((16, 16, 3), 10 + level.index, dtype=np.uint8)


def write_manifest(path: Path, sources: dict[str, bytes]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for alias, payload in sources.items():
            writer.writerow(
                {
                    "schema_version": 2,
                    "alias": alias,
                    "zenodo_filename": f"{alias}.mds",
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "md5": hashlib.md5(payload, usedforsecurity=False).hexdigest(),
                    "source_mpp": "0.26178",
                    "level_count": 3,
                    "level_dimensions": json.dumps(
                        [[16, 16], [16, 16], [16, 16]],
                        separators=(",", ":"),
                    ),
                    "pixel_stream_count": 3,
                    "pixel_sample_sha256": "1" * 64,
                    "pixel_full_sha256": "2" * 64,
                    "sanitization_profile": (
                        "pixel-preserving-nonpixel-redaction-v2"
                    ),
                }
            )
    return path


def arguments(
    source: Path,
    manifest: Path,
    output: Path,
    *,
    sample_ids: list[str] | None = None,
    expected_count: int = 1,
) -> argparse.Namespace:
    return argparse.Namespace(
        input=source,
        output_dir=output,
        manifest=manifest,
        levels=[0, 2],
        sample_id=sample_ids or [],
        expected_count=expected_count,
        source_mpp=0.26178,
        compression="none",
        compression_level=6,
        resume=True,
        overwrite=False,
        dry_run=False,
    )


def test_direct_zenodo_file_converts_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alias = "TumorQuantAI_LymphomaWSI_022"
    payload = b"direct Zenodo MDS fixture"
    source = tmp_path / f"{alias}.mds"
    source.write_bytes(payload)
    manifest = write_manifest(tmp_path / "manifest.csv", {alias: payload})
    output = tmp_path / "slides"
    monkeypatch.setattr(mds_to_tiff, "MdsPixels", FakeMdsPixels)

    first = mds_to_tiff.run(arguments(source, manifest, output))
    second = mds_to_tiff.run(arguments(source, manifest, output))

    assert {row["status"] for row in first} == {"exported"}
    assert {row["status"] for row in second} == {"verified-existing"}
    assert (output / alias / "1_L0_rgb.tif").is_file()
    assert (output / alias / "1_L2_rgb.tif").is_file()
    assert (output / "samples.csv").read_text(encoding="utf-8").splitlines() == [
        "sample_id,slide_path",
        f"{alias},{alias}/1_L0_rgb.tif",
    ]


def test_directory_of_direct_zenodo_files_converts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = {
        "TumorQuantAI_LymphomaWSI_002": b"sample two",
        "TumorQuantAI_LymphomaWSI_022": b"sample twenty two",
    }
    data = tmp_path / "data"
    data.mkdir()
    for alias, payload in sources.items():
        (data / f"{alias}.mds").write_bytes(payload)
    manifest = write_manifest(data / "manifest.csv", sources)
    output = tmp_path / "slides"
    monkeypatch.setattr(mds_to_tiff, "MdsPixels", FakeMdsPixels)

    rows = mds_to_tiff.run(
        arguments(data, manifest, output, expected_count=len(sources))
    )

    assert {row["sample_id"] for row in rows} == set(sources)
    assert (output / "samples.csv").read_text(encoding="utf-8").count("\n") == 3


def test_manifest_keeps_legacy_alias_directory_compatible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alias = "TumorQuantAI_LymphomaWSI_022"
    payload = b"legacy downloader MDS fixture"
    source = tmp_path / "raw" / alias / "1.mds"
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    manifest = write_manifest(tmp_path / "manifest.csv", {alias: payload})
    output = tmp_path / "slides"
    monkeypatch.setattr(mds_to_tiff, "MdsPixels", FakeMdsPixels)

    rows = mds_to_tiff.run(arguments(source.parent.parent, manifest, output))

    assert {row["sample_id"] for row in rows} == {alias}
    assert {row["status"] for row in rows} == {"exported"}
    assert (output / alias / "1_L0_rgb.tif").is_file()


def test_requested_manifest_sample_must_have_a_file(tmp_path: Path) -> None:
    available = "TumorQuantAI_LymphomaWSI_022"
    missing = "TumorQuantAI_LymphomaWSI_002"
    payloads = {available: b"available", missing: b"missing"}
    source = tmp_path / f"{available}.mds"
    source.write_bytes(payloads[available])
    manifest = write_manifest(tmp_path / "manifest.csv", payloads)

    with pytest.raises(mds_to_tiff.MdsExportError, match="absent"):
        mds_to_tiff.run(
            arguments(
                source,
                manifest,
                tmp_path / "slides",
                sample_ids=[missing],
            )
        )


def test_direct_file_checksum_must_match_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alias = "TumorQuantAI_LymphomaWSI_022"
    source = tmp_path / f"{alias}.mds"
    source.write_bytes(b"original")
    manifest = write_manifest(tmp_path / "manifest.csv", {alias: b"original"})
    source.write_bytes(b"changed!")
    monkeypatch.setattr(mds_to_tiff, "MdsPixels", FakeMdsPixels)

    with pytest.raises(mds_to_tiff.MdsExportError, match="checksum"):
        mds_to_tiff.run(arguments(source, manifest, tmp_path / "slides"))


def test_direct_file_size_must_match_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alias = "TumorQuantAI_LymphomaWSI_022"
    source = tmp_path / f"{alias}.mds"
    source.write_bytes(b"original")
    manifest = write_manifest(tmp_path / "manifest.csv", {alias: b"original"})
    source.write_bytes(b"different length")
    monkeypatch.setattr(mds_to_tiff, "MdsPixels", FakeMdsPixels)

    with pytest.raises(mds_to_tiff.MdsExportError, match="checksum"):
        mds_to_tiff.run(arguments(source, manifest, tmp_path / "slides"))


def test_duplicate_direct_and_legacy_candidates_are_ambiguous(tmp_path: Path) -> None:
    alias = "TumorQuantAI_LymphomaWSI_022"
    payload = b"same public sample"
    direct = tmp_path / f"{alias}.mds"
    direct.write_bytes(payload)
    legacy = tmp_path / "raw" / alias / "1.mds"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(payload)
    manifest = write_manifest(tmp_path / "manifest.csv", {alias: payload})

    with pytest.raises(mds_to_tiff.MdsExportError, match="Ambiguous MDS inputs"):
        mds_to_tiff.run(arguments(tmp_path, manifest, tmp_path / "slides"))


def test_manifest_rejects_renamed_direct_file(tmp_path: Path) -> None:
    alias = "TumorQuantAI_LymphomaWSI_022"
    payload = b"public sample"
    source = tmp_path / "renamed.mds"
    source.write_bytes(payload)
    manifest = write_manifest(tmp_path / "manifest.csv", {alias: payload})

    with pytest.raises(mds_to_tiff.MdsExportError, match="zenodo_filename"):
        mds_to_tiff.run(arguments(source, manifest, tmp_path / "slides"))
