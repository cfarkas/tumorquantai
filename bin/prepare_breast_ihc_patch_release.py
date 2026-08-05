#!/usr/bin/env python3
"""Prepare a privacy-sanitized, local-only breast IHC patch release.

This command has no network, deposit, upload, or publication capability.  It
reads an explicit private selection manifest, derives non-sequential public
aliases with HMAC-SHA256, re-encodes RGB TIFF pixels into metadata-minimal TIFF
files while retaining calibrated microns-per-pixel in standard TIFF resolution
tags, verifies the decoded pixels and embedded scale, and writes deterministic
public manifests plus a separate protected linkage table.

The output is only a draft staging tree.  Successful preparation is not a
substitute for institutional privacy, pixel-content, ethics, rights, or release
review.

The private source CSV must contain case_id, marker, field_id, source_path,
include, microns_per_pixel, and mpp_provenance. Extra columns are deliberately
not selected into either public table.
"""

from __future__ import annotations

import argparse
import base64
import csv
import ctypes
import errno
import hashlib
import hmac
import json
import math
import os
import re
import shutil
import stat
import sys
import tempfile
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import tifffile


SCHEMA_VERSION = 1
SANITIZATION_PROFILE = "tumorquantai-breast-ihc-rgb-tiff-minimal-v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SECRET_MINIMUM_BYTES = 32
DISK_SAFETY_MARGIN_BYTES = 64 * 1024 * 1024
AT_FDCWD = -100
RENAME_NOREPLACE = 1
MPP_RELATIVE_TOLERANCE = 2e-6
MPP_ABSOLUTE_TOLERANCE = 2e-6
MIN_EMBEDDED_MPP = 0.05
MAX_EMBEDDED_MPP = 10.0
MICRONS_PER_CENTIMETER = 10_000.0

PATCH_MANIFEST = "patch_manifest.csv"
CASE_MARKER_COUNTS = "case_marker_counts.csv"
VALIDATION_REPORT = "validation_report.json"
SHA256SUMS = "SHA256SUMS"
MD5SUMS = "MD5SUMS"

