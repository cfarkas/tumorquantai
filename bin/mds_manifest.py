#!/usr/bin/env python3
"""Shared schema and strict parser for TumorQuantAI tutorial MDS manifests."""

from __future__ import annotations

import csv
import io
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path


SCHEMA_VERSION = 2
SANITIZATION_PROFILE = "pixel-preserving-nonpixel-redaction-v2"
ALIAS_RE = re.compile(r"^TumorQuantAI_LymphomaWSI_[0-9]{3}$")
HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HEX_MD5_RE = re.compile(r"^[0-9a-f]{32}$")
REQUIRED_COLUMNS = {
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
}


class MdsManifestError(ValueError):
    """Raised when a public MDS manifest violates its declared schema."""


@dataclass(frozen=True)
class MdsManifestRow:
    schema_version: int
    alias: str
    source_mpp: float
    zenodo_filename: str
    dataset_path: str
    size_bytes: int
    sha256: str
    md5: str
    level_count: int
    level_dimensions: tuple[tuple[int, int], ...]
    pixel_stream_count: int
    pixel_sample_sha256: str
    pixel_full_sha256: str
    sanitization_profile: str


def _positive_int(value: object, field: str, source: str, line_number: int) -> int:
    try:
        parsed = int(str(value).strip())
    except ValueError as exc:
        raise MdsManifestError(
            f"Invalid {field} at {source}:{line_number}"
        ) from exc
    if parsed <= 0:
        raise MdsManifestError(f"Invalid {field} at {source}:{line_number}")
    return parsed


def _dimensions(
    value: object, level_count: int, source: str, line_number: int
) -> tuple[tuple[int, int], ...]:
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise MdsManifestError(
            f"Invalid level_dimensions JSON at {source}:{line_number}"
        ) from exc
    if not isinstance(payload, list) or len(payload) != level_count:
        raise MdsManifestError(
            f"level_dimensions must contain {level_count} levels at "
            f"{source}:{line_number}"
        )
    result: list[tuple[int, int]] = []
    for dimensions in payload:
        if (
            not isinstance(dimensions, list)
            or len(dimensions) != 2
            or any(type(item) is not int or item <= 0 for item in dimensions)
        ):
            raise MdsManifestError(
                f"Invalid level_dimensions entry at {source}:{line_number}"
            )
        result.append((dimensions[0], dimensions[1]))
    return tuple(result)


def parse_manifest_text(text: str, source: str) -> list[MdsManifestRow]:
    reader = csv.DictReader(io.StringIO(text))
    fields = set(reader.fieldnames or [])
    missing = REQUIRED_COLUMNS - fields
    if missing:
        raise MdsManifestError(
            f"MDS manifest {source} is missing: {', '.join(sorted(missing))}"
        )
    if fields != REQUIRED_COLUMNS or len(reader.fieldnames or []) != len(REQUIRED_COLUMNS):
        raise MdsManifestError(
            f"MDS manifest {source} contains unrecognized or duplicate columns"
        )
    rows: list[MdsManifestRow] = []
    seen_aliases: set[str] = set()
    seen_files: set[str] = set()
    mpp_values: set[str] = set()
    for line_number, raw in enumerate(reader, start=2):
        schema_version = _positive_int(
            raw.get("schema_version", ""), "schema_version", source, line_number
        )
        if schema_version != SCHEMA_VERSION:
            raise MdsManifestError(
                f"Unsupported schema_version at {source}:{line_number}"
            )
        alias = str(raw.get("alias", "")).strip()
        filename = str(raw.get("zenodo_filename", "")).strip()
        if not ALIAS_RE.fullmatch(alias) or alias in seen_aliases:
            raise MdsManifestError(
                f"Unsafe/duplicate alias at {source}:{line_number}"
            )
        if filename != f"{alias}.mds" or filename in seen_files:
            raise MdsManifestError(f"Unsafe MDS filename at {source}:{line_number}")
        size = _positive_int(raw.get("size_bytes", ""), "size_bytes", source, line_number)
        level_count = _positive_int(
            raw.get("level_count", ""), "level_count", source, line_number
        )
        if level_count < 3:
            raise MdsManifestError(
                f"MDS must contain at least three levels at {source}:{line_number}"
            )
        stream_count = _positive_int(
            raw.get("pixel_stream_count", ""),
            "pixel_stream_count",
            source,
            line_number,
        )
        try:
            source_mpp = float(str(raw.get("source_mpp", "")).strip())
        except ValueError as exc:
            raise MdsManifestError(
                f"Invalid source_mpp at {source}:{line_number}"
            ) from exc
        if not math.isfinite(source_mpp) or source_mpp <= 0:
            raise MdsManifestError(f"Invalid source_mpp at {source}:{line_number}")
        dimensions = _dimensions(
            raw.get("level_dimensions", ""), level_count, source, line_number
        )
        sha256 = str(raw.get("sha256", "")).strip().casefold()
        md5 = str(raw.get("md5", "")).strip().casefold()
        pixel_sha = str(raw.get("pixel_sample_sha256", "")).strip().casefold()
        pixel_full_sha = str(raw.get("pixel_full_sha256", "")).strip().casefold()
        if not HEX_SHA256_RE.fullmatch(sha256) or not HEX_MD5_RE.fullmatch(md5):
            raise MdsManifestError(f"Invalid checksum at {source}:{line_number}")
        if not HEX_SHA256_RE.fullmatch(pixel_sha):
            raise MdsManifestError(
                f"Invalid pixel_sample_sha256 at {source}:{line_number}"
            )
        if not HEX_SHA256_RE.fullmatch(pixel_full_sha):
            raise MdsManifestError(
                f"Invalid pixel_full_sha256 at {source}:{line_number}"
            )
        profile = str(raw.get("sanitization_profile", "")).strip()
        if profile != SANITIZATION_PROFILE:
            raise MdsManifestError(
                f"Unrecognized sanitization profile at {source}:{line_number}"
            )
        rows.append(
            MdsManifestRow(
                schema_version=schema_version,
                alias=alias,
                source_mpp=source_mpp,
                zenodo_filename=filename,
                dataset_path=f"raw/{alias}/1.mds",
                size_bytes=size,
                sha256=sha256,
                md5=md5,
                level_count=level_count,
                level_dimensions=dimensions,
                pixel_stream_count=stream_count,
                pixel_sample_sha256=pixel_sha,
                pixel_full_sha256=pixel_full_sha,
                sanitization_profile=profile,
            )
        )
        seen_aliases.add(alias)
        seen_files.add(filename)
        mpp_values.add(f"{source_mpp:.9f}")
    if not rows:
        raise MdsManifestError("MDS manifest is empty")
    if len(mpp_values) != 1:
        raise MdsManifestError("MDS manifest must use one consistent source_mpp")
    return rows


def load_manifest(path: Path) -> tuple[list[MdsManifestRow], str]:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_file():
        raise MdsManifestError(f"MDS manifest is not a regular file: {candidate}")
    resolved = candidate.resolve()
    text = resolved.read_text(encoding="utf-8-sig")
    return parse_manifest_text(text, str(resolved)), text
