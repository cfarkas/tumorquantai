from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import numpy as np
import pytest
import tifffile


ROOT = Path(__file__).parents[1]

PREPARE_SCRIPT = ROOT / "bin" / "prepare_breast_ihc_patch_release.py"
PREPARE_SPEC = importlib.util.spec_from_file_location(
    "package_test_prepare_breast_release",
    PREPARE_SCRIPT,
)
assert PREPARE_SPEC is not None and PREPARE_SPEC.loader is not None
prepare = importlib.util.module_from_spec(PREPARE_SPEC)
sys.modules[PREPARE_SPEC.name] = prepare
PREPARE_SPEC.loader.exec_module(prepare)

PACKAGE_SCRIPT = ROOT / "bin" / "package_breast_ihc_patch_release.py"
PACKAGE_SPEC = importlib.util.spec_from_file_location(
    "package_breast_ihc_patch_release",
    PACKAGE_SCRIPT,
)
assert PACKAGE_SPEC is not None and PACKAGE_SPEC.loader is not None
package = importlib.util.module_from_spec(PACKAGE_SPEC)
sys.modules[PACKAGE_SPEC.name] = package
PACKAGE_SPEC.loader.exec_module(package)


def write_secret(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(hashlib.sha256(b"synthetic packaging test secret").digest())
    path.chmod(0o600)
    return path


def write_private_tiff(
    path: Path,
    seed: int,
    case_id: str,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pixels = (
        np.arange(10 * 14 * 3, dtype=np.uint16).reshape(10, 14, 3) + seed
    ).astype(np.uint8)
    tifffile.imwrite(
        path,
        pixels,
        photometric="rgb",
        description=rf"C:\Users\Student\2026.07.09\{case_id}",
        software="Private acquisition software",
        datetime="2026:07:09 01:02:03",
    )
    return path


def write_selection(path: Path, rows: list[dict[str, object]]) -> Path:
    columns = (
        "case_id",
        "marker",
        "field_id",
        "source_path",
        "include",
        "microns_per_pixel",
        "mpp_provenance",
        "private_batch_date",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def make_completed_draft(tmp_path: Path) -> dict[str, object]:
    case_a = "PRIVATE-A-001"
    case_b = "PRIVATE-B-002"
    source_root = tmp_path / "private-source"
    selections = [
        {
            "case_id": case_a,
            "marker": "RE",
            "field_id": "field-a-er",
            "source_path": write_private_tiff(
                source_root / "case-a-er.tif",
                1,
                case_a,
            ),
            "include": "true",
            "microns_per_pixel": "0.25",
            "mpp_provenance": "measured_red_bar_10x;binning_3x",
            "private_batch_date": "2026-07-09",
        },
        {
            "case_id": case_a,
            "marker": "Ki67",
            "field_id": "field-a-ki67",
            "source_path": write_private_tiff(
                source_root / "case-a-ki67.tif",
                2,
                case_a,
            ),
            "include": "true",
            "microns_per_pixel": "1.0",
            "mpp_provenance": (
                "extrapolated_from_measured_10x_red_bar;binning_1x"
            ),
            "private_batch_date": "2026-07-09",
        },
        {
            "case_id": case_b,
            "marker": "H&E",
            "field_id": "field-b-he",
            "source_path": write_private_tiff(
                source_root / "case-b-he.tif",
                3,
                case_b,
            ),
            "include": "true",
            "microns_per_pixel": "2.5",
            "mpp_provenance": "externally verified",
            "private_batch_date": "2026-07-09",
        },
    ]
    selection = write_selection(tmp_path / "private-selection.csv", selections)
    secret = write_secret(tmp_path / "private" / "alias.key")
    draft = tmp_path / "sanitized-draft"
    linkage = tmp_path / "private" / "linkage.csv"
    prepare.prepare_release(
        source_manifest=selection,
        secret_file=secret,
        public_output=draft,
        private_linkage=linkage,
        expected_cases=2,
        expected_files=3,
    )
    with (draft / prepare.PATCH_MANIFEST).open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        public_rows = list(csv.DictReader(handle))
    return {
        "draft": draft,
        "linkage": linkage,
        "case_ids": (case_a, case_b),
        "rows": public_rows,
        "output": tmp_path / "zenodo-package",
    }


def run_package(
    inputs: dict[str, object],
    **overrides: object,
) -> dict[str, object]:
    arguments: dict[str, object] = {
        "source_draft": inputs["draft"],
        "package_output": inputs["output"],
        "expected_cases": 2,
        "expected_files": 3,
    }
    arguments.update(overrides)
    return package.package_release(**arguments)


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def rewrite_source_checksums(draft: Path) -> None:
    with (draft / prepare.PATCH_MANIFEST).open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        patch_rows = list(csv.DictReader(handle))
    payloads = sorted(
        [
            prepare.PATCH_MANIFEST,
            prepare.CASE_MARKER_COUNTS,
            prepare.VALIDATION_REPORT,
            *(row["public_path"] for row in patch_rows),
        ]
    )
    sha_lines: list[str] = []
    md5_lines: list[str] = []
    for relative in payloads:
        data = (draft / relative).read_bytes()
        sha_lines.append(f"{hashlib.sha256(data).hexdigest()}  {relative}\n")
        md5_lines.append(
            f"{hashlib.md5(data, usedforsecurity=False).hexdigest()}  {relative}\n"
        )
    (draft / prepare.SHA256SUMS).write_text("".join(sha_lines), encoding="utf-8")
    (draft / prepare.MD5SUMS).write_text("".join(md5_lines), encoding="utf-8")


def test_packages_exact_lossless_case_archives_and_metadata_bundle(
    tmp_path: Path,
) -> None:
    inputs = make_completed_draft(tmp_path)
    draft = Path(inputs["draft"])
    source_before = tree_bytes(draft)

    result = run_package(inputs)

    output = Path(inputs["output"])
    assert result["status"] == "packaged"
    assert result["source_retained"] is True
    assert result["case_archive_count"] == 2
    assert result["upload_file_count"] == 6
    assert result["upload_file_count"] <= package.MAX_ZENODO_UPLOAD_FILES
    assert result["archive_compression"] == "ZIP_STORED"
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert tree_bytes(draft) == source_before
    assert {row["mpp_provenance"] for row in inputs["rows"]} == {
        "measured_scale_bar_calibration_10x_binning_3x",
        (
            "documented_magnification_extrapolation_from_measured_10x_"
            "scale_bar_binning_1x"
        ),
        "externally_verified_calibration",
    }

    rows_by_case: dict[str, list[dict[str, str]]] = {}
    for row in inputs["rows"]:
        rows_by_case.setdefault(row["case_alias"], []).append(row)
    case_archives = sorted(output.glob("TQA_BC_*.zip"))
    assert [path.name for path in case_archives] == [
        f"{alias}.zip" for alias in sorted(rows_by_case)
    ]
    for archive_path in case_archives:
        case_alias = archive_path.stem
        expected_rows = {
            row["public_path"]: row for row in rows_by_case[case_alias]
        }
        local_header = archive_path.read_bytes()
        assert local_header[:4] == b"PK\x03\x04"
        assert int.from_bytes(local_header[4:6], "little") >= 45
        assert local_header[18:26] == b"\xff" * 8
        filename_length = int.from_bytes(local_header[26:28], "little")
        extra_length = int.from_bytes(local_header[28:30], "little")
        local_extra = local_header[
            30 + filename_length : 30 + filename_length + extra_length
        ]
        assert local_extra[:2] == b"\x01\x00"
        with ZipFile(archive_path) as archive:
            infos = archive.infolist()
            assert [info.filename for info in infos] == sorted(expected_rows)
            assert archive.testzip() is None
            for info in infos:
                assert info.extract_version >= 45
                assert info.date_time == package.FIXED_ZIP_DATETIME
                assert info.compress_type == ZIP_STORED
                assert info.create_system == 3
                assert stat.S_ISREG(info.external_attr >> 16)
                assert stat.S_IMODE(info.external_attr >> 16) == 0o644
                assert info.comment == b""
                extracted = archive.read(info)
                expected_row = expected_rows[info.filename]
                assert len(extracted) == int(expected_row["size_bytes"])
                assert hashlib.sha256(extracted).hexdigest() == expected_row["sha256"]
                assert extracted == (draft / info.filename).read_bytes()

    bundle = output / package.MANIFEST_BUNDLE
    with ZipFile(bundle) as archive:
        assert archive.namelist() == sorted(
            [*package.SOURCE_METADATA_FILES, package.ARCHIVE_MANIFEST]
        )
        assert archive.testzip() is None
        archive_manifest = archive.read(package.ARCHIVE_MANIFEST).decode("utf-8")
    assert all(archive.name in archive_manifest for archive in case_archives)

    report_text = (output / package.PACKAGING_REPORT).read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert report["source_retained"] is True
    assert report["archive_compression"] == "ZIP_STORED"
    assert "duplicates its TIFF bytes" in report["disk_tradeoff"]
    assert "/home/example-private" not in report_text
    for case_id in inputs["case_ids"]:
        assert case_id not in report_text

    sha256s = package.parse_checksum_file(
        output / package.UPLOAD_SHA256SUMS,
        "sha256",
    )
    md5s = package.parse_checksum_file(
        output / package.UPLOAD_MD5SUMS,
        "md5",
    )
    expected_checked = {
        *(archive.name for archive in case_archives),
        package.MANIFEST_BUNDLE,
        package.PACKAGING_REPORT,
    }
    assert set(sha256s) == expected_checked
    assert set(md5s) == expected_checked


def test_packaging_is_byte_deterministic_despite_source_mtime_and_mode(
    tmp_path: Path,
) -> None:
    inputs = make_completed_draft(tmp_path)
    run_package(inputs)
    first_output = Path(inputs["output"])
    first = tree_bytes(first_output)

    for source in Path(inputs["draft"]).rglob("*"):
        if source.is_file():
            source.chmod(0o600)
            os.utime(source, (1_700_000_000, 1_700_000_000))
    second_output = tmp_path / "second-package"
    run_package(inputs, package_output=second_output)

    assert tree_bytes(second_output) == first


def test_dry_run_validates_and_reports_retained_source_disk_estimate(
    tmp_path: Path,
) -> None:
    inputs = make_completed_draft(tmp_path)

    result = run_package(inputs, dry_run=True)

    assert result["status"] == "planned"
    assert result["source_retained"] is True
    assert result["case_count"] == 2
    assert result["patch_count"] == 3
    assert result["upload_file_count"] == 6
    assert result["estimated_additional_disk_bytes"] > result["source_tree_bytes"]
    assert not Path(inputs["output"]).exists()
    serialized = repr(result)
    assert str(inputs["draft"]) not in serialized
    for case_id in inputs["case_ids"]:
        assert case_id not in serialized


def test_rejects_tiff_checksum_mismatch_and_unexpected_file(tmp_path: Path) -> None:
    inputs = make_completed_draft(tmp_path)
    draft = Path(inputs["draft"])
    first_tiff = draft / inputs["rows"][0]["public_path"]
    with first_tiff.open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(package.PackagingError, match="digest does not match"):
        run_package(inputs, dry_run=True)
    assert not Path(inputs["output"]).exists()

    inputs = make_completed_draft(tmp_path / "extra")
    draft = Path(inputs["draft"])
    (draft / "private_linkage.csv").write_text(
        "case_id,source_path\nPRIVATE,/home/example-private\n",
        encoding="utf-8",
    )
    with pytest.raises(package.PackagingError, match="roster mismatch"):
        run_package(inputs, dry_run=True)
    assert not Path(inputs["output"]).exists()


def test_rejects_symlink_and_private_path_even_with_recomputed_checksums(
    tmp_path: Path,
) -> None:
    inputs = make_completed_draft(tmp_path)
    draft = Path(inputs["draft"])
    target = draft / inputs["rows"][0]["public_path"]
    symlink = target.parent / "unexpected-link.tif"
    symlink.symlink_to(target)
    with pytest.raises(package.PackagingError, match="Symlink"):
        run_package(inputs, dry_run=True)

    inputs = make_completed_draft(tmp_path / "privacy")
    draft = Path(inputs["draft"])
    report_path = draft / prepare.VALIDATION_REPORT
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["unsafe_note"] = (
        "/home/example-private/PRIVATE-CASE-A/2026-07-09"
    )
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    rewrite_source_checksums(draft)
    with pytest.raises(package.PackagingError, match="Private absolute path"):
        run_package(inputs, dry_run=True)


def test_rejects_unexpected_validation_report_key_with_phi_sentinel(
    tmp_path: Path,
) -> None:
    inputs = make_completed_draft(tmp_path)
    draft = Path(inputs["draft"])
    report_path = draft / prepare.VALIDATION_REPORT
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["patient_name"] = "PHI_SENTINEL_DO_NOT_RELEASE"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    rewrite_source_checksums(draft)

    with pytest.raises(package.PackagingError, match="unexpected keys: patient_name"):
        run_package(inputs, dry_run=True)


def test_rejects_post_preparation_tiff_metadata_even_if_checksums_are_rewritten(
    tmp_path: Path,
) -> None:
    inputs = make_completed_draft(tmp_path)
    draft = Path(inputs["draft"])
    manifest_path = draft / prepare.PATCH_MANIFEST
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        rows = list(reader)
    target_row = rows[0]
    target = draft / target_row["public_path"]
    with tifffile.TiffFile(target) as tif:
        pixels = tif.pages[0].asarray()
    mpp = float(target_row["microns_per_pixel"])
    tifffile.imwrite(
        target,
        pixels,
        photometric="rgb",
        description=r"C:\Users\Student\PRIVATE-CASE-A\2026-07-09",
        software="Private acquisition software",
        metadata=None,
        resolution=(10_000.0 / mpp, 10_000.0 / mpp),
        resolutionunit="CENTIMETER",
    )
    data = target.read_bytes()
    target_row["size_bytes"] = str(len(data))
    target_row["sha256"] = hashlib.sha256(data).hexdigest()
    target_row["md5"] = hashlib.md5(data, usedforsecurity=False).hexdigest()
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    rewrite_source_checksums(draft)

    with pytest.raises(package.PackagingError, match="non-allowlisted tags"):
        run_package(inputs, dry_run=True)
    assert not Path(inputs["output"]).exists()


def test_rejects_unsafe_mpp_provenance_even_with_recomputed_checksums(
    tmp_path: Path,
) -> None:
    inputs = make_completed_draft(tmp_path)
    draft = Path(inputs["draft"])
    manifest_path = draft / prepare.PATCH_MANIFEST
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        rows = list(reader)
    rows[0]["mpp_provenance"] = "student_guess"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    rewrite_source_checksums(draft)

    with pytest.raises(package.PackagingError, match="Unsafe mpp_provenance"):
        run_package(inputs, dry_run=True)


def test_recomputes_decoded_rgb_digest_before_packaging(tmp_path: Path) -> None:
    inputs = make_completed_draft(tmp_path)
    draft = Path(inputs["draft"])
    manifest_path = draft / prepare.PATCH_MANIFEST
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        rows = list(reader)
    target_row = rows[0]
    target = draft / target_row["public_path"]
    with tifffile.TiffFile(target) as tif:
        pixels = tif.pages[0].asarray()
    mutated = pixels.copy()
    mutated[0, 0, 0] ^= 1
    replacement = target.with_suffix(".replacement.tif")
    prepare.reencode_minimal_tiff(
        mutated,
        replacement,
        float(target_row["microns_per_pixel"]),
    )
    os.replace(replacement, target)
    data = target.read_bytes()
    target_row["size_bytes"] = str(len(data))
    target_row["sha256"] = hashlib.sha256(data).hexdigest()
    target_row["md5"] = hashlib.md5(data, usedforsecurity=False).hexdigest()
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    rewrite_source_checksums(draft)

    with pytest.raises(package.PackagingError, match="Decoded RGB digest"):
        run_package(inputs, dry_run=True)


def test_refuses_count_mismatch_existing_output_and_excess_upload_files(
    tmp_path: Path,
) -> None:
    inputs = make_completed_draft(tmp_path)
    with pytest.raises(package.PackagingError, match="Expected 4 sanitized TIFFs"):
        run_package(inputs, expected_files=4, dry_run=True)

    output = Path(inputs["output"])
    output.mkdir()
    sentinel = output / "belongs-to-user.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    with pytest.raises(package.PackagingError, match="already exists"):
        run_package(inputs, dry_run=True)
    assert sentinel.read_text(encoding="utf-8") == "keep\n"

    assert package.ensure_upload_file_limit(96) == 100
    with pytest.raises(package.PackagingError, match="101 upload files"):
        package.ensure_upload_file_limit(97)


def test_atomic_publish_refuses_target_created_immediately_before_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = make_completed_draft(tmp_path)
    output = Path(inputs["output"])
    original_publish = package.atomic_publish_directory_no_replace

    def create_competing_target(source: Path, destination: Path) -> None:
        destination.mkdir()
        (destination / "belongs-to-other-process.txt").write_text(
            "keep\n",
            encoding="utf-8",
        )
        original_publish(source, destination)

    monkeypatch.setattr(
        package,
        "atomic_publish_directory_no_replace",
        create_competing_target,
    )

    with pytest.raises(package.PackagingError, match="appeared before final"):
        run_package(inputs)

    assert {
        path.name for path in output.iterdir()
    } == {"belongs-to-other-process.txt"}
    assert (output / "belongs-to-other-process.txt").read_text(
        encoding="utf-8"
    ) == "keep\n"
    assert not any(
        path.name.startswith(f".{output.name}.package-")
        for path in output.parent.iterdir()
    )


def test_atomic_publish_has_fail_closed_portable_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staging = tmp_path / "staging"
    destination = tmp_path / "destination"
    staging.mkdir()
    sentinel = staging / "complete.txt"
    sentinel.write_text("complete\n", encoding="utf-8")
    monkeypatch.setattr(
        package,
        "linux_rename_directory_noreplace",
        lambda source, target: False,
    )

    with pytest.raises(package.PackagingError, match="refusing a non-atomic fallback"):
        package.atomic_publish_directory_no_replace(staging, destination)

    assert staging.is_dir()
    assert sentinel.read_text(encoding="utf-8") == "complete\n"
    assert not destination.exists()


def test_parser_exposes_no_network_upload_or_publish_operation() -> None:
    parser = package.build_parser()
    options = {option for action in parser._actions for option in action.option_strings}
    assert "--upload" not in options
    assert "--publish" not in options
    assert "--deposit-id" not in options
    assert "--token" not in options
    assert "--api-url" not in options
