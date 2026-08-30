"""Publication-layout figures for CK20-guided colon IHC review.

The renderer uses only PHI-free aliases and already generated registration-QC
pixels.  It deliberately labels the figures as overview-scale research output;
the panels are not a substitute for reviewing the source WSI at cellular scale.
"""

from __future__ import annotations

import math
import os
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Mapping, Sequence


FIGURE_DPI = 300
CASE_CANVAS = (4200, 3000)
SLIDE_CANVAS = (3600, 2400)


class ImmunoscoreFigureError(RuntimeError):
    """Raised when an expected paper-figure input is unsafe or malformed."""


def _fonts() -> dict[str, Any]:
    from PIL import ImageFont

    regular_candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    bold_candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    )

    def load(candidates: Sequence[str], size: int) -> Any:
        for candidate in candidates:
            if Path(candidate).is_file():
                return ImageFont.truetype(candidate, size=size)
        return ImageFont.load_default()

    return {
        "title": load(bold_candidates, 70),
        "subtitle": load(regular_candidates, 34),
        "panel": load(bold_candidates, 38),
        "body": load(regular_candidates, 32),
        "body_bold": load(bold_candidates, 32),
        "small": load(regular_candidates, 26),
        "small_bold": load(bold_candidates, 26),
        "tiny": load(regular_candidates, 22),
    }


