from __future__ import annotations

import csv
import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest


BIN_DIR = Path(__file__).parents[1] / "bin"
sys.path.insert(0, str(BIN_DIR))
MODULE_PATH = BIN_DIR / "download_zenodo_mds.py"
SPEC = importlib.util.spec_from_file_location("download_zenodo_mds", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def manifest_text(alias: str = "TumorQuantAI_LymphomaWSI_001") -> str:
    payload = b"sanitized"
    row = {
        "schema_version": "2",
        "alias": alias,
        "zenodo_filename": f"{alias}.mds",
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "md5": hashlib.md5(payload, usedforsecurity=False).hexdigest(),
        "source_mpp": "0.261780",
        "level_count": "3",
        "level_dimensions": "[[10,10],[5,5],[3,3]]",
        "pixel_stream_count": "10",
        "pixel_sample_sha256": "a" * 64,
        "pixel_full_sha256": "b" * 64,
        "sanitization_profile": "pixel-preserving-nonpixel-redaction-v2",
    }
    from io import StringIO

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=sorted(module.REQUIRED_COLUMNS))
    writer.writeheader()
    writer.writerow(row)
    return buffer.getvalue()


def test_parse_manifest_maps_alias_to_raw_tree() -> None:
    rows = module.parse_manifest_text(manifest_text(), "fixture")
    assert len(rows) == 1
    assert rows[0].dataset_path == "raw/TumorQuantAI_LymphomaWSI_001/1.mds"
    assert rows[0].source_mpp == pytest.approx(0.26178)
    assert rows[0].level_dimensions[2] == (3, 3)


def test_parse_manifest_rejects_unsanitized_profile() -> None:
    text = manifest_text().replace(
        "pixel-preserving-nonpixel-redaction-v2", "unreviewed"
    )
    with pytest.raises(module.base.DownloadError, match="sanitization profile"):
        module.parse_manifest_text(text, "fixture")


def test_parse_manifest_rejects_extra_private_column() -> None:
    text = manifest_text().replace(
        "alias,", "source_path,alias,", 1
    ).replace("\n", "\n/private/source,", 1)
    with pytest.raises(module.base.DownloadError, match="unrecognized"):
        module.parse_manifest_text(text, "fixture")


def test_dry_run_does_not_require_record(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(manifest_text(), encoding="utf-8")
    result = module.download_mds_dataset(
        manifest=manifest,
        record=None,
        output_dir=tmp_path / "download",
        dry_run=True,
    )
    assert result["file_count"] == 1
    assert result["files"][0]["target"].endswith(
        "raw/TumorQuantAI_LymphomaWSI_001/1.mds"
    )
    assert not (tmp_path / "download").exists()


def test_render_raw_samples() -> None:
    rows = module.parse_manifest_text(manifest_text(), "fixture")
    text = module.render_raw_samples(rows)
    assert "sample_id,mds_path,source_mpp" in text
    assert "TumorQuantAI_LymphomaWSI_001/1.mds" in text


def test_select_rows_supports_fast_subset() -> None:
    first = module.parse_manifest_text(manifest_text(), "fixture")[0]
    second = module.parse_manifest_text(
        manifest_text("TumorQuantAI_LymphomaWSI_022"), "fixture"
    )[0]
    selected = module.select_rows(
        [first, second], ["TumorQuantAI_LymphomaWSI_022"]
    )
    assert [row.alias for row in selected] == ["TumorQuantAI_LymphomaWSI_022"]


def test_expected_count_is_fail_closed(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(manifest_text(), encoding="utf-8")
    with pytest.raises(module.base.DownloadError, match="Expected 4"):
        module.download_mds_dataset(
            manifest=manifest,
            record=None,
            output_dir=tmp_path / "download",
            dry_run=True,
            expected_count=4,
        )


def test_only_official_zenodo_api_origins_are_accepted() -> None:
    assert module.validated_api_url("https://zenodo.org/api/") == (
        "https://zenodo.org/api"
    )
    with pytest.raises(module.base.DownloadError, match="api-url"):
        module.validated_api_url("https://example.org/api")
    with pytest.raises(module.base.DownloadError, match="trusted Zenodo"):
        module.require_api_origin(
            "https://example.org/file.mds",
            "https://zenodo.org/api",
            "record file",
        )
