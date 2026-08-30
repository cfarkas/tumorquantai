from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw

from tumorquantai_cli import immunoscore_figures


def _registration_qc(path: Path) -> None:
    canvas = Image.new("RGB", (1800, 1940), "white")
    draw = ImageDraw.Draw(canvas)
    colors = ((177, 115, 92), (71, 145, 84), (109, 138, 175), (185, 121, 61))
    for index, color in enumerate(colors):
        x = (index % 2) * 900
        y = (index // 2) * 950
        draw.rectangle((x + 50, y + 92, x + 850, y + 892), fill=color)
    path.parent.mkdir(parents=True)
    canvas.save(path)


def test_render_case_and_per_slide_paper_figures(tmp_path: Path) -> None:
    case_alias = "TQA_CI_" + "A" * 20
    qc_path = tmp_path / "cases" / case_alias / "registration_qc.png"
    _registration_qc(qc_path)
    slides = {
        marker: SimpleNamespace(slide_alias=f"TQA_CIS_{letter * 20}")
        for marker, letter in (("CK20", "C"), ("CD3", "D"), ("CD8", "E"))
    }
    measurement = {
        "reference_overview": {
            "overview_width": 800,
            "overview_height": 800,
            "overview_mpp_x": 12.5,
            "overview_mpp_y": 12.5,
        },
        "ck20_metrics": {
            "ck20_epithelium_fraction_of_tissue": 0.4,
            "ck20_stroma_fraction_of_tissue": 0.6,
        },
    }
    values = {
        "ck20_guided_provisional_immunoscore": "pI2",
        "ck20_guided_internal_mean_percentile": 50.0,
        "ck20_guided_provisional_reference_n": 6,
        "tumorquantai_cd3_ck20_epithelium_density_per_mm2": 100.0,
        "tumorquantai_cd3_ck20_stroma_density_per_mm2": 200.0,
        "tumorquantai_cd8_ck20_epithelium_density_per_mm2": 80.0,
        "tumorquantai_cd8_ck20_stroma_density_per_mm2": 120.0,
        "qc_status": "pass",
        "qc_flags": "",
    }
    rows = immunoscore_figures.render_case_paper_figures(
        tmp_path,
        case_alias,
        slides,
        measurement,
        values,
        layout_version="test-layout-v1",
    )
    assert len(rows) == 4
    assert {row["figure_scope"] for row in rows} == {"case_summary", "slide_review"}
    assert {row["marker"] for row in rows} == {
        "CK20+CD3+CD8",
        "CK20",
        "CD3",
        "CD8",
    }
    for row in rows:
        png = tmp_path / row["png_path"]
        pdf = tmp_path / row["pdf_path"]
        legend = tmp_path / row["legend_path"]
        assert png.is_file()
        assert pdf.is_file()
        assert legend.is_file()
        assert "not consensus Immunoscore" in legend.read_text(encoding="utf-8")
        with Image.open(png) as rendered:
            expected = (
                immunoscore_figures.CASE_CANVAS
                if row["figure_scope"] == "case_summary"
                else immunoscore_figures.SLIDE_CANVAS
            )
            assert rendered.size == expected
            assert abs(rendered.info["dpi"][0] - 300.0) < 0.01


def test_missing_registration_qc_skips_paper_figures(tmp_path: Path) -> None:
    assert (
        immunoscore_figures.render_case_paper_figures(
            tmp_path,
            "TQA_CI_" + "A" * 20,
            {},
            {},
            {},
            layout_version="test",
        )
        == []
    )