REQUIRED_SOURCE_COLUMNS = frozenset(
    {
        "case_id",
        "marker",
        "field_id",
        "source_path",
        "include",
        "microns_per_pixel",
        "mpp_provenance",
    }
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
PRIVATE_COLUMNS = (
    "schema_version",
    "case_alias",
    "patch_alias",
    "case_id",
    "field_id",
    "original_marker",
    "marker",
    "original_mpp_provenance",
    "mpp_provenance",
    "source_path",
    "source_size_bytes",
    "source_sha256",
    "public_path",
    "public_size_bytes",
    "public_sha256",
    "decoded_rgb_sha256",
    "validation_status",
)

CASE_ALIAS_RE = re.compile(r"^TQA_BC_[A-Z2-7]{20}$")
PATCH_ALIAS_RE = re.compile(r"^TQA_PATCH_[A-Z2-7]{20}$")
ISO_DATE_RE = re.compile(r"(?<![0-9])(?:19|20)[0-9]{2}[-/.][01][0-9][-/.][0-3][0-9](?![0-9])")
PRIVATE_PATH_RE = re.compile(
    r"(?:[A-Za-z]:\\(?:Users|Documents and Settings)\\|/(?:home|media|mnt|Users)/)",
    re.IGNORECASE,
)

MARKERS = ("H&E", "ER", "PR", "HER2", "Ki-67")
MARKER_ORDER = {marker: index for index, marker in enumerate(MARKERS)}
MARKER_FILENAME = {
    "H&E": "HE",
    "ER": "ER",
    "PR": "PR",
    "HER2": "HER2",
    "Ki-67": "KI67",
}
MARKER_ALIASES = {
    "he": "H&E",
    "hande": "H&E",
    "hematoxylinandeosin": "H&E",
    "hematoxylineosin": "H&E",
    "hematoxilinaeosina": "H&E",
    "er": "ER",
    "re": "ER",
    "estrogenreceptor": "ER",
    "receptordeestrogeno": "ER",
    "receptorestrogeno": "ER",
    "pr": "PR",
    "rp": "PR",
    "progesteronereceptor": "PR",
    "receptordeprogesterona": "PR",
    "receptorprogesterona": "PR",
    "her2": "HER2",
    "her2neu": "HER2",
    "erbb2": "HER2",
    "cerbb2": "HER2",
    "ki67": "Ki-67",
    "mki67": "Ki-67",
}

# Public provenance is deliberately restricted to concise English values. The
# cohort-specific variants retain objective/binning because these details are
# relevant to interpreting the calibrated physical scale.
MPP_PROVENANCE_VALUES = (
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
)
MPP_PROVENANCE_ALIASES = {
    value: value for value in MPP_PROVENANCE_VALUES
}
MPP_PROVENANCE_ALIASES.update(
    {
        "measured_scale_bar": "measured_scale_bar_calibration",
        "scale_bar_calibration": "measured_scale_bar_calibration",
        "measured_red_bar_10x_binning_1x": (
            "measured_scale_bar_calibration_10x_binning_1x"
        ),
        "measured_red_bar_10x_binning_3x": (
            "measured_scale_bar_calibration_10x_binning_3x"
        ),
        "measured_red_bar_40x_binning_3x": (
            "measured_scale_bar_calibration_40x_binning_3x"
        ),
        "extrapolated_from_measured_10x_red_bar_binning_1x": (
            "documented_magnification_extrapolation_from_measured_10x_"
            "scale_bar_binning_1x"
        ),
        "documented_extrapolation": "documented_magnification_extrapolation",
        "externally_verified": "externally_verified_calibration",
        "verified_external_calibration": "externally_verified_calibration",
    }
)

# No descriptive, instrument, acquisition, or vendor-private tags are allowed.
# These are the baseline structural TIFF tags emitted by tifffile for a single
# uncompressed contiguous RGB image.
ALLOWED_OUTPUT_TIFF_TAGS = frozenset(
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


class PreparationError(RuntimeError):
    """Raised when a release cannot be prepared without unsafe assumptions."""


@dataclass(frozen=True)
class SourcePatch:
    row_number: int
    case_id: str
    canonical_case_id: str
    original_marker: str
    marker: str
    field_id: str
    canonical_field_id: str
    source_path: Path
    microns_per_pixel: float
    original_mpp_provenance: str
    mpp_provenance: str
    width: int
    height: int
    dtype: str
    estimated_pixel_bytes: int
    initial_identity: tuple[int, int, int, int, int]


@dataclass(frozen=True)
class PlannedPatch:
    source: SourcePatch
    case_alias: str
    patch_alias: str
    public_path: str


@dataclass(frozen=True)
class ReleasePlan:
    source_manifest: Path
    public_output: Path
    private_linkage: Path
    patches: tuple[PlannedPatch, ...]
    case_count: int
    estimated_pixel_bytes: int


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


def ensure_not_symlink(path: Path, label: str) -> None:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink():
        raise PreparationError(f"Refusing symlink {label}: {candidate}")


def validate_locations(
    source_manifest: Path,
    secret_file: Path,
    public_output: Path,
    private_linkage: Path,
) -> tuple[Path, Path, Path, Path]:
    ensure_not_symlink(source_manifest, "source manifest")
    ensure_not_symlink(secret_file, "alias secret")
    ensure_not_symlink(public_output, "public output")
    ensure_not_symlink(private_linkage, "private linkage")

    manifest = canonical_path(source_manifest)
    secret = canonical_path(secret_file)
    public = canonical_path(public_output)
    linkage = canonical_path(private_linkage)
    repository = REPOSITORY_ROOT.resolve()

    if is_within(public, repository):
        raise PreparationError("--public-output must be outside the source repository")
    if is_within(secret, repository) or secret == public or is_within(secret, public):
        raise PreparationError(
            "--alias-secret-file must be outside both --public-output and the repository"
        )
    if is_within(linkage, repository) or linkage == public or is_within(linkage, public):
        raise PreparationError(
            "--private-linkage must be outside both --public-output and the repository"
        )
    if secret == linkage:
        raise PreparationError("Alias secret and private linkage must be different files")
    if manifest == public or is_within(manifest, public):
        raise PreparationError("Source manifest must not be inside --public-output")
    if not manifest.is_file():
        raise PreparationError(f"Source manifest is not a regular file: {manifest}")
    if public.exists() or public_output.expanduser().absolute().is_symlink():
        raise PreparationError(f"Public output already exists; refusing overwrite: {public}")
    if linkage.exists() or private_linkage.expanduser().absolute().is_symlink():
        raise PreparationError(f"Private linkage already exists; refusing overwrite: {linkage}")
    return manifest, secret, public, linkage


def load_secret(path: Path) -> bytes:
    ensure_not_symlink(path, "alias secret")
    try:
        before = path.stat()
    except OSError as exc:
        raise PreparationError("Alias secret is not an accessible regular file") from exc
    if not stat.S_ISREG(before.st_mode):
        raise PreparationError("Alias secret is not a regular file")
    if stat.S_IMODE(before.st_mode) != 0o600:
        raise PreparationError("Alias secret must have exact mode 0600")
    if hasattr(os, "getuid") and before.st_uid != os.getuid():
        raise PreparationError("Alias secret must be owned by the current user")
    if before.st_nlink != 1:
        raise PreparationError("Alias secret must not have additional hard links")
    secret = path.read_bytes()
    after = path.stat()
    if stat_identity(before) != stat_identity(after):
        raise PreparationError("Alias secret changed while it was read")
    if len(secret) < SECRET_MINIMUM_BYTES:
        raise PreparationError(
            f"Alias secret must contain at least {SECRET_MINIMUM_BYTES} bytes"
        )
    return secret


def canonical_identifier(value: str, label: str, row_number: int) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if not normalized or "\x00" in normalized:
        raise PreparationError(f"Empty or invalid {label} at source row {row_number}")
    return normalized


def normalize_marker(value: str, row_number: int) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    key = re.sub(r"[^a-z0-9]+", "", normalized.casefold())
    try:
        return MARKER_ALIASES[key]
    except KeyError as exc:
        raise PreparationError(
            f"Unknown marker at source row {row_number}; allowed English outputs are "
            + ", ".join(MARKERS)
        ) from exc


def parse_mpp(value: str, row_number: int) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise PreparationError(
            f"Invalid microns_per_pixel at source row {row_number}"
        ) from exc
    if (
        not math.isfinite(parsed)
        or parsed < MIN_EMBEDDED_MPP
        or parsed > MAX_EMBEDDED_MPP
    ):
        raise PreparationError(
            "microns_per_pixel must be within the embedded-TIFF range "
            f"{MIN_EMBEDDED_MPP:g}-{MAX_EMBEDDED_MPP:g} at source row {row_number}"
        )
    return parsed


def normalize_mpp_provenance(value: str, row_number: int) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    key = re.sub(r"[^a-z0-9]+", "_", normalized.casefold()).strip("_")
    try:
        return MPP_PROVENANCE_ALIASES[key]
    except KeyError as exc:
        raise PreparationError(
            f"Unknown or unsafe mpp_provenance at source row {row_number}; "
            "use an allowlisted English calibration provenance"
        ) from exc


def inspect_rgb_tiff(path: Path) -> tuple[int, int, str, int]:
    """Validate a source header without decoding its full pixel array."""
    try:
        with tifffile.TiffFile(path) as tif:
            if len(tif.pages) != 1:
                raise PreparationError(
                    f"Source TIFF must contain exactly one page: {path}"
                )
            page = tif.pages[0]
            orientation_tag = page.tags.get("Orientation")
            orientation = 1 if orientation_tag is None else int(orientation_tag.value)
            if orientation != 1:
                raise PreparationError(
                    f"Source TIFF Orientation must be 1 before sanitization: {path}"
                )
            photometric = getattr(page.photometric, "name", str(page.photometric))
            if photometric != "RGB" or int(page.samplesperpixel) != 3:
                raise PreparationError(f"Source TIFF is not three-channel RGB: {path}")
            shape = tuple(int(value) for value in page.shape)
            if len(shape) != 3:
                raise PreparationError(f"Source TIFF does not decode to a 3-D array: {path}")
            if shape[-1] == 3:
                height, width = shape[0], shape[1]
            elif shape[0] == 3:
                height, width = shape[1], shape[2]
            else:
                raise PreparationError(f"Cannot identify RGB channel axis in TIFF: {path}")
            dtype = np.dtype(page.dtype)
            if dtype.kind != "u" or dtype.itemsize not in {1, 2}:
                raise PreparationError(
                    f"Only uint8 and uint16 RGB TIFF pixels are supported: {path}"
                )
            if height <= 0 or width <= 0:
                raise PreparationError(f"Source TIFF has invalid dimensions: {path}")
            return height, width, dtype.str, height * width * 3 * dtype.itemsize
    except PreparationError:
        raise
    except (OSError, TypeError, ValueError, tifffile.TiffFileError) as exc:
        raise PreparationError(f"Cannot inspect source TIFF {path}: {exc}") from exc


def resolve_source_path(raw: str, manifest: Path, row_number: int) -> Path:
    if not raw.strip() or "\x00" in raw:
        raise PreparationError(f"Empty or invalid source_path at source row {row_number}")
    candidate = Path(raw.strip()).expanduser()
    if not candidate.is_absolute():
        candidate = manifest.parent / candidate
    ensure_not_symlink(candidate, f"source TIFF at row {row_number}")
    source = candidate.absolute().resolve(strict=False)
    if not source.is_file():
        raise PreparationError(f"Source TIFF is not a regular file at row {row_number}")
    if source.suffix.casefold() not in {".tif", ".tiff"}:
        raise PreparationError(f"Source is not a .tif/.tiff file at row {row_number}")
    return source


def load_source_manifest(
    manifest: Path,
    expected_cases: int,
    expected_files: int,
) -> list[SourcePatch]:
    if expected_cases <= 0 or expected_files <= 0:
        raise PreparationError("--expected-cases and --expected-files must be > 0")
    selected: list[SourcePatch] = []
    seen_keys: set[tuple[str, str, str]] = set()
    seen_sources: set[Path] = set()
    case_spellings: dict[str, str] = {}
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = REQUIRED_SOURCE_COLUMNS - fields
        if missing:
            raise PreparationError(
                "Source manifest is missing required columns: " + ", ".join(sorted(missing))
            )
        for row_number, row in enumerate(reader, start=2):
            include = str(row.get("include", "")).strip().casefold()
            if include not in {"true", "false"}:
                raise PreparationError(
                    f"include must be exactly true or false at source row {row_number}"
                )
            if include == "false":
                continue
            case_id = str(row.get("case_id", "")).strip()
            field_id = str(row.get("field_id", "")).strip()
            original_marker = str(row.get("marker", "")).strip()
            canonical_case = canonical_identifier(case_id, "case_id", row_number)
            canonical_field = canonical_identifier(field_id, "field_id", row_number)
            previous_spelling = case_spellings.setdefault(canonical_case, case_id)
            if previous_spelling != case_id:
                raise PreparationError(
                    f"Inconsistent spelling for one case_id at source row {row_number}"
                )
            marker = normalize_marker(original_marker, row_number)
            mpp = parse_mpp(str(row.get("microns_per_pixel", "")).strip(), row_number)
            original_mpp_provenance = str(row.get("mpp_provenance", "")).strip()
            mpp_provenance = normalize_mpp_provenance(
                original_mpp_provenance,
                row_number,
            )
            source = resolve_source_path(
                str(row.get("source_path", "")), manifest, row_number
            )
            key = (canonical_case, marker, canonical_field)
            if key in seen_keys:
                raise PreparationError(f"Duplicate case/marker/field at source row {row_number}")
            if source in seen_sources:
                raise PreparationError(f"Duplicate source TIFF at source row {row_number}")
            seen_keys.add(key)
            seen_sources.add(source)
            before = source.stat()
            height, width, dtype, estimated_bytes = inspect_rgb_tiff(source)
            after = source.stat()
            if stat_identity(before) != stat_identity(after):
                raise PreparationError(
                    f"Source TIFF changed while its header was inspected at row {row_number}"
                )
            selected.append(
                SourcePatch(
                    row_number=row_number,
                    case_id=case_id,
                    canonical_case_id=canonical_case,
                    original_marker=original_marker,
                    marker=marker,
                    field_id=field_id,
                    canonical_field_id=canonical_field,
                    source_path=source,
                    microns_per_pixel=mpp,
                    original_mpp_provenance=original_mpp_provenance,
                    mpp_provenance=mpp_provenance,
                    width=width,
                    height=height,
                    dtype=dtype,
                    estimated_pixel_bytes=estimated_bytes,
                    initial_identity=stat_identity(after),
                )
            )
    if len(selected) != expected_files:
        raise PreparationError(
            f"Expected {expected_files} included TIFFs, found {len(selected)}"
        )
    case_count = len({patch.canonical_case_id for patch in selected})
    if case_count != expected_cases:
        raise PreparationError(
            f"Expected {expected_cases} included cases, found {case_count}"
        )
    return selected


def hmac_alias(secret: bytes, domain: str, value: str, prefix: str) -> str:
    message = (
        "TumorQuantAI breast IHC patch release alias v1\x00"
        + domain
        + "\x00"
        + value
    ).encode("utf-8")
    digest = hmac.new(secret, message, hashlib.sha256).digest()
    token = base64.b32encode(digest[:13]).decode("ascii").rstrip("=")[:20]
    return prefix + token


def make_plan(
    source_manifest: Path,
    secret_file: Path,
    public_output: Path,
    private_linkage: Path,
    expected_cases: int,
    expected_files: int,
) -> ReleasePlan:
    manifest, secret_path, public, linkage = validate_locations(
        source_manifest, secret_file, public_output, private_linkage
    )
    secret = load_secret(secret_path)
    sources = load_source_manifest(manifest, expected_cases, expected_files)
    case_aliases = {
        source.canonical_case_id: hmac_alias(
            secret, "case", source.canonical_case_id, "TQA_BC_"
        )
        for source in sources
    }
    if len(set(case_aliases.values())) != len(case_aliases):
        raise PreparationError("HMAC case alias collision; use a new release secret")
    if any(not CASE_ALIAS_RE.fullmatch(alias) for alias in case_aliases.values()):
        raise PreparationError("Generated an invalid public case alias")

    planned: list[PlannedPatch] = []
    patch_aliases: set[str] = set()
    for source in sources:
        patch_key = "\x00".join(
            (
                source.canonical_case_id,
                source.marker,
                source.canonical_field_id,
            )
        )
        patch_alias = hmac_alias(secret, "patch", patch_key, "TQA_PATCH_")
        if not PATCH_ALIAS_RE.fullmatch(patch_alias):
            raise PreparationError("Generated an invalid public patch alias")
        if patch_alias in patch_aliases:
            raise PreparationError("HMAC patch alias collision; use a new release secret")
        patch_aliases.add(patch_alias)
        case_alias = case_aliases[source.canonical_case_id]
        filename = f"{patch_alias}_{MARKER_FILENAME[source.marker]}.tif"
        planned.append(
            PlannedPatch(
                source=source,
                case_alias=case_alias,
                patch_alias=patch_alias,
                public_path=f"patches/{case_alias}/{filename}",
            )
        )
    planned.sort(
        key=lambda item: (
            item.case_alias,
            MARKER_ORDER[item.source.marker],
            item.patch_alias,
        )
    )
    return ReleasePlan(
        source_manifest=manifest,
        public_output=public,
        private_linkage=linkage,
        patches=tuple(planned),
        case_count=len(case_aliases),
        estimated_pixel_bytes=sum(item.estimated_pixel_bytes for item in sources),
    )


def safe_summary(plan: ReleasePlan, status: str) -> dict[str, object]:
    marker_counts = Counter(item.source.marker for item in plan.patches)
    provenance_counts = Counter(
        item.source.mpp_provenance for item in plan.patches
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "draft_only": True,
        "network_used": False,
        "upload_performed": False,
        "publication_performed": False,
        "case_count": plan.case_count,
        "patch_count": len(plan.patches),
        "marker_patch_counts": {
            marker: marker_counts.get(marker, 0) for marker in MARKERS
        },
        "mpp_provenance_counts": {
            provenance: provenance_counts.get(provenance, 0)
            for provenance in MPP_PROVENANCE_VALUES
            if provenance_counts.get(provenance, 0)
        },
        "estimated_decoded_pixel_bytes": plan.estimated_pixel_bytes,
        "sanitization_profile": SANITIZATION_PROFILE,
    }


def canonical_rgb(array: np.ndarray, path: Path) -> np.ndarray:
    value = np.asarray(array)
    if value.ndim != 3:
        raise PreparationError(f"TIFF did not decode to three dimensions: {path}")
    if value.shape[-1] == 3:
        rgb = value
    elif value.shape[0] == 3:
        rgb = np.moveaxis(value, 0, -1)
    else:
        raise PreparationError(f"TIFF did not decode to exactly three RGB channels: {path}")
    if rgb.dtype.kind != "u" or rgb.dtype.itemsize not in {1, 2}:
        raise PreparationError(f"TIFF decoded to an unsupported RGB dtype: {path}")
    target_dtype = np.dtype("u1" if rgb.dtype.itemsize == 1 else "<u2")
    return np.ascontiguousarray(rgb, dtype=target_dtype)


def decoded_rgb_sha256(rgb: np.ndarray) -> str:
    if rgb.ndim != 3 or rgb.shape[-1] != 3 or not rgb.flags.c_contiguous:
        raise PreparationError("Internal error: pixel digest requires contiguous RGB")
    digest = hashlib.sha256()
    digest.update(b"TumorQuantAI decoded RGB sha256 v1\x00")
    digest.update(str(rgb.shape[0]).encode("ascii"))
    digest.update(b"x")
    digest.update(str(rgb.shape[1]).encode("ascii"))
    digest.update(b"x3\x00")
    digest.update(("uint8" if rgb.dtype.itemsize == 1 else "uint16-le").encode("ascii"))
    digest.update(b"\x00")
    digest.update(memoryview(rgb).cast("B"))
    return digest.hexdigest()


def load_decoded_rgb(path: Path) -> np.ndarray:
    try:
        with tifffile.TiffFile(path) as tif:
            if len(tif.pages) != 1:
                raise PreparationError(f"TIFF must contain exactly one page: {path}")
            return canonical_rgb(tif.pages[0].asarray(), path)
    except PreparationError:
        raise
    except (OSError, ValueError, tifffile.TiffFileError) as exc:
        raise PreparationError(f"Cannot decode TIFF {path}: {exc}") from exc


def reencode_minimal_tiff(
    source_rgb: np.ndarray,
    destination: Path,
    microns_per_pixel: float,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(destination.parent, 0o700)
    if destination.exists() or destination.is_symlink():
        raise PreparationError(f"Staging TIFF already exists: {destination}")
    if (
        not math.isfinite(microns_per_pixel)
        or microns_per_pixel < MIN_EMBEDDED_MPP
        or microns_per_pixel > MAX_EMBEDDED_MPP
    ):
        raise PreparationError("Cannot encode an invalid microns-per-pixel value")
    pixels_per_centimeter = MICRONS_PER_CENTIMETER / microns_per_pixel
    bigtiff = source_rgb.nbytes >= (2**32 - 32 * 1024 * 1024)
    try:
        tifffile.imwrite(
            destination,
            source_rgb,
            mode="x",
            bigtiff=bigtiff,
            byteorder="<",
            ome=False,
            shaped=False,
            photometric="rgb",
            planarconfig="contig",
            rowsperstrip=min(int(source_rgb.shape[0]), 256),
            compression=None,
            description=None,
            datetime=None,
            resolution=(pixels_per_centimeter, pixels_per_centimeter),
            resolutionunit="CENTIMETER",
            software=False,
            metadata=None,
            contiguous=False,
            align=1,
            maxworkers=1,
        )
        os.chmod(destination, 0o644)
        with destination.open("rb") as handle:
            os.fsync(handle.fileno())
    except Exception:
        if destination.exists():
            destination.unlink()
        raise


def rational_value(value: object, label: str) -> float:
    if isinstance(value, tuple) and len(value) == 2:
        numerator, denominator = value
        if float(denominator) == 0:
            raise PreparationError(f"Sanitized TIFF has zero {label} denominator")
        result = float(numerator) / float(denominator)
    else:
        result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise PreparationError(f"Sanitized TIFF has invalid {label}")
    return result


def page_microns_per_pixel(page: tifffile.TiffPage) -> tuple[float, float]:
    try:
        unit = page.tags["ResolutionUnit"].value
        unit_name = getattr(unit, "name", str(unit))
        if unit_name != "CENTIMETER" and int(unit) != 3:
            raise PreparationError(
                "Sanitized TIFF resolution unit must be centimeter"
            )
        x_pixels_per_centimeter = rational_value(
            page.tags["XResolution"].value,
            "XResolution",
        )
        y_pixels_per_centimeter = rational_value(
            page.tags["YResolution"].value,
            "YResolution",
        )
    except KeyError as exc:
        raise PreparationError(
            "Sanitized TIFF is missing physical-scale resolution tags"
        ) from exc
    return (
        MICRONS_PER_CENTIMETER / x_pixels_per_centimeter,
        MICRONS_PER_CENTIMETER / y_pixels_per_centimeter,
    )


def validate_minimal_tiff(path: Path, expected_mpp: float) -> tuple[float, float]:
    try:
        with tifffile.TiffFile(path) as tif:
            if len(tif.pages) != 1:
                raise PreparationError(f"Sanitized TIFF has unexpected pages: {path}")
            names = {str(tag.name) for tag in tif.pages[0].tags.values()}
            unexpected = sorted(names - ALLOWED_OUTPUT_TIFF_TAGS)
            if unexpected:
                raise PreparationError(
                    "Sanitized TIFF contains non-allowlisted tags: " + ", ".join(unexpected)
                )
            page = tif.pages[0]
            if (
                getattr(page.photometric, "name", str(page.photometric)) != "RGB"
                or int(page.samplesperpixel) != 3
            ):
                raise PreparationError(f"Sanitized TIFF is not three-channel RGB: {path}")
            if getattr(page.compression, "name", str(page.compression)) != "NONE":
                raise PreparationError(f"Sanitized TIFF is unexpectedly compressed: {path}")
            if getattr(page.planarconfig, "name", str(page.planarconfig)) != "CONTIG":
                raise PreparationError(
                    f"Sanitized TIFF does not use contiguous RGB samples: {path}"
                )
            embedded_mpp = page_microns_per_pixel(page)
            if any(
                not math.isclose(
                    value,
                    expected_mpp,
                    rel_tol=MPP_RELATIVE_TOLERANCE,
                    abs_tol=MPP_ABSOLUTE_TOLERANCE,
                )
                for value in embedded_mpp
            ):
                raise PreparationError(
                    f"Sanitized TIFF physical-scale verification failed: {path}"
                )
            return embedded_mpp
    except PreparationError:
        raise
    except (OSError, ValueError, tifffile.TiffFileError) as exc:
        raise PreparationError(f"Cannot validate sanitized TIFF {path}: {exc}") from exc


def digest_file(
    path: Path, chunk_size: int = 8 * 1024 * 1024
) -> tuple[int, str, str]:
    before = path.stat()
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            sha256.update(chunk)
            md5.update(chunk)
    after = path.stat()
    if stat_identity(before) != stat_identity(after):
        raise PreparationError(f"File changed while checksums were computed: {path}")
    return after.st_size, sha256.hexdigest(), md5.hexdigest()


def write_csv(
    path: Path,
    columns: tuple[str, ...],
    rows: Iterable[dict[str, object]],
    mode: int,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, mode)
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
    os.chmod(path, mode)


def write_private_csv_temporary(
    destination: Path,
    columns: tuple[str, ...],
    rows: Iterable[dict[str, object]],
) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
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
        os.chmod(temporary, 0o600)
        return temporary
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        if temporary.exists():
            temporary.unlink()
        raise


def write_text(path: Path, text: str, mode: int = 0o644) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        if path.exists():
            path.unlink()
        raise
    os.chmod(path, mode)


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def linux_rename_noreplace(source: Path, destination: Path) -> bool:
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
        raise PreparationError(
            "An output appeared during final placement; refusing overwrite"
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


def atomic_publish_no_replace(source: Path, destination: Path) -> None:
    if source.is_symlink() or not (source.is_file() or source.is_dir()):
        raise PreparationError("Final staging entry is missing or unsafe")
    if linux_rename_noreplace(source, destination):
        return
    raise PreparationError(
        "Atomic no-replace placement is unavailable on this platform; "
        "refusing a non-atomic fallback"
    )


def rollback_owned_linkage(
    path: Path,
    expected_identity: tuple[int, int, int, int, int],
) -> None:
    try:
        observed = path.lstat()
    except OSError as exc:
        raise PreparationError(
            "Private linkage rollback failed; manual review is required"
        ) from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(observed.st_mode)
        or stat_identity(observed) != expected_identity
    ):
        raise PreparationError(
            "Private linkage changed before rollback; manual review is required"
        )
    path.unlink()
    fsync_directory(path.parent)


def checksum_payloads(root: Path) -> list[tuple[str, int, str, str]]:
    rows: list[tuple[str, int, str, str]] = []
    for path in sorted(root.rglob("*"), key=lambda value: value.relative_to(root).as_posix()):
        if path.is_symlink():
            raise PreparationError(f"Symlink found in public staging: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in {SHA256SUMS, MD5SUMS}:
            continue
        size, sha256, md5 = digest_file(path)
        rows.append((relative, size, sha256, md5))
    return rows


def validate_public_text(root: Path, private_markers: Iterable[str]) -> None:
    text_files = [
        root / PATCH_MANIFEST,
        root / CASE_MARKER_COUNTS,
        root / VALIDATION_REPORT,
        root / SHA256SUMS,
        root / MD5SUMS,
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in text_files)
    if PRIVATE_PATH_RE.search(combined):
        raise PreparationError("Private absolute path detected in public tables")
    if ISO_DATE_RE.search(combined):
        raise PreparationError("Date-like value detected in public tables")
    folded = combined.casefold()
    for marker in private_markers:
        normalized = unicodedata.normalize("NFKC", marker).strip().casefold()
        if len(normalized) >= 4 and normalized in folded:
            raise PreparationError("Private source identifier detected in public tables")


def ensure_available_space(parent: Path, required: int) -> None:
    free = shutil.disk_usage(parent).free
    minimum = required + DISK_SAFETY_MARGIN_BYTES
    if free < minimum:
        raise PreparationError(
            f"Insufficient free space for sanitized TIFF staging: need at least {minimum} bytes"
        )


def prepare_release(
    source_manifest: Path,
    secret_file: Path,
    public_output: Path,
    private_linkage: Path,
    expected_cases: int,
    expected_files: int,
    dry_run: bool = False,
) -> dict[str, object]:
    plan = make_plan(
        source_manifest,
        secret_file,
        public_output,
        private_linkage,
        expected_cases,
        expected_files,
    )
    if dry_run:
        return safe_summary(plan, "planned")

    plan.public_output.parent.mkdir(parents=True, exist_ok=True)
    plan.private_linkage.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    ensure_not_symlink(plan.public_output.parent, "public output parent")
    ensure_not_symlink(plan.private_linkage.parent, "private linkage parent")
    ensure_available_space(plan.public_output.parent, plan.estimated_pixel_bytes)

    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{plan.public_output.name}.draft-",
            dir=plan.public_output.parent,
        )
    )
    os.chmod(staging, 0o700)
    linkage_temporary: Path | None = None
    try:
        public_rows: list[dict[str, object]] = []
        private_rows: list[dict[str, object]] = []
        case_marker_counts: Counter[tuple[str, str]] = Counter()
        for item in plan.patches:
            source = item.source
            if stat_identity(source.source_path.stat()) != source.initial_identity:
                raise PreparationError(
                    f"Source TIFF changed after planning at row {source.row_number}"
                )
            source_size, source_sha256, _source_md5 = digest_file(source.source_path)
            source_rgb = load_decoded_rgb(source.source_path)
            if source_rgb.shape != (source.height, source.width, 3):
                raise PreparationError(
                    f"Decoded dimensions changed after planning at row {source.row_number}"
                )
            source_pixel_sha256 = decoded_rgb_sha256(source_rgb)
            destination = staging / item.public_path
            reencode_minimal_tiff(
                source_rgb,
                destination,
                source.microns_per_pixel,
            )
            validate_minimal_tiff(
                destination,
                source.microns_per_pixel,
            )
            sanitized_rgb = load_decoded_rgb(destination)
            sanitized_pixel_sha256 = decoded_rgb_sha256(sanitized_rgb)
            if (
                source_pixel_sha256 != sanitized_pixel_sha256
                or source_rgb.dtype != sanitized_rgb.dtype
                or source_rgb.shape != sanitized_rgb.shape
                or not np.array_equal(source_rgb, sanitized_rgb)
            ):
                raise PreparationError(
                    f"Decoded RGB pixel verification failed at row {source.row_number}"
                )
            del sanitized_rgb
            del source_rgb
            public_size, public_sha256, public_md5 = digest_file(destination)
            if stat_identity(source.source_path.stat()) != source.initial_identity:
                raise PreparationError(
                    f"Source TIFF changed while it was processed at row {source.row_number}"
                )

            mpp = format(source.microns_per_pixel, ".12g")
            public_rows.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "case_alias": item.case_alias,
                    "patch_alias": item.patch_alias,
                    "marker": source.marker,
                    "public_path": item.public_path,
                    "microns_per_pixel": mpp,
                    "mpp_provenance": source.mpp_provenance,
                    "width": source.width,
                    "height": source.height,
                    "channels": 3,
                    "dtype": "uint8" if np.dtype(source.dtype).itemsize == 1 else "uint16",
                    "size_bytes": public_size,
                    "sha256": public_sha256,
                    "md5": public_md5,
                    "decoded_rgb_sha256": sanitized_pixel_sha256,
                    "sanitization_profile": SANITIZATION_PROFILE,
                }
            )
            private_rows.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "case_alias": item.case_alias,
                    "patch_alias": item.patch_alias,
                    "case_id": source.case_id,
                    "field_id": source.field_id,
                    "original_marker": source.original_marker,
                    "marker": source.marker,
                    "original_mpp_provenance": source.original_mpp_provenance,
                    "mpp_provenance": source.mpp_provenance,
                    "source_path": str(source.source_path),
                    "source_size_bytes": source_size,
                    "source_sha256": source_sha256,
                    "public_path": item.public_path,
                    "public_size_bytes": public_size,
                    "public_sha256": public_sha256,
                    "decoded_rgb_sha256": sanitized_pixel_sha256,
                    "validation_status": "passed",
                }
            )
            case_marker_counts[(item.case_alias, source.marker)] += 1

        write_csv(staging / PATCH_MANIFEST, PATCH_COLUMNS, public_rows, 0o644)
        case_rows = [
            {
                "schema_version": SCHEMA_VERSION,
                "case_alias": case_alias,
                "marker": marker,
                "patch_count": count,
            }
            for (case_alias, marker), count in sorted(
                case_marker_counts.items(),
                key=lambda value: (
                    value[0][0],
                    MARKER_ORDER[value[0][1]],
                ),
            )
        ]
        write_csv(
            staging / CASE_MARKER_COUNTS,
            CASE_MARKER_COLUMNS,
            case_rows,
            0o644,
        )
        report = safe_summary(plan, "passed")
        report.update(
            {
                "decoded_rgb_verification": "full-array SHA-256 equality",
                "physical_scale_verification": (
                    "Per-file microns_per_pixel encoded and verified in TIFF "
                    "XResolution/YResolution with ResolutionUnit=centimeter"
                ),
                "tiff_metadata_policy": "fixed structural-tag allowlist",
                "public_tables": [PATCH_MANIFEST, CASE_MARKER_COUNTS],
                "privacy_scope": (
                    "Source identifiers, private paths, and acquisition dates are not "
                    "selected into public tables. TIFFs are re-encoded without source "
                    "metadata. Independent visible-pixel and governance review remains "
                    "required before publication."
                ),
            }
        )
        write_text(
            staging / VALIDATION_REPORT,
            json.dumps(report, indent=2, sort_keys=True) + "\n",
        )
        payloads = checksum_payloads(staging)
        write_text(
            staging / SHA256SUMS,
            "".join(f"{sha256}  {relative}\n" for relative, _size, sha256, _md5 in payloads),
        )
        write_text(
            staging / MD5SUMS,
            "".join(f"{md5}  {relative}\n" for relative, _size, _sha256, md5 in payloads),
        )
        validate_public_text(
            staging,
            (
                private_value
                for source in (item.source for item in plan.patches)
                for private_value in (
                    source.case_id,
                    source.field_id,
                    str(source.source_path),
                    source.source_path.name,
                )
            ),
        )

        linkage_temporary = write_private_csv_temporary(
            plan.private_linkage,
            PRIVATE_COLUMNS,
            private_rows,
        )

        linkage_source_stat = linkage_temporary.stat()
        linkage_source_identity = (
            linkage_source_stat.st_dev,
            linkage_source_stat.st_ino,
            linkage_source_stat.st_size,
        )
        atomic_publish_no_replace(linkage_temporary, plan.private_linkage)
        linkage_temporary = None
        linkage_target_stat = plan.private_linkage.lstat()
        linkage_target_identity = (
            linkage_target_stat.st_dev,
            linkage_target_stat.st_ino,
            linkage_target_stat.st_size,
        )
        if (
            not stat.S_ISREG(linkage_target_stat.st_mode)
            or linkage_target_identity != linkage_source_identity
        ):
            raise PreparationError(
                "Private linkage identity changed during final placement; "
                "public output was not committed"
            )
        linkage_identity = stat_identity(linkage_target_stat)
        try:
            atomic_publish_no_replace(staging, plan.public_output)
        except Exception as publish_error:
            try:
                rollback_owned_linkage(plan.private_linkage, linkage_identity)
            except PreparationError as rollback_error:
                raise rollback_error from publish_error
            raise
        fsync_directory(plan.private_linkage.parent)
        if plan.public_output.parent != plan.private_linkage.parent:
            fsync_directory(plan.public_output.parent)
    finally:
        if linkage_temporary is not None and linkage_temporary.exists():
            linkage_temporary.unlink()
        if staging.exists():
            shutil.rmtree(staging)

    result = safe_summary(plan, "prepared")
    result["public_output"] = str(plan.public_output)
    result["private_linkage"] = str(plan.private_linkage)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-manifest",
        required=True,
        type=Path,
        help=(
            "Private CSV with case_id, marker, field_id, source_path, include, "
            "microns_per_pixel, and mpp_provenance"
        ),
    )
    parser.add_argument(
        "--alias-secret-file",
        required=True,
        type=Path,
        help=(
            "Mode-0600 file containing at least 32 random bytes, outside both "
            "the repository and public output"
        ),
    )
    parser.add_argument(
        "--public-output",
        required=True,
        type=Path,
        help="New local draft directory outside the repository; never uploaded",
    )
    parser.add_argument(
        "--private-linkage",
        required=True,
        type=Path,
        help="New mode-0600 CSV outside both staging and the repository",
    )
    parser.add_argument("--expected-cases", required=True, type=int)
    parser.add_argument("--expected-files", required=True, type=int)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report a safe plan without writing or re-encoding files",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = prepare_release(
            source_manifest=args.source_manifest,
            secret_file=args.alias_secret_file,
            public_output=args.public_output,
            private_linkage=args.private_linkage,
            expected_cases=args.expected_cases,
            expected_files=args.expected_files,
            dry_run=args.dry_run,
        )
    except (PreparationError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
