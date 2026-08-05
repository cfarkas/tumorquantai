from __future__ import annotations

import csv
import importlib.util
import os
import stat
import sys
from pathlib import Path

import numpy as np
import pytest
import tifffile


SCRIPT = Path(__file__).parents[1] / "bin" / "prepare_breast_ihc_patch_release.py"
SPEC = importlib.util.spec_from_file_location(
    "prepare_breast_ihc_patch_release", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
prepare = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = prepare
SPEC.loader.exec_module(prepare)

CORE_SCRIPT = Path(__file__).parents[1] / "bin" / "tumorquantai_core.py"
CORE_SPEC = importlib.util.spec_from_file_location("breast_release_test_core", CORE_SCRIPT)
assert CORE_SPEC is not None and CORE_SPEC.loader is not None
core = importlib.util.module_from_spec(CORE_SPEC)
sys.modules[CORE_SPEC.name] = core
CORE_SPEC.loader.exec_module(core)


def write_secret(path: Path, byte: bytes = b"s") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(byte * 32)
    path.chmod(0o600)
    return path


def write_private_tiff(path: Path, pixels: np.ndarray, case_id: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(
        path,
        pixels,
        photometric="rgb",
        description=(
            rf"C:\Users\Student\Desktop\2026.07.09\{case_id}; "
            "camera serial PRIVATE-SERIAL"
        ),
        software="Private Nikon workflow",
        datetime="2026:07:09 11:12:13",
    )
    return path


def write_manifest(path: Path, rows: list[dict[str, object]]) -> Path:
    columns = (
        "case_id",
        "marker",
        "field_id",
        "source_path",
        "include",
        "microns_per_pixel",
        "mpp_provenance",
        "private_batch_date",
        "absolute_results_path",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def release_inputs(tmp_path: Path) -> dict[str, object]:
    case_id = "PRIVATE-CASE-A"
    pixels_a = np.arange(9 * 13 * 3, dtype=np.uint8).reshape(9, 13, 3)
    pixels_b = np.flip(pixels_a, axis=1).copy()
    first = write_private_tiff(
        tmp_path / "private-source" / f"{case_id}_RE_field-01.tif",
        pixels_a,
        case_id,
    )
    second = write_private_tiff(
        tmp_path / "private-source" / f"{case_id}_Ki67_field-02.tif",
        pixels_b,
        case_id,
    )
    manifest = write_manifest(
        tmp_path / "private-selection.csv",
        [
            {
                "case_id": case_id,
                "marker": "RE",
                "field_id": "field-01",
                "source_path": first,
                "include": "true",
                "microns_per_pixel": "0.25",
                "mpp_provenance": "measured_red_bar_10x;binning_1x",
                "private_batch_date": "2026-07-09",
                "absolute_results_path": "/home/example-private/results",
            },
            {
                "case_id": case_id,
                "marker": "Ki67",
                "field_id": "field-02",
                "source_path": second,
                "include": "true",
                "microns_per_pixel": "2.5",
                "mpp_provenance": (
                    "extrapolated_from_measured_10x_red_bar;binning_1x"
                ),
                "private_batch_date": "2026-07-09",
                "absolute_results_path": "/home/example-private/results",
            },
        ],
    )
    return {
        "case_id": case_id,
        "pixels": [pixels_a, pixels_b],
        "manifest": manifest,
        "secret": write_secret(tmp_path / "private" / "alias.key"),
        "output": tmp_path / "draft",
        "linkage": tmp_path / "private" / "linkage.csv",
    }


def run_release(inputs: dict[str, object], **overrides: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "source_manifest": inputs["manifest"],
        "secret_file": inputs["secret"],
        "public_output": inputs["output"],
        "private_linkage": inputs["linkage"],
        "expected_cases": 1,
        "expected_files": 2,
    }
    arguments.update(overrides)
    return prepare.prepare_release(**arguments)


def test_reencodes_exact_pixels_and_keeps_private_values_only_in_linkage(
    tmp_path: Path,
) -> None:
    inputs = release_inputs(tmp_path)

    result = run_release(inputs)

    output = Path(inputs["output"])
    linkage = Path(inputs["linkage"])
    assert result["status"] == "prepared"
    assert result["draft_only"] is True
    assert result["network_used"] is False
    assert result["upload_performed"] is False
    assert result["publication_performed"] is False
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert stat.S_IMODE(linkage.stat().st_mode) == 0o600

    with (output / prepare.PATCH_MANIFEST).open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        public_rows = list(csv.DictReader(handle))
    assert len(public_rows) == 2
    assert {row["marker"] for row in public_rows} == {"ER", "Ki-67"}
    assert {row["mpp_provenance"] for row in public_rows} == {
        "measured_scale_bar_calibration_10x_binning_1x",
        (
            "documented_magnification_extrapolation_from_measured_10x_"
            "scale_bar_binning_1x"
        ),
    }
    assert all(prepare.CASE_ALIAS_RE.fullmatch(row["case_alias"]) for row in public_rows)
    assert all(prepare.PATCH_ALIAS_RE.fullmatch(row["patch_alias"]) for row in public_rows)
    assert len({row["patch_alias"] for row in public_rows}) == 2

    source_by_marker = {
        "ER": (inputs["pixels"][0], 0.25),
        "Ki-67": (inputs["pixels"][1], 2.5),
    }
    for row in public_rows:
        public_tiff = output / row["public_path"]
        with tifffile.TiffFile(public_tiff) as tif:
            tags = {str(tag.name) for tag in tif.pages[0].tags.values()}
            decoded = tif.pages[0].asarray()
            embedded_mpp = prepare.page_microns_per_pixel(tif.pages[0])
        assert tags <= prepare.ALLOWED_OUTPUT_TIFF_TAGS
        assert "ImageDescription" not in tags
        assert "Software" not in tags
        assert "DateTime" not in tags
        expected_pixels, expected_mpp = source_by_marker[row["marker"]]
        assert np.array_equal(decoded, expected_pixels)
        assert float(row["microns_per_pixel"]) == expected_mpp
        assert embedded_mpp == pytest.approx(
            (expected_mpp, expected_mpp),
            rel=prepare.MPP_RELATIVE_TOLERANCE,
            abs=prepare.MPP_ABSOLUTE_TOLERANCE,
        )
        patch_metadata = core._read_tiff_metadata(public_tiff)
        assert patch_metadata["source_mpp"] == pytest.approx(
            expected_mpp,
            rel=prepare.MPP_RELATIVE_TOLERANCE,
            abs=prepare.MPP_ABSOLUTE_TOLERANCE,
        )
        assert prepare.decoded_rgb_sha256(np.ascontiguousarray(decoded)) == row[
            "decoded_rgb_sha256"
        ]

    public_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in output.iterdir()
        if path.is_file()
    )
    assert inputs["case_id"] not in public_text
    assert "2026-07-09" not in public_text
    assert "/home/example-private" not in public_text
    assert "field-01" not in public_text
    linkage_text = linkage.read_text(encoding="utf-8")
    assert inputs["case_id"] in linkage_text
    assert "field-01" in linkage_text
    assert str(tmp_path / "private-source") in linkage_text
    assert "measured_red_bar_10x;binning_1x" in linkage_text
    assert "measured_scale_bar_calibration_10x_binning_1x" in linkage_text
    report = (output / prepare.VALIDATION_REPORT).read_text(encoding="utf-8")
    assert "ResolutionUnit=centimeter" in report


def test_public_tree_and_checksums_are_deterministic(tmp_path: Path) -> None:
    first_inputs = release_inputs(tmp_path)
    run_release(first_inputs)
    first_output = Path(first_inputs["output"])
    first_bytes = {
        path.relative_to(first_output).as_posix(): path.read_bytes()
        for path in first_output.rglob("*")
        if path.is_file()
    }

    second_output = tmp_path / "second-draft"
    second_linkage = tmp_path / "private" / "second-linkage.csv"
    run_release(
        first_inputs,
        public_output=second_output,
        private_linkage=second_linkage,
    )
    second_bytes = {
        path.relative_to(second_output).as_posix(): path.read_bytes()
        for path in second_output.rglob("*")
        if path.is_file()
    }

    assert second_bytes == first_bytes
    sums = (first_output / prepare.SHA256SUMS).read_text(encoding="utf-8")
    assert "patch_manifest.csv" in sums
    assert "case_marker_counts.csv" in sums
    assert "validation_report.json" in sums
    assert "patches/" in sums
    assert prepare.SHA256SUMS not in sums


def test_different_secret_changes_every_public_alias(tmp_path: Path) -> None:
    inputs = release_inputs(tmp_path)
    first = prepare.make_plan(
        Path(inputs["manifest"]),
        Path(inputs["secret"]),
        Path(inputs["output"]),
        Path(inputs["linkage"]),
        expected_cases=1,
        expected_files=2,
    )
    other_secret = write_secret(tmp_path / "other-private" / "alias.key", b"z")
    second = prepare.make_plan(
        Path(inputs["manifest"]),
        other_secret,
        tmp_path / "other-draft",
        tmp_path / "other-private" / "linkage.csv",
        expected_cases=1,
        expected_files=2,
    )

    assert {item.case_alias for item in first.patches}.isdisjoint(
        {item.case_alias for item in second.patches}
    )
    assert {item.patch_alias for item in first.patches}.isdisjoint(
        {item.patch_alias for item in second.patches}
    )


def test_dry_run_validates_but_writes_nothing_and_returns_no_private_values(
    tmp_path: Path,
) -> None:
    inputs = release_inputs(tmp_path)

    result = run_release(inputs, dry_run=True)

    assert result["status"] == "planned"
    assert result["case_count"] == 1
    assert result["patch_count"] == 2
    assert result["marker_patch_counts"]["ER"] == 1
    assert not Path(inputs["output"]).exists()
    assert not Path(inputs["linkage"]).exists()
    serialized = repr(result)
    assert str(inputs["case_id"]) not in serialized
    assert str(inputs["manifest"]) not in serialized
    assert str(inputs["secret"]) not in serialized


def test_fails_closed_for_insecure_or_mislocated_secret(tmp_path: Path) -> None:
    inputs = release_inputs(tmp_path)
    secret = Path(inputs["secret"])
    secret.chmod(0o640)
    with pytest.raises(prepare.PreparationError, match="exact mode 0600"):
        run_release(inputs, dry_run=True)

    secret.chmod(0o600)
    output = tmp_path / "contains-secret"
    inside_secret = write_secret(output / "alias.key")
    with pytest.raises(prepare.PreparationError, match="outside both"):
        run_release(
            inputs,
            secret_file=inside_secret,
            public_output=output,
            dry_run=True,
        )


def test_fails_closed_for_counts_unknown_marker_and_multipage_tiff(
    tmp_path: Path,
) -> None:
    inputs = release_inputs(tmp_path)
    with pytest.raises(prepare.PreparationError, match="Expected 3 included TIFFs"):
        run_release(inputs, expected_files=3, dry_run=True)

    manifest = Path(inputs["manifest"])
    rows = list(csv.DictReader(manifest.open("r", encoding="utf-8", newline="")))
    rows[0]["marker"] = "ambiguous stain"
    write_manifest(manifest, rows)
    with pytest.raises(prepare.PreparationError, match="Unknown marker"):
        run_release(inputs, dry_run=True)

    inputs = release_inputs(tmp_path / "multipage")
    rows = list(
        csv.DictReader(
            Path(inputs["manifest"]).open("r", encoding="utf-8", newline="")
        )
    )
    multipage = Path(rows[0]["source_path"])
    pixels = np.zeros((9, 13, 3), dtype=np.uint8)
    with tifffile.TiffWriter(multipage) as writer:
        writer.write(pixels, photometric="rgb")
        writer.write(pixels, photometric="rgb")
    with pytest.raises(prepare.PreparationError, match="exactly one page"):
        run_release(inputs, dry_run=True)


def test_rejects_nondefault_source_tiff_orientation(tmp_path: Path) -> None:
    inputs = release_inputs(tmp_path)
    with Path(inputs["manifest"]).open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    source = Path(rows[0]["source_path"])
    tifffile.imwrite(
        source,
        inputs["pixels"][0],
        photometric="rgb",
        metadata=None,
        extratags=[(274, "H", 1, 6, False)],
    )
    with tifffile.TiffFile(source) as tif:
        assert int(tif.pages[0].tags["Orientation"].value) == 6

    with pytest.raises(prepare.PreparationError, match="Orientation must be 1"):
        run_release(inputs, dry_run=True)


@pytest.mark.parametrize(
    ("source_value", "expected"),
    [
        (
            "measured_red_bar_10x;binning_1x",
            "measured_scale_bar_calibration_10x_binning_1x",
        ),
        (
            "measured_red_bar_10x;binning_3x",
            "measured_scale_bar_calibration_10x_binning_3x",
        ),
        (
            "extrapolated_from_measured_10x_red_bar;binning_1x",
            (
                "documented_magnification_extrapolation_from_measured_10x_"
                "scale_bar_binning_1x"
            ),
        ),
        (
            "measured_red_bar_40x;binning_3x",
            "measured_scale_bar_calibration_40x_binning_3x",
        ),
    ],
)
def test_canonicalizes_cohort_mpp_provenance_values(
    source_value: str,
    expected: str,
) -> None:
    assert prepare.normalize_mpp_provenance(source_value, 2) == expected


def test_missing_mpp_provenance_column_fails_closed(tmp_path: Path) -> None:
    inputs = release_inputs(tmp_path)
    manifest = Path(inputs["manifest"])
    with manifest.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    columns = tuple(
        column
        for column in rows[0]
        if column != "mpp_provenance"
    )
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=columns,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(prepare.PreparationError, match="mpp_provenance"):
        run_release(inputs, dry_run=True)


def test_unknown_or_unsafe_mpp_provenance_fails_closed(tmp_path: Path) -> None:
    inputs = release_inputs(tmp_path)
    manifest = Path(inputs["manifest"])
    with manifest.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["mpp_provenance"] = "/home/example-private/student guess"
    write_manifest(manifest, rows)

    with pytest.raises(prepare.PreparationError, match="unsafe mpp_provenance"):
        run_release(inputs, dry_run=True)


def test_external_mpp_overrides_disagreeing_source_resolution_tags(
    tmp_path: Path,
) -> None:
    inputs = release_inputs(tmp_path)
    manifest = Path(inputs["manifest"])
    with manifest.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["mpp_provenance"] = "externally verified"
    source = Path(rows[0]["source_path"])
    tifffile.imwrite(
        source,
        inputs["pixels"][0],
        photometric="rgb",
        metadata=None,
        resolution=(72, 72),
        resolutionunit="INCH",
    )
    write_manifest(manifest, rows)

    run_release(inputs)

    with (Path(inputs["output"]) / prepare.PATCH_MANIFEST).open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        public_rows = list(csv.DictReader(handle))
    er_row = next(row for row in public_rows if row["marker"] == "ER")
    assert float(er_row["microns_per_pixel"]) == 0.25
    assert er_row["mpp_provenance"] == "externally_verified_calibration"
    with tifffile.TiffFile(Path(inputs["output"]) / er_row["public_path"]) as tif:
        assert prepare.page_microns_per_pixel(tif.pages[0]) == pytest.approx(
            (0.25, 0.25),
            rel=prepare.MPP_RELATIVE_TOLERANCE,
            abs=prepare.MPP_ABSOLUTE_TOLERANCE,
        )


def test_source_header_inspection_never_accesses_ome_series(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = write_private_tiff(
        tmp_path / "private-source.tif",
        np.zeros((7, 11, 3), dtype=np.uint8),
        "PRIVATE-CASE-A",
    )

    class ForbiddenSeries:
        def __get__(self, instance: object, owner: object) -> object:
            raise AssertionError("source OME series parsing must not run")

    monkeypatch.setattr(tifffile.TiffFile, "series", ForbiddenSeries())

    height, width, dtype, estimated_bytes = prepare.inspect_rgb_tiff(source)

    assert (height, width) == (7, 11)
    assert np.dtype(dtype) == np.dtype("uint8")
    assert estimated_bytes == 7 * 11 * 3


@pytest.mark.parametrize("microns_per_pixel", [0.25, 1.0, 2.5])
def test_embedded_scale_round_trips_for_40x_10x_and_4x_patches(
    tmp_path: Path,
    microns_per_pixel: float,
) -> None:
    output = tmp_path / f"scale-{microns_per_pixel:g}.tif"
    pixels = np.arange(8 * 12 * 3, dtype=np.uint8).reshape(8, 12, 3)

    prepare.reencode_minimal_tiff(pixels, output, microns_per_pixel)

    embedded = prepare.validate_minimal_tiff(output, microns_per_pixel)
    metadata = core._read_tiff_metadata(output)
    assert embedded == pytest.approx(
        (microns_per_pixel, microns_per_pixel),
        rel=prepare.MPP_RELATIVE_TOLERANCE,
        abs=prepare.MPP_ABSOLUTE_TOLERANCE,
    )
    assert metadata["source_mpp"] == pytest.approx(
        microns_per_pixel,
        rel=prepare.MPP_RELATIVE_TOLERANCE,
        abs=prepare.MPP_ABSOLUTE_TOLERANCE,
    )


def test_public_commit_failure_rolls_back_owned_private_linkage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = release_inputs(tmp_path)
    output = Path(inputs["output"]).resolve()
    linkage = Path(inputs["linkage"]).resolve()
    original_publish = prepare.atomic_publish_no_replace

    def fail_public_commit(source: Path, destination: Path) -> None:
        if destination == output:
            raise prepare.PreparationError("synthetic public commit failure")
        original_publish(source, destination)

    monkeypatch.setattr(
        prepare,
        "atomic_publish_no_replace",
        fail_public_commit,
    )

    with pytest.raises(prepare.PreparationError, match="synthetic public commit"):
        run_release(inputs)

    assert not output.exists()
    assert not linkage.exists()
    assert not any(
        path.name.startswith(f".{output.name}.draft-")
        for path in output.parent.iterdir()
    )
    assert not any(
        path.name.startswith(f".{linkage.name}.")
        for path in linkage.parent.iterdir()
    )


def test_parser_exposes_no_upload_or_publish_operation() -> None:
    parser = prepare.build_parser()
    options = {option for action in parser._actions for option in action.option_strings}
    assert "--upload" not in options
    assert "--publish" not in options
    assert "--deposit-id" not in options
    assert "--token" not in options
