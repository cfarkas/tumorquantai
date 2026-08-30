from __future__ import annotations

import csv
import io
import json
import math
import stat
import zipfile
from pathlib import Path

import numpy as np
import openpyxl
import pytest
import tifffile

from tumorquantai_cli import ihc


def write_csv(
    path: Path, fields: list[str] | tuple[str, ...], rows: list[dict[str, object]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_cohen_kappa_handles_perfect_opposite_and_quadratic_scales() -> None:
    perfect, perfect_table = ihc.cohen_kappa([0, 0, 1, 1], [0, 0, 1, 1], [0, 1])
    opposite, opposite_table = ihc.cohen_kappa([0, 0, 1, 1], [1, 1, 0, 0], [0, 1])
    weighted, weighted_table = ihc.cohen_kappa(
        [0, 1, 2, 3], [0, 1, 2, 3], [0, 1, 2, 3], weights="quadratic"
    )

    assert perfect == pytest.approx(1.0)
    assert opposite == pytest.approx(-1.0)
    assert weighted == pytest.approx(1.0)
    assert perfect_table.tolist() == [[2, 0], [0, 2]]
    assert opposite_table.tolist() == [[0, 2], [2, 0]]
    assert weighted_table.trace() == 4


def test_direct_case_archive_loading_verifies_domain_separated_pixels(
    tmp_path: Path,
) -> None:
    case_alias = "TQA_BC_AAAAAAAAAAAAAAAAAAAA"
    patch_alias = "TQA_PATCH_BBBBBBBBBBBBBBBBBBBB"
    public_path = f"patches/{case_alias}/{patch_alias}_ER.tif"
    rgb = np.full((12, 18, 3), 245, dtype=np.uint8)
    rgb[3:9, 5:13] = (91, 55, 30)
    payload = io.BytesIO()
    tifffile.imwrite(payload, rgb, photometric="rgb")

    archive = tmp_path / f"{case_alias}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as handle:
        handle.writestr(public_path, payload.getvalue())

    manifest = tmp_path / "patch_manifest.csv"
    write_csv(
        manifest,
        [
            "case_alias",
            "patch_alias",
            "marker",
            "public_path",
            "microns_per_pixel",
            "width",
            "height",
            "decoded_rgb_sha256",
        ],
        [
            {
                "case_alias": case_alias,
                "patch_alias": patch_alias,
                "marker": "ER",
                "public_path": public_path,
                "microns_per_pixel": 0.5,
                "width": 18,
                "height": 12,
                "decoded_rgb_sha256": ihc.decoded_rgb_sha256(rgb),
            }
        ],
    )

    records, unavailable = ihc.load_patch_manifest(manifest, tmp_path)
    assert unavailable == []
    assert len(records) == 1
    decoded = ihc.load_patch_rgb(records[0])
    assert np.array_equal(decoded, rgb)
    assert ihc.decoded_rgb_sha256(decoded) == records[0].expected_decoded_rgb_sha256


def test_qc_overlay_accepts_vector_cell_classes(tmp_path: Path) -> None:
    labels = np.zeros((64, 80), dtype=np.int32)
    labels[8:23, 8:23] = 1
    labels[31:51, 45:66] = 2
    nuclei = ihc.SegmentedNuclei(
        labels=labels,
        label_ids=np.asarray([1, 2], dtype=np.int32),
        centroid_y=np.asarray([15.0, 40.5]),
        centroid_x=np.asarray([15.0, 55.0]),
        area_um2=np.asarray([56.25, 105.0]),
        mean_hematoxylin_od=np.asarray([0.4, 0.5]),
        mean_dab_od=np.asarray([0.1, 0.7]),
        nuclear_threshold_od=0.2,
    )
    rgb = np.full((64, 80, 3), 235, dtype=np.uint8)
    output = tmp_path / "qc_overlay.png"

    ihc.write_qc_overlay(
        output,
        rgb,
        nuclei,
        np.asarray([0, 3], dtype=np.uint8),
        "ER",
        "synthetic regression fixture",
    )

    assert output.is_file()
    assert output.stat().st_size > 100
    from PIL import Image

    with Image.open(output) as image:
        assert image.mode == "RGB"
        assert image.size == (80, 64)


def test_color_checked_dab_rejects_magenta_and_gray_but_retains_brown() -> None:
    rgb = np.asarray(
        [
            [
                [130, 75, 35],  # brown DAB-like color
                [210, 135, 165],  # magenta/pink
                [150, 150, 150],  # neutral gray
            ]
        ],
        dtype=np.uint8,
    )

    hematoxylin, unconstrained, color_checked = (
        ihc.separate_hematoxylin_dab_color_checked(
            rgb,
            minimum_color_margin_od=0.02,
            minimum_color_ratio=0.15,
        )
    )

    assert hematoxylin.shape == (1, 3)
    assert np.all(unconstrained[0] > 0.2)
    assert color_checked[0, 0] > 0.2
    assert color_checked[0, 1] == 0
    assert color_checked[0, 2] == 0


def test_dab_color_check_is_versioned_and_can_be_disabled() -> None:
    checked = ihc.IHCConfig()
    legacy = ihc.IHCConfig(constrain_dab_to_expected_color=False)

    assert checked.signature() != legacy.signature()
    assert ihc.IHC_SCHEMA_VERSION == "tumorquantai_ihc_v2"
    assert "color-checked" in ihc.IHC_ENGINE_VERSION


def test_pathologist_export_keeps_only_public_alias_and_marker_values(
    tmp_path: Path,
) -> None:
    workbook = tmp_path / "private_clinical.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Biopsias finales incluidas"
    headers = [
        "Número de paciente",
        "Biopsia",
        "Nombre de Paciente",
        "RUT Paciente",
        *ihc.DEFAULT_CLINICAL_COLUMNS.values(),
    ]
    sheet.append(headers)
    sheet.append(
        [1, "PRIVATE_BIOPSY_1", "SYNTHETIC_NAME_1", "SYNTHETIC_ID_1", 0, 10, 1, 0, 15]
    )
    sheet.append(
        [2, "PRIVATE_BIOPSY_2", "SYNTHETIC_NAME_2", "SYNTHETIC_ID_2", 95, 80, 3, 2, 70]
    )
    book.save(workbook)

    linkage = tmp_path / "private_linkage.csv"
    aliases = [
        "TQA_BC_CCCCCCCCCCCCCCCCCCCC",
        "TQA_BC_DDDDDDDDDDDDDDDDDDDD",
    ]
    write_csv(
        linkage,
        ["case_alias", "case_id"],
        [
            {"case_alias": aliases[0], "case_id": 1},
            {"case_alias": aliases[1], "case_id": 2},
        ],
    )
    output = tmp_path / "pathologist_markers_pseudonymized.csv"

    result = ihc.export_pathologist_csv(
        workbook,
        linkage,
        output,
        clinical_id_column="Número de paciente",
        linkage_id_column="case_id",
    )

    with output.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        assert tuple(reader.fieldnames or ()) == ihc.PATHOLOGIST_FIELDS
    serialized = output.read_text(encoding="utf-8")
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert [row["case_alias"] for row in rows] == aliases
    assert "SYNTHETIC_NAME" not in serialized
    assert "SYNTHETIC_ID" not in serialized
    assert "PRIVATE_BIOPSY" not in serialized
    assert result["privacy_status"] == "pseudonymized_minimum_marker_table"
    provenance = json.loads(
        output.with_suffix(".csv.provenance.json").read_text(encoding="utf-8")
    )
    assert (
        stat.S_IMODE(output.with_suffix(".csv.provenance.json").stat().st_mode) == 0o600
    )
    assert provenance["rows"] == 2
    assert "names" in provenance["excluded_data"]


def test_pathologist_export_accepts_only_explicit_private_id_crosswalk(
    tmp_path: Path,
) -> None:
    workbook = tmp_path / "private_clinical.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Biopsias finales incluidas"
    sheet.append(["Biopsia", *ihc.DEFAULT_CLINICAL_COLUMNS.values()])
    sheet.append(["CLINICAL_CASE_1", 10, 20, 1, 0, 30])
    book.save(workbook)

    alias = "TQA_BC_IIIIIIIIIIIIIIIIIIII"
    linkage = tmp_path / "private_linkage.csv"
    write_csv(
        linkage,
        ["case_alias", "case_id"],
        [{"case_alias": alias, "case_id": "LINKAGE_CASE_1"}],
    )
    crosswalk = tmp_path / "private_crosswalk.csv"
    write_csv(
        crosswalk,
        ihc.IDENTIFIER_CROSSWALK_FIELDS,
        [{"linkage_id": "LINKAGE_CASE_1", "clinical_id": "CLINICAL_CASE_1"}],
    )
    crosswalk.chmod(0o600)
    output = tmp_path / "pathologist.csv"

    result = ihc.export_pathologist_csv(
        workbook,
        linkage,
        output,
        clinical_id_column="Biopsia",
        linkage_id_column="case_id",
        identifier_crosswalk=crosswalk,
    )

    assert result["identifier_crosswalk_used"] is True
    assert result["identifier_crosswalk_rows"] == 1
    assert result["marker_values_used_for_linkage"] is False
    assert "LINKAGE_CASE_1" not in output.read_text(encoding="utf-8")
    assert "CLINICAL_CASE_1" not in output.read_text(encoding="utf-8")


def test_agreement_report_writes_marker_wise_kappa_and_contingencies(
    tmp_path: Path,
) -> None:
    results = tmp_path / "results"
    aliases = [
        "TQA_BC_EEEEEEEEEEEEEEEEEEEE",
        "TQA_BC_FFFFFFFFFFFFFFFFFFFF",
        "TQA_BC_GGGGGGGGGGGGGGGGGGGG",
        "TQA_BC_HHHHHHHHHHHHHHHHHHHH",
    ]
    algorithm_rows: list[dict[str, object]] = []
    predicted = {
        "ER": [0, 75, 0, 90],
        "PR": [0, 20, 0, 80],
        "HER2": [0, 1, 2, 3],
        "Ki-67": [5, 25, 55, 95],
    }
    for marker, values in predicted.items():
        for alias, value in zip(aliases, values):
            algorithm_rows.append(
                {
                    "case_alias": alias,
                    "marker": marker,
                    "marker_pre_score": value,
                    "unconstrained_dab_positive_percent": value,
                }
            )
    write_csv(
        results / "tables/case_marker_measurements.csv",
        [
            "case_alias",
            "marker",
            "marker_pre_score",
            "unconstrained_dab_positive_percent",
        ],
        algorithm_rows,
    )
    pathologist = tmp_path / "pathologist.csv"
    write_csv(
        pathologist,
        ihc.PATHOLOGIST_FIELDS,
        [
            {
                "case_alias": alias,
                "pathologist_er_percent": predicted["ER"][index],
                "pathologist_pr_percent": predicted["PR"][index],
                "pathologist_her2_ihc_score": predicted["HER2"][index],
                "pathologist_her2_fish": 0,
                "pathologist_ki67_percent": predicted["Ki-67"][index],
            }
            for index, alias in enumerate(aliases)
        ],
    )

    result = ihc.compare_pathologist_agreement(
        results,
        pathologist,
        results / "agreement",
        bootstrap_iterations=0,
    )

    summary = {
        (row["marker"], row["primary_scale"]): row for row in result["summaries"]
    }
    assert summary[("ER", "binary-at-1-percent")]["kappa"] == pytest.approx(1.0)
    assert summary[("PR", "binary-at-1-percent")]["kappa"] == pytest.approx(1.0)
    assert summary[("HER2", "ordinal-0-to-3")]["kappa"] == pytest.approx(1.0)
    assert summary[("Ki-67", "percentage-deciles")]["kappa"] == pytest.approx(1.0)
    assert summary[("Ki-67", "secondary-binary-at-20-percent")][
        "kappa"
    ] == pytest.approx(1.0)
    for key in (
        ("ER", "binary-at-1-percent"),
        ("PR", "binary-at-1-percent"),
        ("HER2", "ordinal-0-to-3"),
        ("Ki-67", "percentage-deciles"),
    ):
        assert summary[key]["root_mean_squared_error"] == pytest.approx(0.0)
        assert summary[key]["spearman_correlation"] == pytest.approx(1.0)
        assert summary[key]["lin_concordance_correlation"] == pytest.approx(1.0)
    assert result["schema_version"] == "tumorquantai_ihc_agreement_v2"
    assert result["case_rows"] == 4
    report = results / "agreement/AGREEMENT_REPORT.html"
    assert report.is_file()
    assert stat.S_IMODE(report.parent.stat().st_mode) == 0o700
    report_html = report.read_text(encoding="utf-8")
    assert "Agreement at a glance" in report_html
    assert "Contingency matrices" in report_html
    assert "Full concordance metrics CSV" in report_html
    assert "Analysis identity" in report_html
    impact_path = results / "agreement/dab_color_check_impact.csv"
    with impact_path.open(encoding="utf-8", newline="") as handle:
        impact_rows = list(csv.DictReader(handle))
    assert [row["marker"] for row in impact_rows] == ["ER", "PR"]
    assert all(row["color_checked_kappa"] == "1.0" for row in impact_rows)
    assert all(row["color_checked_roc_auc"] == "1.0" for row in impact_rows)
    assert all(row["color_checked_balanced_accuracy"] == "1.0" for row in impact_rows)
    assert "DAB color-check impact" in report_html
    assert "Balanced accuracy checked" in report_html
    metrics_path = results / "agreement/concordance_metrics.csv"
    with metrics_path.open(encoding="utf-8", newline="") as handle:
        metrics_reader = csv.DictReader(handle)
        metric_rows = list(metrics_reader)
    assert len(metric_rows) == 5
    assert {
        "expected_category_agreement",
        "root_mean_squared_error",
        "median_absolute_error",
        "mean_bias_tumorquantai_minus_pathologist",
        "limits_of_agreement_95_low",
        "limits_of_agreement_95_high",
        "spearman_correlation",
        "lin_concordance_correlation",
        "positive_specific_agreement",
        "negative_specific_agreement",
        "pathologist_category_counts",
        "tumorquantai_category_counts",
    } <= set(metrics_reader.fieldnames or ())
    assert stat.S_IMODE(metrics_path.stat().st_mode) == 0o600
    wide_path = results / "agreement/case_concordance_values_pseudonymized.csv"
    with wide_path.open(encoding="utf-8", newline="") as handle:
        wide_reader = csv.DictReader(handle)
        wide_rows = list(wide_reader)
    assert tuple(wide_reader.fieldnames or ()) == ihc.CASE_CONCORDANCE_WIDE_FIELDS
    assert len(wide_rows) == 4
    assert wide_rows[0]["pathologist_er_percent"] == "0"
    assert wide_rows[0]["tumorquantai_er_percent"] == "0.0"
    assert wide_rows[-1]["pathologist_her2_ihc_score"] == "3"
    assert wide_rows[-1]["tumorquantai_her2_membrane_proxy_pre_score"] == "3.0"
    assert stat.S_IMODE(wide_path.stat().st_mode) == 0o600
    contingency = json.loads(
        (results / "agreement/contingency_tables.json").read_text(encoding="utf-8")
    )
    assert contingency["HER2"]["category_labels"] == ["0", "1+", "2+", "3+"]
    assert contingency["HER2"]["matrix_rows_pathologist_columns_tumorquantai"] == [
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1],
    ]


def test_wide_tumorquantai_values_make_missing_markers_explicit() -> None:
    alias = "TQA_BC_LLLLLLLLLLLLLLLLLLLL"
    rows = ihc.wide_tumorquantai_case_values(
        [
            {
                "case_alias": alias,
                "marker": "ER",
                "marker_pre_score": 42.5,
                "h_score": 88.0,
                "unconstrained_dab_positive_percent": 97.5,
                "cell_count": 1234,
                "qc_status": "pass",
            }
        ]
    )

    assert len(rows) == 1
    assert tuple(rows[0]) == ihc.TUMORQUANTAI_WIDE_FIELDS
    assert rows[0]["tumorquantai_er_percent"] == 42.5
    assert rows[0]["tumorquantai_er_unconstrained_dab_percent"] == 97.5
    assert rows[0]["tumorquantai_er_segmented_objects"] == 1234
    assert rows[0]["tumorquantai_her2_membrane_proxy_pre_score"] == ""
    assert rows[0]["tumorquantai_her2_qc_status"] == "unavailable"


def test_agreement_notes_flag_a_single_prediction_category() -> None:
    summaries = [
        {
            "marker": "ER",
            "primary_scale": "binary-at-1-percent",
        }
    ]
    tables = {
        "ER": {
            "category_labels": ["Negative (<1%)", "Positive (≥1%)"],
            "matrix_rows_pathologist_columns_tumorquantai": [[0, 2], [0, 8]],
        }
    }

    notes = ihc._agreement_interpretation_notes(summaries, tables)

    assert len(notes) == 1
    assert "used only the Positive" in notes[0]
    assert "raw agreement is high" in notes[0]


def test_kappa_rejects_values_outside_prespecified_scale() -> None:
    with pytest.raises(ihc.IHCError, match="outside"):
        ihc.cohen_kappa([0, 2], [0, 1], [0, 1])

    missing, table = ihc.cohen_kappa([], [], [0, 1])
    assert math.isnan(missing)
    assert table.tolist() == [[0, 0], [0, 0]]


def test_private_linkage_rejects_non_public_aliases(tmp_path: Path) -> None:
    linkage = tmp_path / "private_linkage.csv"
    write_csv(
        linkage,
        ["case_alias", "case_id"],
        [{"case_alias": "PRIVATE_PATIENT_001", "case_id": 1}],
    )

    with pytest.raises(ihc.IHCError, match="non-public"):
        ihc._load_linkage_rows(linkage)


def test_cohort_report_links_to_case_qc_gallery(tmp_path: Path) -> None:
    alias = "TQA_BC_JJJJJJJJJJJJJJJJJJJJ"
    patch_alias = "TQA_PATCH_KKKKKKKKKKKKKKKKKKKK"
    artifact = tmp_path / "patches" / alias / patch_alias
    artifact.mkdir(parents=True)
    from PIL import Image

    Image.new("RGB", (12, 8), (240, 240, 240)).save(artifact / "qc_overlay.png")
    patch_rows = [
        {
            "completion_status": "completed",
            "case_alias": alias,
            "patch_alias": patch_alias,
            "marker": "ER",
            "dab_positive_percent": 25,
            "cell_count": 100,
            "qc_status": "pass",
            "qc_overlay": "qc_overlay.png",
        }
    ]
    case_rows = [
        {
            "case_alias": alias,
            "marker": "ER",
            "dab_positive_percent": 25,
            "marker_pre_score": 25,
            "cell_count": 100,
            "qc_status": "pass",
        }
    ]

    report = ihc.write_ihc_report(
        tmp_path,
        patch_rows,
        case_rows,
        {
            "engine_version": ihc.IHC_ENGINE_VERSION,
            "analysis_signature": "synthetic-signature",
        },
    )

    cohort_html = report.read_text(encoding="utf-8")
    case_report = tmp_path / "case_reports" / f"{alias}.html"
    case_html = case_report.read_text(encoding="utf-8")
    assert f"case_reports/{alias}.html" in cohort_html
    assert "Cohort overview" in cohort_html
    assert "median 25.0% color-checked DAB+" in cohort_html
    assert f"../patches/{alias}/{patch_alias}/qc_overlay.png" in case_html
    assert "research use only" in case_html
