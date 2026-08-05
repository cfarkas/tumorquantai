from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_repository_hygiene.py"
SPEC = importlib.util.spec_from_file_location("check_repository_hygiene", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
HYGIENE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HYGIENE)


def scan_paths(monkeypatch: pytest.MonkeyPatch, root: Path, paths: list[str]) -> list[str]:
    monkeypatch.setattr(HYGIENE, "ROOT", root)
    files = []
    for name in paths:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic-test-content\n")
        files.append(path)
    errors: list[str] = []
    HYGIENE.check_forbidden_artifacts(files, errors)
    return errors


def scan_text_path(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    relative: str,
    text: str,
) -> list[str]:
    monkeypatch.setattr(HYGIENE, "ROOT", root)
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    errors: list[str] = []
    HYGIENE.check_forbidden_artifacts([path], errors)
    return errors


def test_release_metadata_versions_are_aligned() -> None:
    errors: list[str] = []
    HYGIENE.check_metadata([], errors)
    assert errors == []


@pytest.mark.parametrize(
    "relative",
    [
        "renamed-run/sample-01/cell_types/class_counts.csv",
        "renamed-run/sample-01/cell_types/cell_type_coordinates.csv.gz",
        "renamed-run/sample-01/cell_types/cell_type_coordinates.npy",
        "renamed-run/sample-01/summary/run_metadata.json",
        "renamed-run/sample-01/summary/summary.json",
        "renamed-run/sample-01/overlays/zoom_overlay_celltypes.png",
        "renamed-run/sample-01/qc_patches/patch_000/overlay.png",
        "renamed-run/sample-01/paper_figures/celltype_counts_barplot.pdf",
        "renamed-run/sample-01/plotting_metadata/detected_cell_types.csv",
        "copied-results/celltype_counts_by_sample.csv",
        "copied-results/sample_aggregation_audit.csv",
        "copied-results/workflow_metadata/nextflow_trace_run.tsv",
        "copied-results/nextflow.log",
        "copied-results/analysis_cohort.csv",
        "copied-results/oof_predictions_averaged.csv",
        "copied-results/run_manifest.json",
    ],
)
def test_rejects_actual_patient_output_layout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, relative: str
) -> None:
    errors = scan_paths(monkeypatch, tmp_path, [relative])
    assert errors, relative
    assert any(relative in error for error in errors)


def test_only_literal_synthetic_assets_are_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    allowed = sorted(path.as_posix() for path in HYGIENE.ALLOWED_SYNTHETIC_ASSETS)
    assert scan_paths(monkeypatch, tmp_path, allowed) == []

    invented = "tests/fixtures/not-an-approved-slide/secret_L0_rgb.tif"
    errors = scan_paths(monkeypatch, tmp_path, [invented])
    assert any("forbidden WSI/tutorial data" in error for error in errors)


def test_output_named_like_documentation_asset_is_not_broadly_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    invented = "docs/assets/zoom_overlay_celltypes.png"
    errors = scan_paths(monkeypatch, tmp_path, [invented])
    assert any("generated patient/workflow output" in error for error in errors)


def test_server_specific_path_is_rejected_in_production_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    errors = scan_text_path(
        monkeypatch,
        tmp_path,
        "scripts/run_analysis.py",
        "input_root = '/media/server/private-cohort'\n",
    )
    assert any("server-specific absolute path" in error for error in errors)


@pytest.mark.parametrize(
    "relative",
    ["tests/test_private_path_fixture.py", "scripts/check_docs_language.py"],
)
def test_local_path_pattern_literals_are_narrowly_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, relative: str
) -> None:
    assert scan_text_path(
        monkeypatch,
        tmp_path,
        relative,
        "pattern = r'/home/server/'\n",
    ) == []
