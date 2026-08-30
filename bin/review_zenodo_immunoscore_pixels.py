#!/usr/bin/env python3
"""Render PHI-review panels from sanitized colon-IHC MDS files."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import Any

import olefile
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bin"))

from mds_manifest import load_manifest  # noqa: E402
from tumorquantai_cli.mds_reader import MdsPixels  # noqa: E402


ALIAS_RE = re.compile(r"^TQA_CIS_[A-Z2-7]{20}$")
EXPECTED_COUNT = 30
PANEL_SIZE = (800, 560)


class ReviewError(RuntimeError):
    """Raised when a sanitized MDS cannot be rendered for privacy review."""


def _fit(image: Image.Image, box: tuple[int, int]) -> Image.Image:
    result = image.copy()
    result.thumbnail(box, Image.Resampling.LANCZOS)
    return result


def _embedded_image(path: Path, name: str) -> Image.Image:
    with olefile.OleFileIO(str(path)) as ole:
        matches = [
            stream
            for stream in ole.listdir(streams=True, storages=False)
            if len(stream) == 1 and stream[0].casefold() == name.casefold()
        ]
        if len(matches) != 1:
            raise ReviewError(f"Sanitized MDS has no unique {name} stream")
        payload = ole.openstream(matches[0]).read()
    try:
        with Image.open(BytesIO(payload)) as image:
            return image.convert("RGB").copy()
    except Exception as exc:
        raise ReviewError(f"Sanitized {name} stream is not a readable image") from exc


def _overview(
    path: Path, maximum_edge: int = 1600
) -> tuple[Image.Image, dict[str, Any]]:
    with MdsPixels(path) as pixels:
        candidates = [
            level
            for level in pixels.levels
            if max(level.width, level.height) >= maximum_edge
        ]
        level = candidates[-1] if candidates else pixels.levels[-1]
        rgb = pixels.read_level_array(level)
        level_count = len(pixels.levels)
        level_dimensions = [
            [candidate.width, candidate.height] for candidate in pixels.levels
        ]
    image = Image.fromarray(rgb, mode="RGB")
    image.thumbnail((maximum_edge, maximum_edge), Image.Resampling.LANCZOS)
    return image, {
        "level_index": level.index,
        "level_name": level.name,
        "level_count": level_count,
        "level_dimensions": level_dimensions,
        "overview_width": image.width,
        "overview_height": image.height,
    }


def _atomic_png(path: Path, image: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".png", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        image.save(temporary, format="PNG", optimize=True)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def render_one(
    alias: str,
    source: Path,
    output_dir: Path,
    expected_size: int,
    resume: bool,
) -> dict[str, Any]:
    overview_path = output_dir / f"overview_{alias}.png"
    panel_path = output_dir / f"review_{alias}.png"
    if source.is_symlink() or not source.is_file():
        raise ReviewError(f"Sanitized MDS is missing for {alias}")
    if source.stat().st_size != expected_size:
        raise ReviewError(f"Sanitized MDS size changed for {alias}")
    if resume and overview_path.is_file() and panel_path.is_file():
        with Image.open(overview_path) as image:
            overview_width, overview_height = image.size
        return {
            "alias": alias,
            "overview_file": overview_path.name,
            "panel_file": panel_path.name,
            "overview_width": overview_width,
            "overview_height": overview_height,
            "render_status": "verified-existing",
        }

    overview, details = _overview(source)
    label = _embedded_image(source, "Label")
    macro = _embedded_image(source, "Macro")
    _atomic_png(overview_path, overview)

    panel = Image.new("RGB", PANEL_SIZE, "white")
    draw = ImageDraw.Draw(panel)
    draw.text((14, 12), alias, fill=(15, 23, 42))
    draw.text(
        (14, 34),
        "DSI0 tissue overview; embedded Label and Macro must be neutral",
        fill=(55, 65, 81),
    )
    tissue = _fit(overview, (560, 470))
    panel.paste(tissue, (14, 72))
    label_small = _fit(label, (200, 190))
    macro_small = _fit(macro, (200, 190))
    panel.paste(label_small, (586 + (200 - label_small.width) // 2, 100))
    panel.paste(macro_small, (586 + (200 - macro_small.width) // 2, 345))
    draw.text((586, 78), "Embedded Label", fill=(15, 23, 42))
    draw.text((586, 323), "Embedded Macro", fill=(15, 23, 42))
    _atomic_png(panel_path, panel)
    return {
        "alias": alias,
        "overview_file": overview_path.name,
        "panel_file": panel_path.name,
        "label_width": label.width,
        "label_height": label.height,
        "macro_width": macro.width,
        "macro_height": macro.height,
        "render_status": "rendered",
        **details,
    }


def _contact_sheets(
    output_dir: Path,
    rows: list[dict[str, Any]],
    per_sheet: int = 6,
) -> list[str]:
    names: list[str] = []
    for offset in range(0, len(rows), per_sheet):
        selected = rows[offset : offset + per_sheet]
        sheet = Image.new(
            "RGB",
            (PANEL_SIZE[0] * 2, PANEL_SIZE[1] * 3),
            (225, 231, 238),
        )
        for index, row in enumerate(selected):
            with Image.open(output_dir / str(row["panel_file"])) as panel:
                sheet.paste(
                    panel.convert("RGB"),
                    ((index % 2) * PANEL_SIZE[0], (index // 2) * PANEL_SIZE[1]),
                )
        name = f"contact_sheet_{offset // per_sheet + 1:02d}.png"
        _atomic_png(output_dir / name, sheet)
        names.append(name)
    return names


def run(
    staging_dir: Path,
    public_manifest: Path,
    output_dir: Path,
    *,
    workers: int,
    resume: bool,
) -> dict[str, Any]:
    if workers < 1 or workers > 8:
        raise ReviewError("Workers must be between 1 and 8")
    rows, _text = load_manifest(public_manifest, alias_re=ALIAS_RE)
    if len(rows) != EXPECTED_COUNT:
        raise ReviewError("Review manifest must contain exactly 30 MDS files")
    staging = staging_dir.expanduser().resolve()
    output_candidate = output_dir.expanduser().absolute()
    if output_candidate.is_symlink():
        raise ReviewError("Review output must not be a symlink")
    output = output_candidate.resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output, 0o700)
    tasks = [
        (
            row.alias,
            staging / row.zenodo_filename,
            output,
            row.size_bytes,
            resume,
        )
        for row in rows
    ]
    rendered: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as executor:
        futures = {executor.submit(render_one, *task): str(task[0]) for task in tasks}
        for future in as_completed(futures):
            alias = futures[future]
            try:
                rendered.append(future.result())
            except Exception as exc:
                raise ReviewError(f"Pixel-review rendering failed for {alias}") from exc
            print(f"rendered privacy-review panel: {alias}", file=sys.stderr)
    rendered.sort(key=lambda row: str(row["alias"]))
    contact_sheets = _contact_sheets(output, rendered)
    fields = sorted({key for row in rendered for key in row})
    manifest_path = output / "visual_review_manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rendered)
    report = {
        "schema_version": 1,
        "status": "rendered_pending_documented_visual_review",
        "slide_count": len(rendered),
        "contact_sheets": contact_sheets,
        "review_requirements": [
            "DSI0 tissue overview contains no visible identifiers",
            "embedded Label is neutral",
            "embedded Macro is neutral",
            "all 30 slides receive a documented reviewer decision",
        ],
    }
    (output / "visual_review_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {**report, "output_dir": str(output)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-dir", required=True, type=Path)
    parser.add_argument("--public-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run(
            args.staging_dir,
            args.public_manifest,
            args.output_dir,
            workers=args.workers,
            resume=args.resume,
        )
    except (ReviewError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
