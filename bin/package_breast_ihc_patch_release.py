#!/usr/bin/env python3
"""Create deterministic, local-only Zenodo upload files from a sanitized draft.

The input must be a completed output from prepare_breast_ihc_patch_release.py.
This command validates the full public roster, manifests, privacy screens, and
checksums before creating one deterministic ZIP64 archive per HMAC case alias.
It also creates a deterministic manifest bundle, a packaging report, and
upload-level SHA-256 and MD5 checksum files.

The sanitized source tree is retained and never modified. Packaging therefore
requires additional disk space, conservatively estimated before any archive is
written. This command has no network, upload, deposit, or publication feature.
"""

from __future__ import annotations

import argparse
import ctypes
import csv
import errno
import hashlib
import json
import math
import os
import re
import shutil
import stat
import sys
import tempfile
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable
from zipfile import ZIP_STORED, BadZipFile, ZipFile, ZipInfo

import numpy as np
import tifffile


SCHEMA_VERSION = 1
SANITIZATION_PROFILE = "tumorquantai-breast-ihc-rgb-tiff-minimal-v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MAX_ZENODO_UPLOAD_FILES = 100
AT_FDCWD = -100
RENAME_NOREPLACE = 1
FIXED_ZIP_DATETIME = (1980, 1, 1, 0, 0, 0)
DISK_SAFETY_MARGIN_BYTES = 64 * 1024 * 1024

PATCH_MANIFEST = "patch_manifest.csv"
CASE_MARKER_COUNTS = "case_marker_counts.csv"
VALIDATION_REPORT = "validation_report.json"
SOURCE_SHA256SUMS = "SHA256SUMS"
SOURCE_MD5SUMS = "MD5SUMS"
SOURCE_METADATA_FILES = (
    PATCH_MANIFEST,
    CASE_MARKER_COUNTS,
    VALIDATION_REPORT,
    SOURCE_SHA256SUMS,
    SOURCE_MD5SUMS,
)
PREPARATION_REPORT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "draft_only",
        "network_used",
        "upload_performed",
        "publication_performed",
        "case_count",
        "patch_count",
        "marker_patch_counts",
        "mpp_provenance_counts",
        "estimated_decoded_pixel_bytes",
        "sanitization_profile",
        "decoded_rgb_verification",
        "physical_scale_verification",
        "tiff_metadata_policy",
        "public_tables",
        "privacy_scope",
    }
)
PREPARATION_DECODED_RGB_VERIFICATION = "full-array SHA-256 equality"
PREPARATION_PHYSICAL_SCALE_VERIFICATION = (
    "Per-file microns_per_pixel encoded and verified in TIFF "
    "XResolution/YResolution with ResolutionUnit=centimeter"
)
PREPARATION_TIFF_METADATA_POLICY = "fixed structural-tag allowlist"
PREPARATION_PRIVACY_SCOPE = (
    "Source identifiers, private paths, and acquisition dates are not selected "
    "into public tables. TIFFs are re-encoded without source metadata. "
    "Independent visible-pixel and governance review remains required before "
    "publication."
)

ARCHIVE_MANIFEST = "archive_manifest.csv"
MANIFEST_BUNDLE = "TQA_BreastIHC_manifest_bundle.zip"
PACKAGING_REPORT = "packaging_report.json"
UPLOAD_SHA256SUMS = "SHA256SUMS"
UPLOAD_MD5SUMS = "MD5SUMS"
UPLOAD_AUXILIARY_FILES = (
    MANIFEST_BUNDLE,
    PACKAGING_REPORT,
    UPLOAD_SHA256SUMS,
    UPLOAD_MD5SUMS,
)

PATCH_COLUMNS = (
    "schema_version",
    "case_alias",
    "patch_alias",
    "marker",
    "public_path",
    "microns_per_pixel",
    "mpp_provenance",
    "width",
    "height",
    "channels",
    "dtype",
    "size_bytes",
    "sha256",
    "md5",
    "decoded_rgb_sha256",
    "sanitization_profile",
)
CASE_MARKER_COLUMNS = (
    "schema_version",
    "case_alias",
    "marker",
    "patch_count",
)
ARCHIVE_COLUMNS = (
    "schema_version",
    "case_alias",
    "archive_filename",
    "member_count",
    "uncompressed_bytes",
    "archive_size_bytes",
    "sha256",
    "md5",
)

