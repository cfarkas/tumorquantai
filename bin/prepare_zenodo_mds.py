#!/usr/bin/env python3
"""Prepare privacy-sanitized MDS copies for the TumorQuantAI Zenodo tutorial.

The command copies selected MDS slides to stable public aliases, preserves every
internal ``DSI0`` pixel stream, and replaces every non-pixel OLE stream (labels,
macro images, and acquisition metadata). Source files are opened read-only and
are never modified. The output remains unpublished until a separate depositor
is run explicitly.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable

import olefile
from PIL import Image, ImageDraw

from mds_manifest import SANITIZATION_PROFILE, SCHEMA_VERSION
from mds_to_tiff import MdsPixels


ALIAS_RE = re.compile(r"^TumorQuantAI_LymphomaWSI_[0-9]{3}$")
FICLONE = 0x40049409
PUBLIC_COLUMNS = (
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
PRIVATE_COLUMNS = (
    "alias",
    "source_path",
    "staged_path",
    "original_size_bytes",
    "original_sha256",
    "sanitized_sha256",
    "sanitized_md5",
    "pixel_stream_count",
    "nonpixel_stream_count",
    "pixel_sample_sha256",
    "pixel_full_sha256",
    "source_markers_absent",
    "validation_status",
)


class MdsPreparationError(RuntimeError):
    """Raised when a source MDS cannot be staged safely."""


@dataclass(frozen=True)
class Selection:
    alias: str
    source_path: Path


@dataclass(frozen=True)
class OlePixelSignature:
    stream_count: int
    level_count: int
    sample_sha256: str
    full_sha256: str


def validate_mpp(value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise MdsPreparationError("--source-mpp must be finite and greater than zero")
    return value


def load_selection(
    mapping: Path,
    excluded_aliases: set[str],
    expected_count: int | None,
) -> list[Selection]:
    path = mapping.expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise MdsPreparationError(f"Private alias mapping is not a regular file: {path}")
    rows: list[Selection] = []
    seen_aliases: set[str] = set()
    seen_sources: set[Path] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        if "alias" not in fields or not ({"source_path", "source_mds_path"} & fields):
            raise MdsPreparationError(
                "Alias mapping requires alias and source_path or source_mds_path"
            )
        source_column = "source_path" if "source_path" in fields else "source_mds_path"
        for line_number, row in enumerate(reader, start=2):
            alias = str(row.get("alias", "")).strip()
            if alias in excluded_aliases:
                continue
            if not ALIAS_RE.fullmatch(alias):
                raise MdsPreparationError(f"Unsafe alias at {path}:{line_number}")
            candidate = Path(str(row.get(source_column, "")).strip()).expanduser().absolute()
            if candidate.is_symlink() or not candidate.is_file():
                raise MdsPreparationError(
                    f"MDS source is not a regular file at {path}:{line_number}"
                )
            source = candidate.resolve()
            if source.suffix.casefold() != ".mds":
                raise MdsPreparationError(f"Source is not .mds at {path}:{line_number}")
            if alias in seen_aliases or source in seen_sources:
                raise MdsPreparationError(f"Duplicate alias/source at {path}:{line_number}")
            seen_aliases.add(alias)
            seen_sources.add(source)
            rows.append(Selection(alias=alias, source_path=source))
    rows.sort(key=lambda item: item.alias)
    if not rows:
        raise MdsPreparationError("Selection is empty")
    if expected_count is not None and len(rows) != expected_count:
        raise MdsPreparationError(
            f"Expected {expected_count} selected MDS files, found {len(rows)}"
        )
    return rows


def clone_or_copy(source: Path, destination: Path) -> str:
    if destination.exists() or destination.is_symlink():
        raise MdsPreparationError(f"Staging destination already exists: {destination}")
    try:
        source_fd = os.open(source, os.O_RDONLY)
        try:
            destination_fd = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                stat.S_IRUSR | stat.S_IWUSR,
            )
            try:
                fcntl.ioctl(destination_fd, FICLONE, source_fd)
            finally:
                os.close(destination_fd)
        finally:
            os.close(source_fd)
        shutil.copystat(source, destination, follow_symlinks=False)
        os.chmod(destination, stat.S_IRUSR | stat.S_IWUSR)
        return "reflink"
    except OSError:
        if destination.exists():
            destination.unlink()
    shutil.copy2(source, destination, follow_symlinks=False)
    os.chmod(destination, stat.S_IRUSR | stat.S_IWUSR)
    return "copy"


def neutral_bytes(size: int, label: str) -> bytes:
    if size < 0:
        raise MdsPreparationError("Negative OLE stream size")
    marker = f"TumorQuantAI de-identified: {label}".encode("ascii")
    return (marker[:size] + b"\x00" * size)[:size]


def neutral_jpeg(original: bytes, stream_name: str) -> bytes:
    target_size = len(original)
    try:
        with Image.open(BytesIO(original)) as source:
            width, height = source.size
    except Exception as exc:
        raise MdsPreparationError(
            f"Embedded {stream_name} stream is not a readable image"
        ) from exc
    if width <= 0 or height <= 0:
        raise MdsPreparationError(f"Embedded {stream_name} has invalid dimensions")
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    text = "DE-IDENTIFIED"
    box = draw.textbbox((0, 0), text)
    x = max(4, (width - (box[2] - box[0])) // 2)
    y = max(4, (height - (box[3] - box[1])) // 2)
    draw.text((x, y), text, fill="black")
    encoded = BytesIO()
    image.save(encoded, format="JPEG", quality=45, optimize=True)
    payload = encoded.getvalue()
    if len(payload) > target_size:
        encoded = BytesIO()
        Image.new("RGB", (width, height), "white").save(
            encoded, format="JPEG", quality=20, optimize=True
        )
        payload = encoded.getvalue()
    if len(payload) > target_size:
        raise MdsPreparationError(
            f"Cannot create a same-size neutral {stream_name} JPEG"
        )
    return payload + b"\x00" * (target_size - len(payload))


def pixel_streams(ole: olefile.OleFileIO) -> list[tuple[str, ...]]:
    return sorted(
        (
            tuple(stream)
            for stream in ole.listdir(streams=True, storages=False)
            if len(stream) == 3 and stream[0] == "DSI0"
        ),
        key=lambda stream: tuple(part.casefold() for part in stream),
    )


def sampled_paths(streams: list[tuple[str, ...]]) -> list[tuple[str, ...]]:
    by_level: dict[str, list[tuple[str, ...]]] = {}
    for stream in streams:
        by_level.setdefault(stream[1], []).append(stream)
    selected: list[tuple[str, ...]] = []
    for level in sorted(by_level):
        values = by_level[level]
        for index in sorted({0, len(values) // 2, len(values) - 1}):
            selected.append(values[index])
    return selected


def ole_pixel_signature(ole: olefile.OleFileIO) -> OlePixelSignature:
    streams = pixel_streams(ole)
    if not streams:
        raise MdsPreparationError("MDS contains no DSI0 pixel streams")
    sampled = set(sampled_paths(streams))
    sample_digest = hashlib.sha256()
    full_digest = hashlib.sha256()
    for stream in streams:
        data = ole.openstream(list(stream)).read()
        encoded_name = "/".join(stream).encode("utf-8")
        encoded_size = len(data).to_bytes(8, "big")
        full_digest.update(encoded_name)
        full_digest.update(encoded_size)
        full_digest.update(data)
        if stream in sampled:
            sample_digest.update(encoded_name)
            sample_digest.update(encoded_size)
            sample_digest.update(data)
    return OlePixelSignature(
        stream_count=len(streams),
        level_count=len({stream[1] for stream in streams}),
        sample_sha256=sample_digest.hexdigest(),
        full_sha256=full_digest.hexdigest(),
    )


def sanitize_nonpixel_streams(path: Path) -> tuple[OlePixelSignature, int]:
    try:
        ole = olefile.OleFileIO(str(path), write_mode=True)
    except (OSError, IOError, olefile.OleFileError) as exc:
        raise MdsPreparationError(f"Cannot open staged MDS for sanitization: {path}") from exc
    try:
        signature = ole_pixel_signature(ole)
        nonpixel = [
            tuple(stream)
            for stream in ole.listdir(streams=True, storages=False)
            if not (len(stream) == 3 and stream[0] == "DSI0")
        ]
        if not nonpixel:
            raise MdsPreparationError(f"MDS has no associated metadata streams: {path}")
        for stream in nonpixel:
            original = ole.openstream(list(stream)).read()
            name = "/".join(stream)
            if len(stream) == 1 and stream[0].casefold() in {"label", "macro"}:
                replacement = neutral_jpeg(original, stream[0])
            else:
                replacement = neutral_bytes(len(original), name)
            if len(replacement) != len(original):
                raise MdsPreparationError(f"Replacement size mismatch for stream {name}")
            ole.write_stream(list(stream), replacement)
    finally:
        ole.close()
    return signature, len(nonpixel)


def validate_sanitized_ole(
    source: Path,
    staged: Path,
    expected: OlePixelSignature | None,
) -> tuple[int, list[list[int]], OlePixelSignature]:
    try:
        source_ole = olefile.OleFileIO(str(source))
        staged_ole = olefile.OleFileIO(str(staged))
    except (OSError, IOError, olefile.OleFileError) as exc:
        raise MdsPreparationError("Cannot reopen source/staged MDS for validation") from exc
    try:
        source_streams = pixel_streams(source_ole)
        staged_streams = pixel_streams(staged_ole)
        if source_streams != staged_streams:
            raise MdsPreparationError("DSI0 pixel stream names changed during sanitization")
        sampled = set(sampled_paths(source_streams))
        sample_digest = hashlib.sha256()
        full_digest = hashlib.sha256()
        for stream in source_streams:
            source_data = source_ole.openstream(list(stream)).read()
            staged_data = staged_ole.openstream(list(stream)).read()
            if source_data != staged_data:
                raise MdsPreparationError(
                    "DSI0 pixel bytes changed during sanitization"
                )
            encoded_name = "/".join(stream).encode("utf-8")
            encoded_size = len(staged_data).to_bytes(8, "big")
            full_digest.update(encoded_name)
            full_digest.update(encoded_size)
            full_digest.update(staged_data)
            if stream in sampled:
                sample_digest.update(encoded_name)
                sample_digest.update(encoded_size)
                sample_digest.update(staged_data)
        staged_signature = OlePixelSignature(
            stream_count=len(staged_streams),
            level_count=len({stream[1] for stream in staged_streams}),
            sample_sha256=sample_digest.hexdigest(),
            full_sha256=full_digest.hexdigest(),
        )
        if expected is not None and staged_signature != expected:
            raise MdsPreparationError(
                "Full DSI0 pixel signature changed during sanitization"
            )
        source_all_streams = source_ole.listdir(streams=True, storages=False)
        staged_all_streams = staged_ole.listdir(streams=True, storages=False)
        if source_all_streams != staged_all_streams:
            raise MdsPreparationError("OLE stream names changed during sanitization")
        for stream in staged_all_streams:
            if len(stream) == 3 and stream[0] == "DSI0":
                continue
            source_data = source_ole.openstream(stream).read()
            staged_data = staged_ole.openstream(stream).read()
            name = "/".join(stream)
            if len(stream) == 1 and stream[0].casefold() in {"label", "macro"}:
                expected_data = neutral_jpeg(source_data, stream[0])
            else:
                expected_data = neutral_bytes(len(source_data), name)
            if staged_data != expected_data:
                raise MdsPreparationError(
                    f"Non-pixel stream differs from deterministic neutral form: {name}"
                )
    finally:
        source_ole.close()
        staged_ole.close()

    with MdsPixels(staged) as pixels:
        dimensions = [[level.width, level.height] for level in pixels.levels]
        level_count = len(pixels.levels)
    if level_count != staged_signature.level_count:
        raise MdsPreparationError("MDS level count changed during sanitization")
    return level_count, dimensions, staged_signature


def marker_variants(source: Path) -> list[bytes]:
    parent = source.parent.name
    accession = parent.split("_")[0]
    values = {parent, accession, str(source), str(source.parent)}
    variants: set[bytes] = set()
    for value in values:
        if len(value) < 4:
            continue
        variants.add(value.encode("utf-8"))
        variants.add(value.encode("utf-16le"))
    return sorted(variants)


def digest_and_scan(path: Path, markers: Iterable[bytes]) -> tuple[int, str, str, bool]:
    marker_values = [value for value in markers if value]
    overlap = max((len(value) for value in marker_values), default=1) - 1
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    size = 0
    tail = b""
    marker_found = False
    before = path.stat()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            size += len(chunk)
            sha256.update(chunk)
            md5.update(chunk)
            searchable = tail + chunk
            if any(marker in searchable for marker in marker_values):
                marker_found = True
            tail = searchable[-overlap:] if overlap else b""
    after = path.stat()
    identity = lambda item: (
        item.st_dev,
        item.st_ino,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
    )
    if identity(before) != identity(after):
        raise MdsPreparationError(f"File changed while hashing: {path}")
    return size, sha256.hexdigest(), md5.hexdigest(), not marker_found


def atomic_csv(
    path: Path,
    columns: tuple[str, ...],
    rows: list[dict[str, object]],
    mode: int,
) -> None:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink():
        raise MdsPreparationError(f"Refusing symlink output: {candidate}")
    path = candidate.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=columns,
                extrasaction="ignore",
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def prepare_one(selection: Selection, staging_dir: Path, resume: bool) -> tuple[dict, dict]:
    remote_name = f"{selection.alias}.mds"
    destination = staging_dir / remote_name
    if destination.exists() and not resume:
        raise MdsPreparationError(f"Staged MDS already exists (use --resume): {destination}")
    source_size, source_sha, _, _ = digest_and_scan(selection.source_path, [])
    if not destination.exists():
        temporary = staging_dir / f".{remote_name}.preparing"
        if temporary.exists():
            raise MdsPreparationError(f"Incomplete staging file requires review: {temporary}")
        method = clone_or_copy(selection.source_path, temporary)
        try:
            source_signature, nonpixel_count = sanitize_nonpixel_streams(temporary)
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()
    else:
        method = "resumed"
        staged_ole = None
        try:
            staged_ole = olefile.OleFileIO(str(destination))
            nonpixel_count = len(
                [
                    stream
                    for stream in staged_ole.listdir(streams=True, storages=False)
                    if not (len(stream) == 3 and stream[0] == "DSI0")
                ]
            )
        finally:
            if staged_ole is not None:
                staged_ole.close()
        source_signature = None
    level_count, dimensions, validated_signature = validate_sanitized_ole(
        selection.source_path, destination, source_signature
    )
    source_signature = validated_signature
    size, sha256, md5, markers_absent = digest_and_scan(
        destination, marker_variants(selection.source_path)
    )
    if size != source_size:
        raise MdsPreparationError(f"Sanitized MDS size changed: {remote_name}")
    if not markers_absent:
        raise MdsPreparationError(f"Source identifier marker remains in: {remote_name}")
    public = {
        "schema_version": SCHEMA_VERSION,
        "alias": selection.alias,
        "zenodo_filename": remote_name,
        "size_bytes": size,
        "sha256": sha256,
        "md5": md5,
        "level_count": level_count,
        "level_dimensions": json.dumps(dimensions, separators=(",", ":")),
        "pixel_stream_count": source_signature.stream_count,
        "pixel_sample_sha256": source_signature.sample_sha256,
        "pixel_full_sha256": source_signature.full_sha256,
        "sanitization_profile": SANITIZATION_PROFILE,
    }
    private = {
        "alias": selection.alias,
        "source_path": str(selection.source_path),
        "staged_path": str(destination),
        "original_size_bytes": source_size,
        "original_sha256": source_sha,
        "sanitized_sha256": sha256,
        "sanitized_md5": md5,
        "pixel_stream_count": source_signature.stream_count,
        "nonpixel_stream_count": nonpixel_count,
        "pixel_sample_sha256": source_signature.sample_sha256,
        "pixel_full_sha256": source_signature.full_sha256,
        "source_markers_absent": True,
        "validation_status": f"validated-{method}",
    }
    return public, private


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alias-mapping", required=True, type=Path)
    parser.add_argument("--staging-dir", required=True, type=Path)
    parser.add_argument("--public-manifest", required=True, type=Path)
    parser.add_argument("--private-mapping", required=True, type=Path)
    parser.add_argument("--exclude-alias", action="append", default=[])
    parser.add_argument("--expected-count", type=int, default=21)
    parser.add_argument("--source-mpp", type=float, default=0.261780)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--limit", type=int)
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    source_mpp = validate_mpp(args.source_mpp)
    excluded = set(args.exclude_alias)
    invalid = sorted(alias for alias in excluded if not ALIAS_RE.fullmatch(alias))
    if invalid:
        raise MdsPreparationError("Invalid --exclude-alias value")
    selections = load_selection(args.alias_mapping, excluded, args.expected_count)
    if args.limit is not None:
        if args.limit <= 0:
            raise MdsPreparationError("--limit must be greater than zero")
        selections = selections[: args.limit]
    total_bytes = sum(item.source_path.stat().st_size for item in selections)
    plan = {
        "selected_files": len(selections),
        "total_size_bytes": total_bytes,
        "excluded_aliases": sorted(excluded),
        "source_mpp": source_mpp,
        "files": [f"{item.alias}.mds" for item in selections],
    }
    if args.plan:
        return {"plan": True, **plan}

    staging_candidate = args.staging_dir.expanduser().absolute()
    if staging_candidate.is_symlink():
        raise MdsPreparationError(f"Refusing symlink staging directory: {staging_candidate}")
    staging_dir = staging_candidate.resolve()
    staging_dir.mkdir(parents=True, exist_ok=True, mode=stat.S_IRWXU)
    os.chmod(staging_dir, stat.S_IRWXU)
    public_rows: list[dict[str, object]] = []
    private_rows: list[dict[str, object]] = []
    for index, selection in enumerate(selections, start=1):
        print(f"[{index}/{len(selections)}] preparing {selection.alias}", file=sys.stderr)
        public, private = prepare_one(selection, staging_dir, args.resume)
        public["source_mpp"] = source_mpp
        public_rows.append(public)
        private_rows.append(private)
    atomic_csv(args.public_manifest, PUBLIC_COLUMNS, public_rows, 0o644)
    atomic_csv(args.private_mapping, PRIVATE_COLUMNS, private_rows, 0o600)
    return {
        "plan": False,
        **plan,
        "sanitized_total_size_bytes": sum(int(row["size_bytes"]) for row in public_rows),
        "public_manifest": str(args.public_manifest.expanduser().resolve()),
        "private_mapping": str(args.private_mapping.expanduser().resolve()),
        "staging_dir": str(staging_dir),
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except (MdsPreparationError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
