from __future__ import annotations

import csv
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

from PIL import Image

from tumorquantai_cli import immunoscore


BIN_DIR = Path(__file__).parents[1] / "bin"
sys.path.insert(0, str(BIN_DIR))
MODULE_PATH = BIN_DIR / "package_zenodo_immunoscore_release.py"
SPEC = importlib.util.spec_from_file_location(
    "package_zenodo_immunoscore_release", MODULE_PATH
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
MDS_FIELDS = (
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


def _token(index: int) -> str:
    return "A" * 18 + ALPHABET[index // 32] + ALPHABET[index % 32]


def _write_csv(path: Path, fields, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    manifest = tmp_path / module.MANIFEST_NAME
    sizes = [1] * 29 + [module.EXPECTED_MDS_BYTES - 29]
    manifest_rows = []
    inventory_rows = []
    markers_by_case = [("CD3", "CD8", "CK20") for _ in range(9)] + [
        ("CD3",),
        ("CD8", "CK20"),
    ]
    slide_index = 0
    case_aliases = []
    for case_index, markers in enumerate(markers_by_case):
        case_alias = "TQA_CI_" + _token(case_index)
        case_aliases.append(case_alias)
        for marker in markers:
            slide_alias = "TQA_CIS_" + _token(slide_index)
            size = sizes[slide_index]
            manifest_rows.append(
                {
                    "schema_version": 2,
                    "alias": slide_alias,
                    "zenodo_filename": f"{slide_alias}.mds",
                    "size_bytes": size,
                    "sha256": f"{slide_index + 1:064x}",
                    "md5": f"{slide_index + 1:032x}",
                    "source_mpp": "0.261780",
                    "level_count": 3,
                    "level_dimensions": "[[100,100],[50,50],[25,25]]",
                    "pixel_stream_count": 3,
                    "pixel_sample_sha256": "a" * 64,
                    "pixel_full_sha256": "b" * 64,
                    "sanitization_profile": "pixel-preserving-nonpixel-redaction-v2",
                }
            )
            inventory_rows.append(
                {
                    "case_alias": case_alias,
                    "slide_alias": slide_alias,
                    "marker": marker,
                    "source_format": "Motic MDS; DSI0 pixels only",
                    "source_mpp": "0.261780",
                    "source_mpp_provenance": "Motic scale",
                }
            )
            slide_index += 1
    _write_csv(manifest, MDS_FIELDS, manifest_rows)
    inventory = tmp_path / "public_slide_inventory.csv"
    _write_csv(inventory, immunoscore.PUBLIC_SLIDE_FIELDS, inventory_rows)

    analysis = tmp_path / "analysis"
    values = []
    for index, case_alias in enumerate(case_aliases):
        row = {field: "" for field in immunoscore.CASE_VALUE_FIELDS}
        row["case_alias"] = case_alias
        row["qc_status"] = "pass" if index < 9 else "unavailable"
        row["consensus_immunoscore_status"] = (
            "unavailable_requires_pathologist_validated_CT_IM_and_external_reference"
        )
        values.append(row)
        if index < 9:
            path = analysis / "cases" / case_alias / "registration_qc.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (10, 10), "white").save(path)
    _write_csv(
        analysis / "tables/tumorquantai_immunoscore_values.csv",
        immunoscore.CASE_VALUE_FIELDS,
        values,
    )
    _write_csv(
        analysis / "tables/cohort_density_summary.csv",
        immunoscore.COHORT_DENSITY_SUMMARY_FIELDS,
        immunoscore._cohort_density_summary(values),
    )
    _write_csv(
        analysis / "tables/case_compartment_densities.csv",
        immunoscore.COMPARTMENT_FIELDS,
        [],
    )
    _write_csv(
        analysis / "tables/registration_qc.csv",
        immunoscore.REGISTRATION_FIELDS,
        [],
    )
    _write_csv(
        analysis / "tables/unavailable_cases.csv",
        immunoscore.UNAVAILABLE_FIELDS,
        [],
    )
    review_rows = immunoscore._pathologist_review_rows(values)
    _write_csv(
        analysis / "tables/pathologist_review_template.csv",
        immunoscore.PATHOLOGIST_REVIEW_FIELDS,
        review_rows,
    )
    _write_csv(
        analysis / "tables/pathologist_review_codebook.csv",
        immunoscore.PATHOLOGIST_REVIEW_CODEBOOK_FIELDS,
        immunoscore._pathologist_review_codebook_rows(),
    )
    (analysis / "PATHOLOGIST_REVIEW.html").write_text(
        "<html><body>anonymous accept flag exclude review</body></html>",
        encoding="utf-8",
    )
    slides_by_case = {}
    for row in inventory_rows:
        slides_by_case.setdefault(row["case_alias"], []).append(row)
    paper_rows = []
    for case_alias in case_aliases[:9]:
        figure_dir = analysis / "cases" / case_alias / "paper_figures"
        figure_dir.mkdir(parents=True, exist_ok=True)
        definitions = [("", "CK20+CD3+CD8", "case_summary")]
        definitions.extend(
            (row["slide_alias"], row["marker"], "slide_review")
            for row in slides_by_case[case_alias]
        )
        for index, (slide_alias, marker, scope) in enumerate(definitions):
            stem = "case_summary" if not slide_alias else f"{slide_alias}_{marker}"
            png = figure_dir / f"{stem}.png"
            pdf = figure_dir / f"{stem}.pdf"
            legend = figure_dir / f"{stem}_legend.txt"
            Image.new("RGB", (20, 20), (index * 20, 100, 120)).save(png)
            Image.new("RGB", (20, 20), "white").save(pdf, format="PDF")
            legend.write_text("Anonymous research figure; not consensus Immunoscore.\n")
            paper_rows.append(
                {
                    "case_alias": case_alias,
                    "slide_alias": slide_alias,
                    "marker": marker,
                    "figure_scope": scope,
                    "png_path": str(png.relative_to(analysis)),
                    "pdf_path": str(pdf.relative_to(analysis)),
                    "legend_path": str(legend.relative_to(analysis)),
                    "dpi": 300,
                    "layout_version": immunoscore.PAPER_FIGURE_LAYOUT_VERSION,
                }
            )
    _write_csv(
        analysis / "tables/paper_figure_manifest.csv",
        immunoscore.PAPER_FIGURE_FIELDS,
        paper_rows,
    )
    metadata = analysis / "workflow_metadata/immunoscore_run.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(
        json.dumps(
            {
                "schema_version": immunoscore.IMMUNOSCORE_SCHEMA_VERSION,
                "report_path": "START_HERE.html",
            }
        ),
        encoding="utf-8",
    )
    return manifest, inventory, analysis


def test_packages_exact_anonymous_release_artifacts(tmp_path: Path) -> None:
    manifest, inventory, analysis = _fixture(tmp_path)
    output = tmp_path / "public"
    result = module.package_release(
        manifest,
        inventory,
        analysis,
        output,
    )
    assert result["mds_file_count"] == 30
    assert result["registration_qc_image_count"] == 9
    assert result["paper_figure_count"] == 36
    assert (output / "README.md").is_file()
    assert (output / "REPORT.html").is_file()
    assert (output / "cohort_density_summary.csv").is_file()
    assert (output / "PATHOLOGIST_REVIEW.html").is_file()
    figure_zip = output / "tumorquantai_immunoscore_paper_figures.zip"
    assert figure_zip.is_file()
    with zipfile.ZipFile(figure_zip) as archive:
        assert len(archive.namelist()) == 108
    assert (output / "SHA256SUMS").read_text(encoding="utf-8").count(".mds") == 30
    with (output / "tumorquantai_colon_immunoscore_slide_catalog.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        assert len(list(csv.DictReader(handle))) == 30
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in output.iterdir()
        if path.suffix.casefold() not in {".png", ".pdf", ".zip"}
    )
    assert "/private/" not in combined
    assert "source_case_id" not in combined
    validation = json.loads(
        (output / "release_validation_report.json").read_text(encoding="utf-8")
    )
    assert validation["original_label_or_macro_content_included"] is False
    assert validation["neutral_label_macro_streams_included"] is True