CASE_ALIAS_RE = re.compile(r"^TQA_BC_[A-Z2-7]{20}$")
PATCH_ALIAS_RE = re.compile(r"^TQA_PATCH_[A-Z2-7]{20}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MD5_RE = re.compile(r"^[0-9a-f]{32}$")
ACCESSION_RE = re.compile(r"(?<![A-Za-z0-9])B[0-9]{2}-[0-9]{3,}(?![A-Za-z0-9])")
ISO_DATE_RE = re.compile(
    r"(?<![0-9])(?:19|20)[0-9]{2}[-/.][01][0-9][-/.][0-3][0-9](?![0-9])"
)
PRIVATE_PATH_RE = re.compile(
    r"(?:[A-Za-z]:\\(?:Users|Documents and Settings)\\|/(?:home|media|mnt|Users)/)",
    re.IGNORECASE,
)
CHECKSUM_LINE_RE = re.compile(r"^([0-9a-f]+)  ([^\r\n]+)$")

MARKERS = ("H&E", "ER", "PR", "HER2", "Ki-67")
MARKER_ORDER = {marker: index for index, marker in enumerate(MARKERS)}
MARKER_FILENAME = {
    "H&E": "HE",
    "ER": "ER",
    "PR": "PR",
    "HER2": "HER2",
    "Ki-67": "KI67",
}
MPP_PROVENANCE_VALUES = frozenset(
    {
        "measured_scale_bar_calibration",
        "measured_scale_bar_calibration_10x_binning_1x",
        "measured_scale_bar_calibration_10x_binning_3x",
        "measured_scale_bar_calibration_40x_binning_3x",
        "documented_magnification_extrapolation",
        (
            "documented_magnification_extrapolation_from_measured_10x_"
            "scale_bar_binning_1x"
        ),
        "externally_verified_calibration",
    }
)
ALLOWED_TIFF_TAGS = frozenset(
    {
        "ImageWidth",
        "ImageLength",
        "BitsPerSample",
        "Compression",
        "PhotometricInterpretation",
        "StripOffsets",
        "SamplesPerPixel",
        "RowsPerStrip",
        "StripByteCounts",
        "XResolution",
        "YResolution",
        "PlanarConfiguration",
        "ResolutionUnit",
        "SampleFormat",
    }
)


class PackagingError(RuntimeError):
    """Raised when a draft cannot be packaged without unsafe assumptions."""


@dataclass(frozen=True)
class FileDigest:
    size: int
    sha256: str
    md5: str


@dataclass(frozen=True)
class PatchRecord:
    case_alias: str
    patch_alias: str
    marker: str
    mpp_provenance: str
    public_path: str
    source_path: Path
    size: int
    sha256: str
    md5: str
    decoded_rgb_sha256: str
    decoded_pixel_bytes: int


@dataclass(frozen=True)
class ValidatedDraft:
    root: Path
    patches: tuple[PatchRecord, ...]
    cases: tuple[str, ...]
    source_file_digests: dict[str, FileDigest]
    source_tree_bytes: int
    estimated_additional_bytes: int


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def canonical_path(path: Path) -> Path:
    return path.expanduser().absolute().resolve(strict=False)


def stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def digest_file(
    path: Path, chunk_size: int = 8 * 1024 * 1024
) -> FileDigest:
    before = path.stat()
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            sha256.update(chunk)
            md5.update(chunk)
    after = path.stat()
    if stat_identity(before) != stat_identity(after):
        raise PackagingError(f"File changed while it was hashed: {path}")
    return FileDigest(after.st_size, sha256.hexdigest(), md5.hexdigest())


def validate_relative_path(value: str, label: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise PackagingError(f"Unsafe {label}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PackagingError(f"Unsafe {label}")
    normalized = path.as_posix()
    if normalized != value:
        raise PackagingError(f"Non-canonical {label}")
    return normalized


def validate_public_text(text: str, label: str) -> None:
    if PRIVATE_PATH_RE.search(text):
        raise PackagingError(f"Private absolute path detected in {label}")
    if ACCESSION_RE.search(text):
        raise PackagingError(f"Private accession-like identifier detected in {label}")
    if ISO_DATE_RE.search(text):
        raise PackagingError(f"Private date-like value detected in {label}")


def parse_positive_int(value: str, label: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise PackagingError(f"Invalid {label}") from exc
    if parsed <= 0:
        raise PackagingError(f"Invalid {label}")
    return parsed


def rational_value(value: object, label: str) -> float:
    if isinstance(value, tuple) and len(value) == 2:
        numerator, denominator = value
        if float(denominator) == 0:
            raise PackagingError(f"Sanitized TIFF has zero {label} denominator")
        result = float(numerator) / float(denominator)
    else:
        result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise PackagingError(f"Sanitized TIFF has invalid {label}")
    return result


def decoded_rgb_sha256_from_tiff(path: Path) -> str:
    try:
        with tifffile.TiffFile(path) as tif:
            if len(tif.pages) != 1:
                raise PackagingError("Sanitized TIFF must contain exactly one page")
            value = np.asarray(tif.pages[0].asarray())
        if value.ndim != 3:
            raise PackagingError("Sanitized TIFF does not decode to three dimensions")
        if value.shape[-1] == 3:
            rgb = value
        elif value.shape[0] == 3:
            rgb = np.moveaxis(value, 0, -1)
        else:
            raise PackagingError("Sanitized TIFF does not decode to three RGB channels")
        if rgb.dtype.kind != "u" or rgb.dtype.itemsize not in {1, 2}:
            raise PackagingError("Sanitized TIFF decodes to an unsupported RGB dtype")
        target_dtype = np.dtype("u1" if rgb.dtype.itemsize == 1 else "<u2")
        canonical = np.ascontiguousarray(rgb, dtype=target_dtype)
        digest = hashlib.sha256()
        digest.update(b"TumorQuantAI decoded RGB sha256 v1\x00")
        digest.update(str(canonical.shape[0]).encode("ascii"))
        digest.update(b"x")
        digest.update(str(canonical.shape[1]).encode("ascii"))
        digest.update(b"x3\x00")
        digest.update(
            ("uint8" if canonical.dtype.itemsize == 1 else "uint16-le").encode(
                "ascii"
            )
        )
        digest.update(b"\x00")
        digest.update(memoryview(canonical).cast("B"))
        return digest.hexdigest()
    except PackagingError:
        raise
    except (OSError, TypeError, ValueError, tifffile.TiffFileError) as exc:
        raise PackagingError(f"Cannot decode sanitized TIFF: {path.name}") from exc


def validate_sanitized_tiff_header(
    path: Path,
    width: int,
    height: int,
    dtype: str,
    microns_per_pixel: float,
) -> None:
    try:
        with tifffile.TiffFile(path) as tif:
            if len(tif.pages) != 1:
                raise PackagingError("Sanitized TIFF must contain exactly one page")
            page = tif.pages[0]
            tags = {str(tag.name) for tag in page.tags.values()}
            unexpected = sorted(tags - ALLOWED_TIFF_TAGS)
            if unexpected:
                raise PackagingError(
                    "Sanitized TIFF contains non-allowlisted tags: "
                    + ", ".join(unexpected)
                )
            observed_dtype = str(page.dtype)
            expected_dtype = "uint8" if dtype == "uint8" else "uint16"
            if (
                int(page.imagewidth) != width
                or int(page.imagelength) != height
                or int(page.samplesperpixel) != 3
                or getattr(page.photometric, "name", str(page.photometric)) != "RGB"
                or getattr(page.compression, "name", str(page.compression)) != "NONE"
                or getattr(page.planarconfig, "name", str(page.planarconfig)) != "CONTIG"
                or observed_dtype != expected_dtype
            ):
                raise PackagingError("Sanitized TIFF header does not match its manifest")
            unit = page.tags["ResolutionUnit"].value
            if int(unit) != 3:
                raise PackagingError("Sanitized TIFF resolution unit is not centimeter")
            x_ppcm = rational_value(page.tags["XResolution"].value, "XResolution")
            y_ppcm = rational_value(page.tags["YResolution"].value, "YResolution")
            embedded = (10_000.0 / x_ppcm, 10_000.0 / y_ppcm)
            if any(
                not math.isclose(
                    value,
                    microns_per_pixel,
                    rel_tol=2e-6,
                    abs_tol=2e-6,
                )
                for value in embedded
            ):
                raise PackagingError(
                    "Sanitized TIFF physical scale does not match its manifest"
                )
    except PackagingError:
        raise
    except (KeyError, OSError, TypeError, ValueError, tifffile.TiffFileError) as exc:
        raise PackagingError(f"Cannot validate sanitized TIFF header: {path.name}") from exc


def parse_patch_manifest(root: Path) -> list[PatchRecord]:
    path = root / PATCH_MANIFEST
    text = path.read_text(encoding="utf-8-sig")
    validate_public_text(text, PATCH_MANIFEST)
    rows: list[PatchRecord] = []
    seen_aliases: set[str] = set()
    seen_paths: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != PATCH_COLUMNS:
            raise PackagingError(f"{PATCH_MANIFEST} has an unexpected schema")
        for line_number, row in enumerate(reader, start=2):
            if str(row.get("schema_version", "")) != str(SCHEMA_VERSION):
                raise PackagingError(f"Invalid schema version at {PATCH_MANIFEST}:{line_number}")
            case_alias = str(row.get("case_alias", ""))
            patch_alias = str(row.get("patch_alias", ""))
            marker = str(row.get("marker", ""))
            mpp_provenance = str(row.get("mpp_provenance", ""))
            public_path = validate_relative_path(
                str(row.get("public_path", "")),
                f"public_path at {PATCH_MANIFEST}:{line_number}",
            )
            if not CASE_ALIAS_RE.fullmatch(case_alias):
                raise PackagingError(f"Unsafe case alias at {PATCH_MANIFEST}:{line_number}")
            if not PATCH_ALIAS_RE.fullmatch(patch_alias):
                raise PackagingError(f"Unsafe patch alias at {PATCH_MANIFEST}:{line_number}")
            if marker not in MARKERS:
                raise PackagingError(f"Non-English marker at {PATCH_MANIFEST}:{line_number}")
            if mpp_provenance not in MPP_PROVENANCE_VALUES:
                raise PackagingError(
                    f"Unsafe mpp_provenance at {PATCH_MANIFEST}:{line_number}"
                )
            expected_path = (
                f"patches/{case_alias}/{patch_alias}_{MARKER_FILENAME[marker]}.tif"
            )
            if public_path != expected_path:
                raise PackagingError(
                    f"Public TIFF path does not match aliases at {PATCH_MANIFEST}:{line_number}"
                )
            if patch_alias in seen_aliases or public_path in seen_paths:
                raise PackagingError(f"Duplicate patch at {PATCH_MANIFEST}:{line_number}")
            seen_aliases.add(patch_alias)
            seen_paths.add(public_path)
            size = parse_positive_int(
                str(row.get("size_bytes", "")),
                f"size_bytes at {PATCH_MANIFEST}:{line_number}",
            )
            sha256 = str(row.get("sha256", ""))
            md5 = str(row.get("md5", ""))
            if not SHA256_RE.fullmatch(sha256) or not MD5_RE.fullmatch(md5):
                raise PackagingError(f"Invalid digest at {PATCH_MANIFEST}:{line_number}")
            expected_decoded_rgb_sha256 = str(row.get("decoded_rgb_sha256", ""))
            if not SHA256_RE.fullmatch(expected_decoded_rgb_sha256):
                raise PackagingError(
                    f"Invalid decoded pixel digest at {PATCH_MANIFEST}:{line_number}"
                )
            if str(row.get("channels", "")) != "3":
                raise PackagingError(f"Invalid channels at {PATCH_MANIFEST}:{line_number}")
            dtype = str(row.get("dtype", ""))
            if dtype not in {"uint8", "uint16"}:
                raise PackagingError(f"Invalid dtype at {PATCH_MANIFEST}:{line_number}")
            width = parse_positive_int(
                str(row.get("width", "")),
                f"width at {PATCH_MANIFEST}:{line_number}",
            )
            height = parse_positive_int(
                str(row.get("height", "")),
                f"height at {PATCH_MANIFEST}:{line_number}",
            )
            try:
                mpp = float(str(row.get("microns_per_pixel", "")))
            except ValueError as exc:
                raise PackagingError(
                    f"Invalid microns_per_pixel at {PATCH_MANIFEST}:{line_number}"
                ) from exc
            if not math.isfinite(mpp) or not 0.05 <= mpp <= 10.0:
                raise PackagingError(
                    f"Invalid microns_per_pixel at {PATCH_MANIFEST}:{line_number}"
                )
            if str(row.get("sanitization_profile", "")) != SANITIZATION_PROFILE:
                raise PackagingError(
                    f"Unexpected sanitization profile at {PATCH_MANIFEST}:{line_number}"
                )
            source = root / public_path
            if source.is_symlink() or not source.is_file():
                raise PackagingError(f"Public TIFF is missing or unsafe: {public_path}")
            validate_sanitized_tiff_header(
                source,
                width,
                height,
                dtype,
                mpp,
            )
            if decoded_rgb_sha256_from_tiff(source) != expected_decoded_rgb_sha256:
                raise PackagingError(
                    f"Decoded RGB digest does not match {PATCH_MANIFEST}: {public_path}"
                )
            rows.append(
                PatchRecord(
                    case_alias=case_alias,
                    patch_alias=patch_alias,
                    marker=marker,
                    mpp_provenance=mpp_provenance,
                    public_path=public_path,
                    source_path=source,
                    size=size,
                    sha256=sha256,
                    md5=md5,
                    decoded_rgb_sha256=expected_decoded_rgb_sha256,
                    decoded_pixel_bytes=(
                        width * height * 3 * (1 if dtype == "uint8" else 2)
                    ),
                )
            )
    if not rows:
        raise PackagingError(f"{PATCH_MANIFEST} contains no patches")
    rows.sort(
        key=lambda item: (
            item.case_alias,
            MARKER_ORDER[item.marker],
            item.patch_alias,
        )
    )
    return rows


def validate_case_marker_counts(root: Path, patches: list[PatchRecord]) -> None:
    path = root / CASE_MARKER_COUNTS
    text = path.read_text(encoding="utf-8-sig")
    validate_public_text(text, CASE_MARKER_COUNTS)
    observed: list[tuple[str, str, int]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CASE_MARKER_COLUMNS:
            raise PackagingError(f"{CASE_MARKER_COUNTS} has an unexpected schema")
        for line_number, row in enumerate(reader, start=2):
            if str(row.get("schema_version", "")) != str(SCHEMA_VERSION):
                raise PackagingError(
                    f"Invalid schema version at {CASE_MARKER_COUNTS}:{line_number}"
                )
            alias = str(row.get("case_alias", ""))
            marker = str(row.get("marker", ""))
            if not CASE_ALIAS_RE.fullmatch(alias) or marker not in MARKERS:
                raise PackagingError(f"Unsafe row at {CASE_MARKER_COUNTS}:{line_number}")
            count = parse_positive_int(
                str(row.get("patch_count", "")),
                f"patch_count at {CASE_MARKER_COUNTS}:{line_number}",
            )
            observed.append((alias, marker, count))
    expected_counts = Counter((patch.case_alias, patch.marker) for patch in patches)
    expected = [
        (alias, marker, count)
        for (alias, marker), count in sorted(
            expected_counts.items(),
            key=lambda value: (value[0][0], MARKER_ORDER[value[0][1]]),
        )
    ]
    if observed != expected:
        raise PackagingError(f"{CASE_MARKER_COUNTS} does not match {PATCH_MANIFEST}")


def validate_preparation_report(
    root: Path,
    patches: list[PatchRecord],
    expected_cases: int,
    expected_files: int,
) -> None:
    path = root / VALIDATION_REPORT
    text = path.read_text(encoding="utf-8")
    validate_public_text(text, VALIDATION_REPORT)
    try:
        report = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PackagingError(f"{VALIDATION_REPORT} is not valid JSON") from exc
    if not isinstance(report, dict):
        raise PackagingError(f"{VALIDATION_REPORT} must be a JSON object")
    observed_keys = set(report)
    if observed_keys != PREPARATION_REPORT_KEYS:
        unexpected = sorted(observed_keys - PREPARATION_REPORT_KEYS)
        missing = sorted(PREPARATION_REPORT_KEYS - observed_keys)
        details: list[str] = []
        if unexpected:
            details.append("unexpected keys: " + ", ".join(unexpected))
        if missing:
            details.append("missing keys: " + ", ".join(missing))
        raise PackagingError(
            f"{VALIDATION_REPORT} has an invalid key roster ("
            + "; ".join(details)
            + ")"
        )
    required = {
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "draft_only": True,
        "network_used": False,
        "upload_performed": False,
        "publication_performed": False,
        "case_count": expected_cases,
        "patch_count": expected_files,
        "sanitization_profile": SANITIZATION_PROFILE,
        "estimated_decoded_pixel_bytes": sum(
            patch.decoded_pixel_bytes for patch in patches
        ),
        "decoded_rgb_verification": PREPARATION_DECODED_RGB_VERIFICATION,
        "physical_scale_verification": PREPARATION_PHYSICAL_SCALE_VERIFICATION,
        "tiff_metadata_policy": PREPARATION_TIFF_METADATA_POLICY,
        "public_tables": [PATCH_MANIFEST, CASE_MARKER_COUNTS],
        "privacy_scope": PREPARATION_PRIVACY_SCOPE,
    }
    for key, value in required.items():
        if report.get(key) != value:
            raise PackagingError(f"{VALIDATION_REPORT} has invalid {key}")
    marker_counts = Counter(patch.marker for patch in patches)
    expected_marker_counts = {
        marker: marker_counts.get(marker, 0) for marker in MARKERS
    }
    if report.get("marker_patch_counts") != expected_marker_counts:
        raise PackagingError(
            f"{VALIDATION_REPORT} marker counts do not match {PATCH_MANIFEST}"
        )
    provenance_counts = Counter(patch.mpp_provenance for patch in patches)
    expected_provenance_counts = {
        provenance: provenance_counts[provenance]
        for provenance in sorted(provenance_counts)
    }
    if report.get("mpp_provenance_counts") != expected_provenance_counts:
        raise PackagingError(
            f"{VALIDATION_REPORT} MPP provenance counts do not match "
            f"{PATCH_MANIFEST}"
        )


def parse_checksum_file(path: Path, algorithm: str) -> dict[str, str]:
    expected_length = 64 if algorithm == "sha256" else 32
    text = path.read_text(encoding="utf-8")
    validate_public_text(text, path.name)
    result: dict[str, str] = {}
    previous = ""
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = CHECKSUM_LINE_RE.fullmatch(line)
        if match is None or len(match.group(1)) != expected_length:
            raise PackagingError(f"Malformed checksum line at {path.name}:{line_number}")
        digest, relative = match.groups()
        validate_relative_path(relative, f"checksum path at {path.name}:{line_number}")
        if relative in result or (previous and relative <= previous):
            raise PackagingError(f"Checksums are duplicated or unsorted in {path.name}")
        result[relative] = digest
        previous = relative
    if not result:
        raise PackagingError(f"{path.name} is empty")
    return result


def validate_source_roster(root: Path, patches: list[PatchRecord]) -> None:
    expected_files = set(SOURCE_METADATA_FILES)
    expected_files.update(patch.public_path for patch in patches)
    expected_dirs = {"patches"}
    expected_dirs.update(f"patches/{patch.case_alias}" for patch in patches)
    actual_files: set[str] = set()
    actual_dirs: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        validate_relative_path(relative, "source draft path")
        if path.is_symlink():
            raise PackagingError(f"Symlink found in sanitized draft: {relative}")
        if path.is_file():
            actual_files.add(relative)
        elif path.is_dir():
            actual_dirs.add(relative)
        else:
            raise PackagingError(f"Non-regular entry found in sanitized draft: {relative}")
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        extra = sorted(actual_files - expected_files)
        raise PackagingError(
            "Sanitized draft file roster mismatch "
            f"(missing={len(missing)}, extra={len(extra)})"
        )
    if actual_dirs != expected_dirs:
        raise PackagingError("Sanitized draft directory roster is not allowlisted")


def conservative_disk_estimate(payload_bytes: int, metadata_bytes: int) -> int:
    compression_overhead = max(
        DISK_SAFETY_MARGIN_BYTES,
        math.ceil(payload_bytes * 0.01),
    )
    return payload_bytes + metadata_bytes + compression_overhead


def ensure_upload_file_limit(case_count: int) -> int:
    upload_count = case_count + len(UPLOAD_AUXILIARY_FILES)
    if upload_count > MAX_ZENODO_UPLOAD_FILES:
        raise PackagingError(
            f"Packaging would create {upload_count} upload files; "
            f"Zenodo limit is {MAX_ZENODO_UPLOAD_FILES}"
        )
    return upload_count


def validate_completed_draft(
    source_draft: Path,
    expected_cases: int,
    expected_files: int,
) -> ValidatedDraft:
    if expected_cases <= 0 or expected_files <= 0:
        raise PackagingError("--expected-cases and --expected-files must be > 0")
    candidate = source_draft.expanduser().absolute()
    if candidate.is_symlink():
        raise PackagingError("Refusing a symlink source draft")
    root = candidate.resolve(strict=False)
    if not root.is_dir():
        raise PackagingError("Source draft is not a directory")
    for name in SOURCE_METADATA_FILES:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise PackagingError(f"Completed draft is missing safe metadata file: {name}")

    patches = parse_patch_manifest(root)
    cases = tuple(sorted({patch.case_alias for patch in patches}))
    if len(patches) != expected_files:
        raise PackagingError(
            f"Expected {expected_files} sanitized TIFFs, found {len(patches)}"
        )
    if len(cases) != expected_cases:
        raise PackagingError(f"Expected {expected_cases} cases, found {len(cases)}")
    ensure_upload_file_limit(len(cases))
    validate_source_roster(root, patches)
    validate_case_marker_counts(root, patches)
    validate_preparation_report(root, patches, expected_cases, expected_files)

    source_payload_paths = {
        patch.public_path for patch in patches
    } | {PATCH_MANIFEST, CASE_MARKER_COUNTS, VALIDATION_REPORT}
    computed: dict[str, FileDigest] = {}
    for relative in sorted(source_payload_paths):
        computed[relative] = digest_file(root / relative)
    for patch in patches:
        observed = computed[patch.public_path]
        if (
            observed.size != patch.size
            or observed.sha256 != patch.sha256
            or observed.md5 != patch.md5
        ):
            raise PackagingError(
                f"TIFF digest does not match {PATCH_MANIFEST}: {patch.public_path}"
            )
    sha256s = parse_checksum_file(root / SOURCE_SHA256SUMS, "sha256")
    md5s = parse_checksum_file(root / SOURCE_MD5SUMS, "md5")
    if set(sha256s) != source_payload_paths or set(md5s) != source_payload_paths:
        raise PackagingError("Completed draft checksum roster is not exact")
    for relative, observed in computed.items():
        if sha256s[relative] != observed.sha256 or md5s[relative] != observed.md5:
            raise PackagingError(f"Completed draft checksum mismatch: {relative}")

    source_file_digests = dict(computed)
    source_file_digests[SOURCE_SHA256SUMS] = digest_file(root / SOURCE_SHA256SUMS)
    source_file_digests[SOURCE_MD5SUMS] = digest_file(root / SOURCE_MD5SUMS)
    source_tree_bytes = sum(
        digest.size for digest in source_file_digests.values()
    )
    tiff_bytes = sum(patch.size for patch in patches)
    metadata_bytes = source_tree_bytes - tiff_bytes
    return ValidatedDraft(
        root=root,
        patches=tuple(patches),
        cases=cases,
        source_file_digests=source_file_digests,
        source_tree_bytes=source_tree_bytes,
        estimated_additional_bytes=conservative_disk_estimate(
            tiff_bytes,
            metadata_bytes,
        ),
    )


def validate_output_location(source: Path, package_output: Path) -> Path:
    candidate = package_output.expanduser().absolute()
    if candidate.is_symlink():
        raise PackagingError("Refusing a symlink package output")
    output = candidate.resolve(strict=False)
    repository = REPOSITORY_ROOT.resolve()
    if output.exists():
        raise PackagingError(f"Package output already exists; refusing overwrite: {output}")
    if is_within(output, repository):
        raise PackagingError("--package-output must be outside the repository")
    if output == source or is_within(output, source) or is_within(source, output):
        raise PackagingError("Package output and source draft must be separate trees")
    return output


def safe_summary(
    draft: ValidatedDraft,
    status: str,
) -> dict[str, object]:
    upload_count = ensure_upload_file_limit(len(draft.cases))
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "draft_only": True,
        "network_used": False,
        "upload_performed": False,
        "publication_performed": False,
        "source_retained": True,
        "case_count": len(draft.cases),
        "patch_count": len(draft.patches),
        "case_archive_count": len(draft.cases),
        "upload_file_count": upload_count,
        "maximum_upload_file_count": MAX_ZENODO_UPLOAD_FILES,
        "source_tree_bytes": draft.source_tree_bytes,
        "estimated_additional_disk_bytes": draft.estimated_additional_bytes,
        "archive_compression": "ZIP_STORED",
        "disk_tradeoff": (
            "The sanitized source is retained and ZIP_STORED duplicates its TIFF "
            "bytes. Exact archive bytes are scoped to identical validated inputs "
            "under the same supported packager tool/runtime."
        ),
        "zip_member_timestamp": "1980-01-01T00:00:00",
    }


def deterministic_zip_info(name: str, size: int, force_zip64: bool) -> ZipInfo:
    validate_relative_path(name, "ZIP member path")
    info = ZipInfo(name, date_time=FIXED_ZIP_DATETIME)
    info.compress_type = ZIP_STORED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.internal_attr = 0
    info.comment = b""
    info.extra = b""
    info.file_size = size
    if force_zip64:
        info.extract_version = max(info.extract_version, 45)
        info.create_version = max(info.create_version, 45)
    return info


def copy_member(
    archive: ZipFile,
    info: ZipInfo,
    source: Path,
    expected: FileDigest,
    force_zip64: bool,
) -> None:
    before = source.stat()
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    crc = 0
    size = 0
    with source.open("rb") as input_handle:
        with archive.open(info, mode="w", force_zip64=force_zip64) as output_handle:
            for chunk in iter(lambda: input_handle.read(8 * 1024 * 1024), b""):
                output_handle.write(chunk)
                sha256.update(chunk)
                md5.update(chunk)
                crc = zlib.crc32(chunk, crc)
                size += len(chunk)
    after = source.stat()
    if stat_identity(before) != stat_identity(after):
        raise PackagingError(f"Source changed while archiving: {source}")
    if (
        size != expected.size
        or sha256.hexdigest() != expected.sha256
        or md5.hexdigest() != expected.md5
    ):
        raise PackagingError(f"Source digest changed while archiving: {source}")
    if archive.getinfo(info.filename).CRC != (crc & 0xFFFFFFFF):
        raise PackagingError(f"ZIP writer CRC mismatch: {info.filename}")


def create_zip(
    destination: Path,
    members: list[tuple[str, Path, FileDigest]],
    force_zip64: bool,
) -> None:
    if destination.exists() or destination.is_symlink():
        raise PackagingError(f"Archive already exists: {destination.name}")
    with ZipFile(
        destination,
        mode="x",
        compression=ZIP_STORED,
        allowZip64=True,
        strict_timestamps=True,
    ) as archive:
        archive.comment = b""
        for name, source, expected in sorted(members, key=lambda item: item[0]):
            info = deterministic_zip_info(name, expected.size, force_zip64)
            copy_member(archive, info, source, expected, force_zip64)
    os.chmod(destination, 0o644)
    with destination.open("rb") as handle:
        os.fsync(handle.fileno())


def verify_zip(
    archive_path: Path,
    expected: dict[str, FileDigest],
    require_zip64: bool,
) -> None:
    try:
        with ZipFile(archive_path, mode="r") as archive:
            if archive.comment:
                raise PackagingError(f"ZIP comment is not allowed: {archive_path.name}")
            infos = archive.infolist()
            observed_names = [info.filename for info in infos]
            expected_names = sorted(expected)
            if observed_names != expected_names or len(set(observed_names)) != len(infos):
                raise PackagingError(f"ZIP member roster mismatch: {archive_path.name}")
            for info in infos:
                target = expected[info.filename]
                if (
                    info.is_dir()
                    or info.date_time != FIXED_ZIP_DATETIME
                    or info.compress_type != ZIP_STORED
                    or info.file_size != target.size
                ):
                    raise PackagingError(
                        f"ZIP member metadata mismatch: {archive_path.name}:{info.filename}"
                    )
                unix_mode = info.external_attr >> 16
                if (
                    info.create_system != 3
                    or not stat.S_ISREG(unix_mode)
                    or stat.S_IMODE(unix_mode) != 0o644
                    or info.comment
                    or info.flag_bits & 0x1
                ):
                    raise PackagingError(
                        f"ZIP member permissions/flags mismatch: "
                        f"{archive_path.name}:{info.filename}"
                    )
                if require_zip64 and info.extract_version < 45:
                    raise PackagingError(
                        f"ZIP64 was not forced: {archive_path.name}:{info.filename}"
                    )
                sha256 = hashlib.sha256()
                md5 = hashlib.md5(usedforsecurity=False)
                crc = 0
                size = 0
                with archive.open(info, mode="r") as handle:
                    for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                        sha256.update(chunk)
                        md5.update(chunk)
                        crc = zlib.crc32(chunk, crc)
                        size += len(chunk)
                if (
                    size != target.size
                    or sha256.hexdigest() != target.sha256
                    or md5.hexdigest() != target.md5
                    or (crc & 0xFFFFFFFF) != info.CRC
                ):
                    raise PackagingError(
                        f"ZIP member verification failed: {archive_path.name}:{info.filename}"
                    )
    except (BadZipFile, OSError, RuntimeError) as exc:
        if isinstance(exc, PackagingError):
            raise
        raise PackagingError(f"Cannot verify ZIP archive: {archive_path.name}") from exc


def write_csv(
    path: Path,
    columns: tuple[str, ...],
    rows: Iterable[dict[str, object]],
) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
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
    except Exception:
        if path.exists():
            path.unlink()
        raise
    os.chmod(path, 0o644)


def write_text(path: Path, text: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        if path.exists():
            path.unlink()
        raise
    os.chmod(path, 0o644)


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def linux_rename_directory_noreplace(source: Path, destination: Path) -> bool:
    """Atomically rename a directory without replacing an existing entry.

    Return False only when the operating system or C library does not expose
    the required Linux primitive. All other failures are raised.
    """
    if not sys.platform.startswith("linux"):
        return False
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        return False
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        AT_FDCWD,
        os.fsencode(source),
        AT_FDCWD,
        os.fsencode(destination),
        RENAME_NOREPLACE,
    )
    if result == 0:
        return True
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise PackagingError(
            "Package output appeared before final placement; refusing overwrite"
        )
    unavailable = {
        errno.ENOSYS,
        errno.EINVAL,
        getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
        errno.EOPNOTSUPP,
    }
    if error_number in unavailable:
        return False
    raise OSError(
        error_number,
        os.strerror(error_number),
        os.fspath(destination),
    )


def atomic_publish_directory_no_replace(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise PackagingError("Final staging directory is missing or unsafe")
    if linux_rename_directory_noreplace(source, destination):
        fsync_directory(destination.parent)
        return
    raise PackagingError(
        "Atomic no-replace directory publication is unavailable on this platform; "
        "refusing a non-atomic fallback"
    )


def package_release(
    source_draft: Path,
    package_output: Path,
    expected_cases: int,
    expected_files: int,
    dry_run: bool = False,
) -> dict[str, object]:
    source = canonical_path(source_draft)
    output = validate_output_location(source, package_output)
    draft = validate_completed_draft(
        source,
        expected_cases,
        expected_files,
    )
    if dry_run:
        return safe_summary(draft, "planned")

    output.parent.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(output.parent).free
    if free_bytes < draft.estimated_additional_bytes:
        raise PackagingError(
            "Insufficient free space for retained-source packaging: "
            f"need at least {draft.estimated_additional_bytes} bytes"
        )
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}.package-",
            dir=output.parent,
        )
    )
    os.chmod(staging, 0o700)
    try:
        patches_by_case: dict[str, list[PatchRecord]] = defaultdict(list)
        for patch in draft.patches:
            patches_by_case[patch.case_alias].append(patch)

        archive_rows: list[dict[str, object]] = []
        case_archive_digests: dict[str, FileDigest] = {}
        for case_alias in draft.cases:
            archive_name = f"{case_alias}.zip"
            archive_path = staging / archive_name
            members = [
                (
                    patch.public_path,
                    patch.source_path,
                    FileDigest(patch.size, patch.sha256, patch.md5),
                )
                for patch in patches_by_case[case_alias]
            ]
            create_zip(archive_path, members, force_zip64=True)
            expected_members = {
                name: digest for name, _source, digest in members
            }
            verify_zip(archive_path, expected_members, require_zip64=True)
            archive_digest = digest_file(archive_path)
            case_archive_digests[archive_name] = archive_digest
            archive_rows.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "case_alias": case_alias,
                    "archive_filename": archive_name,
                    "member_count": len(members),
                    "uncompressed_bytes": sum(
                        digest.size for _name, _source, digest in members
                    ),
                    "archive_size_bytes": archive_digest.size,
                    "sha256": archive_digest.sha256,
                    "md5": archive_digest.md5,
                }
            )

        archive_manifest_path = staging / ARCHIVE_MANIFEST
        write_csv(archive_manifest_path, ARCHIVE_COLUMNS, archive_rows)
        archive_manifest_digest = digest_file(archive_manifest_path)
        bundle_members: list[tuple[str, Path, FileDigest]] = [
            (
                name,
                draft.root / name,
                draft.source_file_digests[name],
            )
            for name in SOURCE_METADATA_FILES
        ]
        bundle_members.append(
            (
                ARCHIVE_MANIFEST,
                archive_manifest_path,
                archive_manifest_digest,
            )
        )
        bundle_path = staging / MANIFEST_BUNDLE
        create_zip(bundle_path, bundle_members, force_zip64=False)
        verify_zip(
            bundle_path,
            {name: digest for name, _source, digest in bundle_members},
            require_zip64=False,
        )
        archive_manifest_path.unlink()
        bundle_digest = digest_file(bundle_path)

        report = safe_summary(draft, "packaged")
        report.update(
            {
                "case_archive_bytes": sum(
                    digest.size for digest in case_archive_digests.values()
                ),
                "manifest_bundle_bytes": bundle_digest.size,
                "manifest_bundle": MANIFEST_BUNDLE,
                "manifest_bundle_members": sorted(
                    [*SOURCE_METADATA_FILES, ARCHIVE_MANIFEST]
                ),
                "verification": (
                    "Every ZIP roster, member size, CRC32, SHA-256, and MD5 was "
                    "verified after writing; TIFF member bytes are lossless."
                ),
                "privacy_scope": (
                    "Public schemas, text patterns, file rosters, and TIFF metadata "
                    "tags were validated. Independent visible-pixel and governance "
                    "review remains required before publication."
                ),
            }
        )
        write_text(
            staging / PACKAGING_REPORT,
            json.dumps(report, indent=2, sort_keys=True) + "\n",
        )

        checksum_payloads: dict[str, FileDigest] = dict(case_archive_digests)
        checksum_payloads[MANIFEST_BUNDLE] = bundle_digest
        checksum_payloads[PACKAGING_REPORT] = digest_file(staging / PACKAGING_REPORT)
        write_text(
            staging / UPLOAD_SHA256SUMS,
            "".join(
                f"{checksum_payloads[name].sha256}  {name}\n"
                for name in sorted(checksum_payloads)
            ),
        )
        write_text(
            staging / UPLOAD_MD5SUMS,
            "".join(
                f"{checksum_payloads[name].md5}  {name}\n"
                for name in sorted(checksum_payloads)
            ),
        )
        expected_output_files = set(case_archive_digests) | set(UPLOAD_AUXILIARY_FILES)
        actual_output_files = {
            path.relative_to(staging).as_posix()
            for path in staging.iterdir()
            if path.is_file()
        }
        if actual_output_files != expected_output_files or any(
            path.is_symlink() or not path.is_file() for path in staging.iterdir()
        ):
            raise PackagingError("Final upload roster is not exact and allowlisted")
        if len(actual_output_files) > MAX_ZENODO_UPLOAD_FILES:
            raise PackagingError("Final upload roster exceeds Zenodo file limit")
        final_sha256 = parse_checksum_file(staging / UPLOAD_SHA256SUMS, "sha256")
        final_md5 = parse_checksum_file(staging / UPLOAD_MD5SUMS, "md5")
        if set(final_sha256) != set(checksum_payloads) or set(final_md5) != set(
            checksum_payloads
        ):
            raise PackagingError("Upload checksum roster is not exact")
        for name, expected in checksum_payloads.items():
            observed = digest_file(staging / name)
            if (
                observed != expected
                or final_sha256[name] != observed.sha256
                or final_md5[name] != observed.md5
            ):
                raise PackagingError(f"Final upload checksum mismatch: {name}")

        validate_source_roster(draft.root, list(draft.patches))
        atomic_publish_directory_no_replace(staging, output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)

    result = safe_summary(draft, "packaged")
    result["package_output"] = str(output)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-draft",
        required=True,
        type=Path,
        help="Completed sanitized output from prepare_breast_ihc_patch_release.py",
    )
    parser.add_argument(
        "--package-output",
        required=True,
        type=Path,
        help="New local Zenodo-ready package directory outside the repository",
    )
    parser.add_argument("--expected-cases", required=True, type=int)
    parser.add_argument("--expected-files", required=True, type=int)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the complete draft and report disk/upload plans without writing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = package_release(
            source_draft=args.source_draft,
            package_output=args.package_output,
            expected_cases=args.expected_cases,
            expected_files=args.expected_files,
            dry_run=args.dry_run,
        )
    except (PackagingError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