def _atomic_image(image: Any, path: Path, image_format: str) -> None:
    target = path.expanduser().absolute()
    if target.is_symlink():
        raise ImmunoscoreFigureError(f"Refusing symlink figure output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=f".{image_format.casefold()}",
        dir=target.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        if image_format == "PNG":
            image.save(
                temporary, format="PNG", dpi=(FIGURE_DPI, FIGURE_DPI), optimize=True
            )
        elif image_format == "PDF":
            image.convert("RGB").save(temporary, format="PDF", resolution=FIGURE_DPI)
        else:
            raise ImmunoscoreFigureError(f"Unsupported figure format: {image_format}")
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _atomic_text(path: Path, value: str) -> None:
    target = path.expanduser().absolute()
    if target.is_symlink():
        raise ImmunoscoreFigureError(f"Refusing symlink legend output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value.rstrip() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _extract_qc_panels(qc_path: Path, overview: Mapping[str, Any]) -> list[Any]:
    from PIL import Image

    candidate = qc_path.expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_file():
        raise ImmunoscoreFigureError(
            f"Registration QC is not a regular file: {candidate}"
        )
    with Image.open(candidate) as source:
        canvas = source.convert("RGB")
    if canvas.width < 1800 or canvas.height < 1900:
        raise ImmunoscoreFigureError(
            "Registration QC canvas is smaller than the v1 layout"
        )
    try:
        width = int(overview["overview_width"])
        height = int(overview["overview_height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ImmunoscoreFigureError(
            "Reference overview metadata is incomplete"
        ) from exc
    if width < 1 or height < 1:
        raise ImmunoscoreFigureError("Reference overview dimensions are invalid")
    scale = min(1.0, 900.0 / max(width, height))
    rendered_width = max(1, int(round(width * scale)))
    rendered_height = max(1, int(round(height * scale)))
    local_x = (900 - rendered_width) // 2
    local_y = 42 + (900 - rendered_height) // 2
    panels = []
    for index in range(4):
        offset_x = (index % 2) * 900
        offset_y = (index // 2) * 950
        panels.append(
            canvas.crop(
                (
                    offset_x + local_x,
                    offset_y + local_y,
                    offset_x + local_x + rendered_width,
                    offset_y + local_y + rendered_height,
                )
            )
        )
    return panels


def _nice_scale_um(physical_width_um: float) -> float:
    target = max(1.0, physical_width_um * 0.18)
    exponent = math.floor(math.log10(target))
    base = 10.0**exponent
    candidates = [value * base for value in (1.0, 2.0, 5.0, 10.0)]
    eligible = [value for value in candidates if value <= target]
    return max(eligible) if eligible else candidates[0]


def _scale_label(length_um: float) -> str:
    if length_um >= 1000.0:
        value = length_um / 1000.0
        return f"{value:g} mm"
    return f"{length_um:g} µm"


def _draw_wrapped(
    draw: Any,
    xy: tuple[int, int],
    value: str,
    font: Any,
    fill: tuple[int, int, int],
    width_chars: int,
    spacing: int = 8,
) -> int:
    lines = textwrap.wrap(str(value), width=max(8, width_chars)) or [""]
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        box = draw.textbbox((x, y), line or " ", font=font)
        y += box[3] - box[1] + spacing
    return y


def _draw_image_panel(
    canvas: Any,
    draw: Any,
    image: Any,
    box: tuple[int, int, int, int],
    title: str,
    letter: str,
    physical_width_um: float,
    fonts: Mapping[str, Any],
) -> None:
    from PIL import Image

    x0, y0, x1, y1 = box
    draw.rounded_rectangle(
        box, radius=18, fill=(250, 250, 248), outline=(174, 184, 192), width=3
    )
    title_height = 74
    available_width = x1 - x0 - 30
    available_height = y1 - y0 - title_height - 20
    scale = min(available_width / image.width, available_height / image.height)
    width = max(1, int(round(image.width * scale)))
    height = max(1, int(round(image.height * scale)))
    rendered = image.resize((width, height), resample=Image.Resampling.LANCZOS)
    image_x = x0 + (x1 - x0 - width) // 2
    image_y = y0 + title_height + (available_height - height) // 2
    canvas.paste(rendered, (image_x, image_y))
    draw.text((x0 + 18, y0 + 12), letter, font=fonts["panel"], fill=(18, 33, 45))
    draw.text((x0 + 78, y0 + 15), title, font=fonts["body_bold"], fill=(18, 33, 45))
    if physical_width_um > 0 and width > 0:
        length_um = _nice_scale_um(physical_width_um)
        bar_width = max(30, int(round(width * length_um / physical_width_um)))
        bar_x1 = image_x + width - 28
        bar_x0 = bar_x1 - bar_width
        bar_y = image_y + height - 34
        draw.rectangle(
            (bar_x0 - 12, bar_y - 38, bar_x1 + 12, bar_y + 15), fill=(255, 255, 255)
        )
        draw.line((bar_x0, bar_y, bar_x1, bar_y), fill=(10, 10, 10), width=9)
        label = _scale_label(length_um)
        label_box = draw.textbbox((0, 0), label, font=fonts["tiny"])
        draw.text(
            (bar_x0 + (bar_width - (label_box[2] - label_box[0])) // 2, bar_y - 34),
            label,
            font=fonts["tiny"],
            fill=(10, 10, 10),
        )


def _numeric(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _draw_density_bars(
    draw: Any,
    box: tuple[int, int, int, int],
    labels: Sequence[str],
    values: Sequence[Any],
    colors: Sequence[tuple[int, int, int]],
    fonts: Mapping[str, Any],
    title: str = "Positive-cell density",
) -> None:
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(
        box, radius=18, fill=(250, 250, 248), outline=(174, 184, 192), width=3
    )
    draw.text((x0 + 22, y0 + 16), title, font=fonts["panel"], fill=(18, 33, 45))
    numeric = [_numeric(value) for value in values]
    finite = [value for value in numeric if value is not None and value >= 0]
    maximum = max([math.log10(1.0 + value) for value in finite], default=1.0)
    bar_left = x0 + 330
    bar_right = x1 - 150
    top = y0 + 100
    row_height = max(70, (y1 - top - 35) // max(1, len(labels)))
    for index, (label, value, color) in enumerate(zip(labels, numeric, colors)):
        y = top + index * row_height
        draw.text((x0 + 26, y + 8), label, font=fonts["small_bold"], fill=(28, 42, 52))
        draw.rounded_rectangle(
            (bar_left, y + 7, bar_right, y + 47), radius=12, fill=(226, 231, 235)
        )
        if value is not None and value >= 0:
            fraction = math.log10(1.0 + value) / maximum if maximum > 0 else 0.0
            end = bar_left + max(2, int(round((bar_right - bar_left) * fraction)))
            draw.rounded_rectangle(
                (bar_left, y + 7, end, y + 47), radius=12, fill=color
            )
            formatted = f"{value:,.2f}"
        else:
            formatted = "unavailable"
        draw.text(
            (bar_right + 18, y + 8), formatted, font=fonts["small"], fill=(28, 42, 52)
        )
    draw.text(
        (bar_left, y1 - 32),
        "Bar length: log10(1 + cells/mm²); exact values at right",
        font=fonts["tiny"],
        fill=(82, 93, 103),
    )


def _draw_ck20_fractions(
    draw: Any,
    box: tuple[int, int, int, int],
    measurement: Mapping[str, Any],
    fonts: Mapping[str, Any],
) -> None:
    metrics = measurement.get("ck20_metrics", {})
    if not isinstance(metrics, Mapping):
        metrics = {}
    values = [
        100.0 * (_numeric(metrics.get("ck20_epithelium_fraction_of_tissue")) or 0.0),
        100.0 * (_numeric(metrics.get("ck20_stroma_fraction_of_tissue")) or 0.0),
    ]
    _draw_density_bars(
        draw,
        box,
        ("CK20 epithelium", "CK20 stroma"),
        values,
        ((40, 155, 86), (224, 145, 50)),
        fonts,
        title="CK20-guided tissue fraction (%)",
    )


def _draw_score_and_qc(
    draw: Any,
    box: tuple[int, int, int, int],
    value_row: Mapping[str, Any],
    fonts: Mapping[str, Any],
) -> None:
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(
        box, radius=18, fill=(250, 250, 248), outline=(174, 184, 192), width=3
    )
    score = str(
        value_row.get("ck20_guided_provisional_immunoscore", "") or "unavailable"
    )
    percentile = _numeric(value_row.get("ck20_guided_internal_mean_percentile", ""))
    draw.text(
        (x0 + 24, y0 + 18),
        f"Provisional score: {score}",
        font=fonts["panel"],
        fill=(149, 49, 36),
    )
    gauge_x0, gauge_x1 = x0 + 30, x1 - 30
    gauge_y0, gauge_y1 = y0 + 100, y0 + 170
    bands = (
        (0.0, 10.0, (55, 55, 55), "pI0"),
        (10.0, 25.0, (75, 150, 82), "pI1"),
        (25.0, 70.0, (63, 146, 190), "pI2"),
        (70.0, 95.0, (224, 142, 42), "pI3"),
        (95.0, 100.0, (190, 52, 46), "pI4"),
    )
    for start, stop, color, label in bands:
        bx0 = int(round(gauge_x0 + (gauge_x1 - gauge_x0) * start / 100.0))
        bx1 = int(round(gauge_x0 + (gauge_x1 - gauge_x0) * stop / 100.0))
        draw.rectangle((bx0, gauge_y0, bx1, gauge_y1), fill=color)
        draw.text((bx0 + 4, gauge_y1 + 5), label, font=fonts["tiny"], fill=(35, 45, 53))
    if percentile is not None:
        pointer_x = int(
            round(
                gauge_x0
                + (gauge_x1 - gauge_x0) * min(100.0, max(0.0, percentile)) / 100.0
            )
        )
        draw.polygon(
            (
                (pointer_x, gauge_y0 - 24),
                (pointer_x - 14, gauge_y0 - 3),
                (pointer_x + 14, gauge_y0 - 3),
            ),
            fill=(0, 0, 0),
        )
        draw.text(
            (gauge_x0, gauge_y1 + 50),
            f"Mean internal percentile: {percentile:.2f}",
            font=fonts["small_bold"],
            fill=(25, 38, 48),
        )
    y = gauge_y1 + 105
    reference_n = value_row.get("ck20_guided_provisional_reference_n", "") or "0"
    draw.text(
        (x0 + 30, y),
        f"Internal reference n={reference_n} automatic-QC-pass cases",
        font=fonts["small"],
        fill=(40, 52, 61),
    )
    y += 48
    qc_status = value_row.get("qc_status", "")
    draw.text(
        (x0 + 30, y),
        f"Algorithm QC: {qc_status}",
        font=fonts["small_bold"],
        fill=(40, 52, 61),
    )
    y += 46
    flags = str(value_row.get("qc_flags", "") or "none")
    y = _draw_wrapped(
        draw, (x0 + 30, y), f"Flags: {flags}", fonts["small"], (40, 52, 61), 72
    )
    _draw_wrapped(
        draw,
        (x0 + 30, min(y + 12, y1 - 115)),
        "Research proxy only — no validated CT/IM regions or external reference distribution.",
        fonts["small_bold"],
        (149, 49, 36),
        66,
    )


def _density_values(
    value_row: Mapping[str, Any]
) -> tuple[list[str], list[Any], list[tuple[int, int, int]]]:
    labels = ["CD3 epithelium", "CD3 stroma", "CD8 epithelium", "CD8 stroma"]
    fields = [
        "tumorquantai_cd3_ck20_epithelium_density_per_mm2",
        "tumorquantai_cd3_ck20_stroma_density_per_mm2",
        "tumorquantai_cd8_ck20_epithelium_density_per_mm2",
        "tumorquantai_cd8_ck20_stroma_density_per_mm2",
    ]
    colors = [(0, 114, 178), (86, 180, 233), (213, 94, 0), (230, 159, 0)]
    return labels, [value_row.get(field, "") for field in fields], colors


def _base_canvas(
    size: tuple[int, int], title: str, subtitle: str, fonts: Mapping[str, Any]
) -> tuple[Any, Any]:
    from PIL import Image, ImageDraw

    canvas = Image.new("RGB", size, (242, 245, 247))
    draw = ImageDraw.Draw(canvas)
    draw.text((80, 54), title, font=fonts["title"], fill=(18, 33, 45))
    draw.text((82, 142), subtitle, font=fonts["subtitle"], fill=(75, 88, 98))
    return canvas, draw


def _write_figure_triplet(
    canvas: Any, base: Path, legend: str
) -> tuple[Path, Path, Path]:
    png = base.with_suffix(".png")
    pdf = base.with_suffix(".pdf")
    legend_path = base.with_name(base.name + "_legend.txt")
    _atomic_image(canvas, png, "PNG")
    _atomic_image(canvas, pdf, "PDF")
    _atomic_text(legend_path, legend)
    return png, pdf, legend_path


def render_case_paper_figures(
    output_root: Path,
    case_alias: str,
    slides: Mapping[str, Any],
    measurement: Mapping[str, Any],
    value_row: Mapping[str, Any],
    *,
    layout_version: str,
) -> list[dict[str, Any]]:
    """Render one case sheet and one marker-specific sheet per available slide."""
    case_directory = output_root / "cases" / case_alias
    qc_path = case_directory / "registration_qc.png"
    if not qc_path.is_file():
        return []
    overview = measurement.get("reference_overview", {})
    if not isinstance(overview, Mapping):
        raise ImmunoscoreFigureError("Measurement lacks reference overview metadata")
    panels = _extract_qc_panels(qc_path, overview)
    try:
        physical_width_um = float(overview["overview_width"]) * float(
            overview["overview_mpp_x"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ImmunoscoreFigureError("Reference physical scale is unavailable") from exc
    fonts = _fonts()
    score = str(
        value_row.get("ck20_guided_provisional_immunoscore", "") or "unavailable"
    )
    figure_dir = case_directory / "paper_figures"
    figure_rows: list[dict[str, Any]] = []

    case_canvas, case_draw = _base_canvas(
        CASE_CANVAS,
        f"{case_alias} · CK20-guided CD3/CD8 review",
        f"Provisional {score} · overview-scale serial-section QC; source WSI review required",
        fonts,
    )
    panel_boxes = (
        (80, 250, 2040, 1200),
        (2160, 250, 4120, 1200),
        (80, 1280, 2040, 2230),
        (2160, 1280, 4120, 2230),
    )
    titles = (
        "CK20 reference overview",
        "CK20 compartment overlay",
        "CD3→CK20 registration blend",
        "CD8→CK20 registration blend",
    )
    for index, (panel, box, title) in enumerate(zip(panels, panel_boxes, titles)):
        _draw_image_panel(
            case_canvas,
            case_draw,
            panel,
            box,
            title,
            chr(ord("a") + index),
            physical_width_um,
            fonts,
        )
    labels, values, colors = _density_values(value_row)
    _draw_density_bars(case_draw, (80, 2310, 2520, 2940), labels, values, colors, fonts)
    _draw_score_and_qc(case_draw, (2640, 2310, 4120, 2940), value_row, fonts)
    case_legend = (
        f"{case_alias}. TumorQuantAI CK20-guided CD3/CD8 research figure. "
        "(a) CK20 reference whole-slide overview. (b) CK20-positive epithelial "
        "proxy (green) and CK20-negative tissue/stromal proxy (orange). "
        "(c-d) registered CD3 and CD8 serial-section blends with CK20. Density "
        "bars report positive cells/mm2; length uses log10(1+density) while exact "
        "values are printed. The pI0-pI4 label applies published percentile bands "
        "to an internal automatic-QC-pass reference and is not consensus "
        "Immunoscore. Panels are overview-scale registration/compartment audits, "
        "not cell-outline overlays. Pathologist review of source WSIs is required."
    )
    case_base = figure_dir / "case_summary_paper_figure"
    png, pdf, legend_path = _write_figure_triplet(case_canvas, case_base, case_legend)
    figure_rows.append(
        {
            "case_alias": case_alias,
            "slide_alias": "",
            "marker": "CK20+CD3+CD8",
            "figure_scope": "case_summary",
            "png_path": str(png.relative_to(output_root)),
            "pdf_path": str(pdf.relative_to(output_root)),
            "legend_path": str(legend_path.relative_to(output_root)),
            "dpi": FIGURE_DPI,
            "layout_version": layout_version,
        }
    )

    panel_by_marker = {"CK20": 0, "CD3": 2, "CD8": 3}
    for marker in ("CK20", "CD3", "CD8"):
        slide = slides.get(marker)
        if slide is None:
            continue
        slide_alias = str(getattr(slide, "slide_alias", ""))
        canvas, draw = _base_canvas(
            SLIDE_CANVAS,
            f"{slide_alias} · {marker}",
            f"Case {case_alias} · provisional {score} · pathologist accept/flag sheet",
            fonts,
        )
        primary = panels[panel_by_marker[marker]]
        primary_title = (
            "CK20 reference overview"
            if marker == "CK20"
            else f"{marker}→CK20 registration blend"
        )
        _draw_image_panel(
            canvas,
            draw,
            primary,
            (80, 250, 1740, 1500),
            primary_title,
            "a",
            physical_width_um,
            fonts,
        )
        _draw_image_panel(
            canvas,
            draw,
            panels[1],
            (1860, 250, 3520, 1500),
            "CK20 compartment reference",
            "b",
            physical_width_um,
            fonts,
        )
        if marker == "CK20":
            _draw_ck20_fractions(draw, (80, 1590, 2170, 2330), measurement, fonts)
        else:
            start = 0 if marker == "CD3" else 2
            _draw_density_bars(
                draw,
                (80, 1590, 2170, 2330),
                labels[start : start + 2],
                values[start : start + 2],
                colors[start : start + 2],
                fonts,
            )
        _draw_score_and_qc(draw, (2290, 1590, 3520, 2330), value_row, fonts)
        legend = (
            f"{slide_alias} ({marker}), anonymized case {case_alias}. Panel a is "
            + (
                "the CK20 reference whole-slide overview. "
                if marker == "CK20"
                else f"the {marker} serial-section registration blend with CK20. "
            )
            + "Panel b shows the CK20-guided epithelial (green) and stromal "
            "(orange) proxies used for compartment assignment. Quantitative and "
            "provisional-score panels preserve exact TumorQuantAI values and "
            "algorithm QC. This overview-scale research figure is not a cell-level "
            "detection overlay and the pI label is not consensus Immunoscore."
        )
        base = figure_dir / f"{slide_alias}_{marker}_paper_figure"
        png, pdf, legend_path = _write_figure_triplet(canvas, base, legend)
        figure_rows.append(
            {
                "case_alias": case_alias,
                "slide_alias": slide_alias,
                "marker": marker,
                "figure_scope": "slide_review",
                "png_path": str(png.relative_to(output_root)),
                "pdf_path": str(pdf.relative_to(output_root)),
                "legend_path": str(legend_path.relative_to(output_root)),
                "dpi": FIGURE_DPI,
                "layout_version": layout_version,
            }
        )
    return figure_rows
