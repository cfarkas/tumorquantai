#!/usr/bin/env python3
"""Export Motic MDS pixel levels to resumable, integrity-tracked BigTIFF.

Only ``DSI0`` pixel streams are read. Labels, macro images, and acquisition
metadata are never exported. The conversion manifest binds every TIFF to its
source MDS checksum and exact conversion settings.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterator

import numpy as np
import olefile
import tifffile
from PIL import Image

from mds_manifest import MdsManifestError, MdsManifestRow, load_manifest


ALIAS_RE = re.compile(r"^TumorQuantAI_LymphomaWSI_[0-9]{3}$")
CONVERSION_SCHEMA_VERSION = 1
CONVERTER_VERSION = "1.0"
CONVERSION_MANIFEST_NAME = "mds_conversion_manifest.json"
SAMPLES_NAME = "samples.csv"


class MdsExportError(RuntimeError):
    """Raised when an MDS file cannot be exported safely."""


@dataclass(frozen=True)
class MdsLevel:
    index: int
    name: str
    rows: int
    columns: int
    tile_width: int
    tile_height: int

    @property
    def width(self) -> int:
        return self.columns * self.tile_width

    @property
    def height(self) -> int:
        return self.rows * self.tile_height


def parse_tile_name(value: str) -> tuple[int, int] | None:
    parts = value.split("_")
    if len(parts) != 2:
        return None
    try:
        row, column = (int(part) for part in parts)
    except ValueError:
        return None
    if row < 0 or column < 0:
        return None
    return row, column


def level_sort_key(value: str) -> tuple[int, float | str]:
    try:
        return (0, -float(value))
    except ValueError:
        return (1, value.casefold())


class MdsPixels:
    """Small, read-only MDS pixel reader backed by ``olefile``."""

    def __init__(self, path: Path) -> None:
        candidate = path.expanduser().absolute()
        if candidate.is_symlink() or not candidate.is_file():
            raise MdsExportError(f"MDS input is not a regular file: {candidate}")
        self.path = candidate.resolve()
        if self.path.suffix.casefold() != ".mds":
            raise MdsExportError(f"MDS input must end in .mds: {self.path}")
        try:
            self.ole = olefile.OleFileIO(str(self.path))
        except (OSError, IOError, olefile.OleFileError) as exc:
            raise MdsExportError(
                f"Cannot open MDS OLE structure: {self.path}"
            ) from exc
        self._tiles: dict[str, dict[tuple[int, int], tuple[str, ...]]] = {}
        try:
            self._levels = self._discover_levels()
        except Exception:
            self.ole.close()
            raise

    def __enter__(self) -> "MdsPixels":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.ole.close()

    @property
    def levels(self) -> tuple[MdsLevel, ...]:
        return self._levels

    def _discover_levels(self) -> tuple[MdsLevel, ...]:
        grouped: dict[str, dict[tuple[int, int], tuple[str, ...]]] = {}
        for stream in self.ole.listdir(streams=True, storages=False):
            if len(stream) != 3 or stream[0] != "DSI0":
                continue
            coordinate = parse_tile_name(stream[2])
            if coordinate is None:
                continue
            grouped.setdefault(stream[1], {})[coordinate] = tuple(stream)
        if not grouped:
            raise MdsExportError(f"MDS contains no DSI0 pixel tiles: {self.path}")

        levels: list[MdsLevel] = []
        for index, name in enumerate(sorted(grouped, key=level_sort_key)):
            tiles = grouped[name]
            first_path = tiles[min(tiles)]
            try:
                encoded = self.ole.openstream(list(first_path)).read()
                with Image.open(BytesIO(encoded)) as image:
                    tile_width, tile_height = image.size
            except Exception as exc:
                raise MdsExportError(
                    f"Cannot decode the first tile in MDS level {name!r}: "
                    f"{self.path}"
                ) from exc
            if tile_width <= 0 or tile_height <= 0:
                raise MdsExportError(f"Invalid tile dimensions in {self.path}")
            rows = max(row for row, _ in tiles) + 1
            columns = max(column for _, column in tiles) + 1
            self._tiles[name] = tiles
            levels.append(
                MdsLevel(
                    index=index,
                    name=name,
                    rows=rows,
                    columns=columns,
                    tile_width=tile_width,
                    tile_height=tile_height,
                )
            )
        return tuple(levels)

    def iter_level_tiles(
        self, level: MdsLevel, fill_value: int = 255
    ) -> Iterator[np.ndarray]:
        paths = self._tiles[level.name]
        expected_shape = (level.tile_height, level.tile_width, 3)
        for row in range(level.rows):
            for column in range(level.columns):
                stream = paths.get((row, column))
                if stream is None:
                    yield np.full(expected_shape, fill_value, dtype=np.uint8)
                    continue
                try:
                    encoded = self.ole.openstream(list(stream)).read()
                    with Image.open(BytesIO(encoded)) as image:
                        array = np.asarray(image.convert("RGB"), dtype=np.uint8)
                except Exception as exc:
                    raise MdsExportError(
                        f"Cannot decode tile {level.name}/{row}_{column} "
                        f"in {self.path}"
                    ) from exc
                if array.shape == expected_shape:
                    yield array
                    continue
                padded = np.full(expected_shape, fill_value, dtype=np.uint8)
                height = min(array.shape[0], level.tile_height)
                width = min(array.shape[1], level.tile_width)
                padded[:height, :width, :] = array[:height, :width, :3]
                yield padded


def compression_settings(name: str, level: int) -> tuple[str | None, dict | None]:
    normalized = name.strip().casefold()
    if normalized in {"none", "no", "uncompressed"}:
        return None, None
    if normalized in {"deflate", "zlib"}:
        if not 0 <= level <= 9:
            raise MdsExportError("--compression-level must be between 0 and 9")
        return "deflate", {"level": level}
    return normalized, None


def validate_mpp(value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise MdsExportError("source MPP must be finite and greater than zero")
    return value


def digest_file(path: Path) -> tuple[int, str]:
    before = path.stat()
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    after = path.stat()
    identity = lambda item: (
        item.st_dev,
        item.st_ino,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
    )
    if identity(before) != identity(after):
        raise MdsExportError(f"File changed while hashing: {path}")
    return size, digest.hexdigest()


def _rational_float(value: object) -> float:
    if isinstance(value, tuple) and len(value) == 2:
        return float(value[0]) / float(value[1])
    return float(value)


def validate_tiff(
    path: Path, *, width: int, height: int, output_mpp: float
) -> None:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_file():
        raise MdsExportError(f"TIFF output is not a regular file: {candidate}")
    try:
        with tifffile.TiffFile(candidate) as tif:
            page = tif.pages[0]
            if (int(page.imagewidth), int(page.imagelength)) != (width, height):
                raise MdsExportError(f"TIFF dimension validation failed: {candidate}")
            if not page.is_tiled or int(page.samplesperpixel) != 3:
                raise MdsExportError(
                    f"TIFF tile/channel validation failed: {candidate}"
                )
            unit = int(page.tags["ResolutionUnit"].value)
            x_resolution = _rational_float(page.tags["XResolution"].value)
            measured_mpp = 10_000.0 / x_resolution if unit == 3 else math.nan
            if (
                not math.isfinite(measured_mpp)
                or not math.isclose(
                    measured_mpp, output_mpp, rel_tol=2e-6, abs_tol=2e-6
                )
            ):
                raise MdsExportError(
                    f"TIFF physical-resolution validation failed: {candidate}"
                )
    except (KeyError, OSError, tifffile.TiffFileError) as exc:
        raise MdsExportError(f"Cannot validate TIFF output: {candidate}") from exc


def export_level(
    source: MdsPixels,
    level: MdsLevel,
    output: Path,
    *,
    source_mpp: float,
    compression: str,
    compression_level: int,
    overwrite: bool,
) -> dict[str, object]:
    candidate = output.expanduser().absolute()
    if candidate.is_symlink():
        raise MdsExportError(f"Refusing symlink output: {candidate}")
    output = candidate.resolve()
    if output.exists() and not overwrite:
        raise MdsExportError(f"Output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    codec, codec_args = compression_settings(compression, compression_level)
    try:
        downsample = float(source.levels[0].name) / float(level.name)
    except ValueError as exc:
        raise MdsExportError(f"Non-numeric MDS level name: {level.name!r}") from exc
    level_mpp = source_mpp * downsample
    pixels_per_centimeter = 10_000.0 / level_mpp

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        tifffile.imwrite(
            str(temporary),
            data=source.iter_level_tiles(level),
            shape=(level.height, level.width, 3),
            dtype=np.uint8,
            tile=(level.tile_height, level.tile_width),
            photometric="rgb",
            planarconfig="contig",
            compression=codec,
            compressionargs=codec_args,
            bigtiff=True,
            metadata=None,
            resolution=(pixels_per_centimeter, pixels_per_centimeter),
            resolutionunit="CENTIMETER",
            maxworkers=None,
        )
        validate_tiff(
            temporary,
            width=level.width,
            height=level.height,
            output_mpp=level_mpp,
        )
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    size, sha256 = digest_file(output)
    return {
        "output": str(output),
        "width": level.width,
        "height": level.height,
        "output_mpp": level_mpp,
        "output_size_bytes": size,
        "output_sha256": sha256,
        "status": "exported",
    }


def discover_inputs(value: Path) -> list[Path]:
    candidate = value.expanduser().resolve()
    if candidate.is_file():
        return [candidate]
    if not candidate.is_dir():
        raise MdsExportError(f"Input does not exist: {candidate}")
    paths = sorted(candidate.rglob("*.mds"), key=lambda path: str(path).casefold())
    if not paths:
        raise MdsExportError(f"No .mds files found under: {candidate}")
    return paths


def sample_id_for(path: Path) -> str:
    if ALIAS_RE.fullmatch(path.stem):
        return path.stem
    if path.name.casefold() == "1.mds" and ALIAS_RE.fullmatch(path.parent.name):
        return path.parent.name
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._-")
    if not value:
        raise MdsExportError(f"Cannot derive a safe sample ID from: {path}")
    return value


def select_inputs(paths: list[Path], requested: list[str]) -> list[Path]:
    by_sample: dict[str, Path] = {}
    for path in paths:
        sample_id = sample_id_for(path)
        if sample_id in by_sample:
            raise MdsExportError(f"Duplicate sample ID in MDS inputs: {sample_id}")
        by_sample[sample_id] = path
    if not requested:
        return [by_sample[key] for key in sorted(by_sample)]
    if len(set(requested)) != len(requested):
        raise MdsExportError("--sample-id values must be unique")
    missing = [sample_id for sample_id in requested if sample_id not in by_sample]
    if missing:
        raise MdsExportError("Requested sample IDs are absent: " + ", ".join(missing))
    return [by_sample[sample_id] for sample_id in requested]


def _safe_relative_output(output_dir: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise MdsExportError(f"Unsafe conversion-manifest path: {value}")
    target = output_dir / relative
    cursor = output_dir
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise MdsExportError(f"Refusing symlink in output path: {value}")
    resolved = target.resolve()
    try:
        resolved.relative_to(output_dir)
    except ValueError as exc:
        raise MdsExportError(f"Conversion path escapes output directory: {value}") from exc
    return resolved


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    if path.exists() and path.is_symlink():
        raise MdsExportError(f"Refusing symlink state file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def empty_conversion_state() -> dict[str, object]:
    return {
        "schema_version": CONVERSION_SCHEMA_VERSION,
        "converter_version": CONVERTER_VERSION,
        "entries": [],
    }


def load_conversion_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return empty_conversion_state()
    if path.is_symlink() or not path.is_file():
        raise MdsExportError(f"Conversion manifest is not a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MdsExportError(f"Invalid conversion manifest: {path}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != CONVERSION_SCHEMA_VERSION
        or payload.get("converter_version") != CONVERTER_VERSION
        or not isinstance(payload.get("entries"), list)
    ):
        raise MdsExportError(f"Unsupported conversion manifest: {path}")
    seen: set[tuple[str, int]] = set()
    for raw in payload["entries"]:
        if not isinstance(raw, dict):
            raise MdsExportError("Invalid conversion-manifest entry")
        try:
            key = (str(raw["sample_id"]), int(raw["level"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise MdsExportError("Invalid conversion-manifest entry key") from exc
        if key in seen or not ALIAS_RE.fullmatch(key[0]) or key[1] < 0:
            raise MdsExportError("Unsafe/duplicate conversion-manifest entry")
        seen.add(key)
    return payload


def entry_index(state: dict[str, object]) -> dict[tuple[str, int], dict[str, object]]:
    entries = state.get("entries")
    assert isinstance(entries, list)
    return {
        (str(entry["sample_id"]), int(entry["level"])): entry
        for entry in entries
        if isinstance(entry, dict)
    }


def store_entry(state: dict[str, object], entry: dict[str, object]) -> None:
    entries = entry_index(state)
    entries[(str(entry["sample_id"]), int(entry["level"]))] = entry
    state["entries"] = [
        entries[key] for key in sorted(entries, key=lambda item: (item[0], item[1]))
    ]


def expected_entry(
    *,
    sample_id: str,
    source: Path,
    source_size: int,
    source_sha256: str,
    source_mpp: float,
    source_level_count: int,
    base_level_name: str,
    level: MdsLevel,
    output_dir: Path,
    output: Path,
    compression: str,
    compression_level: int,
) -> dict[str, object]:
    try:
        downsample = float(level.name)
        base_scale = float(base_level_name)
    except ValueError as exc:
        raise MdsExportError(f"Non-numeric MDS level name: {level.name!r}") from exc
    output_mpp = source_mpp * (base_scale / downsample)
    return {
        "schema_version": CONVERSION_SCHEMA_VERSION,
        "converter_version": CONVERTER_VERSION,
        "sample_id": sample_id,
        "source_mds_path": str(source),
        "source_mds_size_bytes": source_size,
        "source_mds_sha256": source_sha256,
        "source_mpp": source_mpp,
        "source_level_count": source_level_count,
        "level": level.index,
        "internal_level": level.name,
        "output_path": str(output.relative_to(output_dir)),
        "width": level.width,
        "height": level.height,
        "output_mpp": output_mpp,
        "compression": compression.strip().casefold(),
        "compression_level": compression_level,
    }


def entry_matches(existing: dict[str, object], expected: dict[str, object]) -> bool:
    exact_fields = (
        "schema_version",
        "converter_version",
        "sample_id",
        "source_mds_path",
        "source_mds_size_bytes",
        "source_mds_sha256",
        "source_level_count",
        "level",
        "internal_level",
        "output_path",
        "width",
        "height",
        "compression",
        "compression_level",
    )
    if any(existing.get(field) != expected.get(field) for field in exact_fields):
        return False
    for field in ("source_mpp", "output_mpp"):
        try:
            if not math.isclose(
                float(existing.get(field)),
                float(expected.get(field)),
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                return False
        except (TypeError, ValueError):
            return False
    return True


def verify_existing_entry(
    output_dir: Path,
    entry: dict[str, object],
    expected: dict[str, object] | None = None,
) -> dict[str, object]:
    if expected is not None and not entry_matches(entry, expected):
        raise MdsExportError(
            f"Resume settings/source changed for "
            f"{entry.get('sample_id')} L{entry.get('level')}"
        )
    try:
        target = _safe_relative_output(output_dir, str(entry["output_path"]))
        width = int(entry["width"])
        height = int(entry["height"])
        output_mpp = float(entry["output_mpp"])
        expected_size = int(entry["output_size_bytes"])
        expected_sha = str(entry["output_sha256"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MdsExportError("Incomplete conversion-manifest entry") from exc
    validate_tiff(target, width=width, height=height, output_mpp=output_mpp)
    size, sha256 = digest_file(target)
    if size != expected_size or sha256 != expected_sha:
        raise MdsExportError(
            f"Existing TIFF checksum differs from conversion manifest: {target}"
        )
    result = dict(entry)
    result["status"] = "verified-existing"
    return result


def write_samples(output_dir: Path, rows: list[dict[str, object]]) -> Path:
    selected: dict[str, str] = {}
    for row in rows:
        if int(row["level"]) != 0:
            continue
        sample_id = str(row["sample_id"])
        relative = f"{sample_id}/1_L0_rgb.tif"
        if sample_id in selected:
            raise MdsExportError(f"Duplicate sample ID: {sample_id}")
        selected[sample_id] = relative
    target = output_dir / SAMPLES_NAME
    output_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{SAMPLES_NAME}.", dir=output_dir
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=("sample_id", "slide_path"))
            writer.writeheader()
            for sample_id in sorted(selected):
                writer.writerow(
                    {"sample_id": sample_id, "slide_path": selected[sample_id]}
                )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def verified_complete_rows(
    output_dir: Path,
    state: dict[str, object],
    already_verified: set[tuple[str, int]],
) -> list[dict[str, object]]:
    entries = entry_index(state)
    complete_aliases = sorted(
        alias
        for alias in {key[0] for key in entries}
        if (alias, 0) in entries and (alias, 2) in entries
    )
    rows: list[dict[str, object]] = []
    for alias in complete_aliases:
        for level in (0, 2):
            entry = entries[(alias, level)]
            if (alias, level) not in already_verified:
                verify_existing_entry(output_dir, entry)
            rows.append(entry)
    return rows


def _manifest_by_alias(path: Path | None) -> dict[str, MdsManifestRow]:
    if path is None:
        return {}
    try:
        rows, _ = load_manifest(path)
    except MdsManifestError as exc:
        raise MdsExportError(str(exc)) from exc
    return {row.alias: row for row in rows}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="MDS file or directory")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Authoritative MDS manifest used to verify source hashes and geometry",
    )
    parser.add_argument("--levels", nargs="+", type=int, default=[0, 2])
    parser.add_argument(
        "--sample-id",
        action="append",
        default=[],
        help="Convert only this public alias; repeatable",
    )
    parser.add_argument(
        "--expected-count",
        type=int,
        help="Fail unless exactly this many slides are selected",
    )
    parser.add_argument(
        "--source-mpp",
        type=float,
        help="Required without --manifest; must match it when both are provided",
    )
    parser.add_argument("--compression", default="deflate")
    parser.add_argument("--compression-level", type=int, default=6)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--resume",
        action="store_true",
        help="Reuse only TIFFs verified by the conversion manifest",
    )
    mode.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace selected outputs and their conversion entries",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def run(args: argparse.Namespace) -> list[dict[str, object]]:
    requested_levels = sorted(set(args.levels))
    if not requested_levels or requested_levels[0] < 0:
        raise MdsExportError("--levels must contain non-negative integers")
    compression_settings(args.compression, args.compression_level)
    inputs = select_inputs(discover_inputs(args.input), args.sample_id)
    if args.expected_count is not None:
        if args.expected_count <= 0:
            raise MdsExportError("--expected-count must be greater than zero")
        if len(inputs) != args.expected_count:
            raise MdsExportError(
                f"Expected {args.expected_count} selected MDS files, found {len(inputs)}"
            )
    manifest_rows = _manifest_by_alias(args.manifest)
    if not manifest_rows and args.source_mpp is None:
        raise MdsExportError("Provide --manifest or --source-mpp")

    output_candidate = args.output_dir.expanduser().absolute()
    if output_candidate.is_symlink():
        raise MdsExportError(f"Refusing symlink output directory: {output_candidate}")
    output_dir = output_candidate.resolve()
    state_path = output_dir / CONVERSION_MANIFEST_NAME
    if state_path.exists() and not (args.resume or args.overwrite or args.dry_run):
        raise MdsExportError(
            f"Conversion manifest already exists; use --resume or --overwrite: "
            f"{state_path}"
        )
    state = load_conversion_state(state_path) if not args.dry_run else empty_conversion_state()
    existing_entries = entry_index(state)
    rows: list[dict[str, object]] = []
    verified_keys: set[tuple[str, int]] = set()

    for path in inputs:
        sample_id = sample_id_for(path)
        manifest_row = manifest_rows.get(sample_id)
        if manifest_rows and manifest_row is None:
            raise MdsExportError(f"Input alias is absent from manifest: {sample_id}")
        if manifest_row is not None:
            source_mpp = manifest_row.source_mpp
            if args.source_mpp is not None and not math.isclose(
                validate_mpp(args.source_mpp),
                source_mpp,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise MdsExportError(
                    f"--source-mpp differs from manifest for {sample_id}"
                )
        else:
            assert args.source_mpp is not None
            source_mpp = validate_mpp(args.source_mpp)

        if args.dry_run:
            source_size = (
                manifest_row.size_bytes if manifest_row is not None else path.stat().st_size
            )
            source_sha = manifest_row.sha256 if manifest_row is not None else "not-computed"
        else:
            source_size, source_sha = digest_file(path)
            if manifest_row is not None and (
                source_size != manifest_row.size_bytes
                or source_sha != manifest_row.sha256
            ):
                raise MdsExportError(
                    f"Source MDS checksum differs from manifest: {sample_id}"
                )

        with MdsPixels(path) as slide:
            actual_dimensions = tuple(
                (level.width, level.height) for level in slide.levels
            )
            if manifest_row is not None and (
                len(slide.levels) != manifest_row.level_count
                or actual_dimensions != manifest_row.level_dimensions
            ):
                raise MdsExportError(
                    f"Source MDS geometry differs from manifest: {sample_id}"
                )
            unavailable = [
                index for index in requested_levels if index >= len(slide.levels)
            ]
            if unavailable:
                raise MdsExportError(
                    f"{path.name} has {len(slide.levels)} levels; "
                    f"unavailable: {unavailable}"
                )
            for index in requested_levels:
                level = slide.levels[index]
                output = _safe_relative_output(
                    output_dir, f"{sample_id}/1_L{index}_rgb.tif"
                )
                expected = expected_entry(
                    sample_id=sample_id,
                    source=path.resolve(),
                    source_size=source_size,
                    source_sha256=source_sha,
                    source_mpp=source_mpp,
                    source_level_count=len(slide.levels),
                    base_level_name=slide.levels[0].name,
                    level=level,
                    output_dir=output_dir,
                    output=output,
                    compression=args.compression,
                    compression_level=args.compression_level,
                )
                key = (sample_id, index)
                if args.dry_run:
                    rows.append({**expected, "status": "planned"})
                    continue
                existing = existing_entries.get(key)
                if output.exists() and args.resume:
                    if existing is None:
                        raise MdsExportError(
                            f"Existing TIFF has no trusted conversion entry: {output}; "
                            "review it, then use --overwrite to regenerate"
                        )
                    result = verify_existing_entry(output_dir, existing, expected)
                    rows.append(result)
                    verified_keys.add(key)
                    continue
                if output.exists() and not args.overwrite:
                    raise MdsExportError(
                        f"Output already exists; use --resume or --overwrite: {output}"
                    )
                result = export_level(
                    slide,
                    level,
                    output,
                    source_mpp=source_mpp,
                    compression=args.compression,
                    compression_level=args.compression_level,
                    overwrite=args.overwrite,
                )
                entry = {
                    **expected,
                    "output_size_bytes": result["output_size_bytes"],
                    "output_sha256": result["output_sha256"],
                    "status": "complete",
                }
                store_entry(state, entry)
                existing_entries[key] = entry
                atomic_json(state_path, state)
                rows.append({**entry, "status": "exported"})
                verified_keys.add(key)

    if not args.dry_run:
        complete_rows = verified_complete_rows(output_dir, state, verified_keys)
        write_samples(output_dir, complete_rows)
        atomic_json(state_path, state)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        rows = run(args)
    except (MdsExportError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "slides": len({row["sample_id"] for row in rows}),
                "rows": rows,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
