#!/usr/bin/env python3
"""Create or resume an open-access, unpublished breast-IHC Zenodo draft.

This command is intentionally draft-only and accepts exactly the 55 files
created by ``package_breast_ihc_patch_release.py`` for the fixed 51-case,
1,901-patch release. It has no publication operation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import stat
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from html import unescape
from pathlib import Path
from urllib.parse import quote, urlparse
from zipfile import ZIP_STORED, BadZipFile, ZipFile

import package_breast_ihc_patch_release as package
import zenodo_deposit as base


DEFAULT_API_URL = "https://zenodo.org/api"
ALLOWED_API_URLS = frozenset(
    {
        "https://zenodo.org/api",
        "https://sandbox.zenodo.org/api",
    }
)
DATASET_FORMAT = "breast-ihc-package-v1"
EXPECTED_CASES = 51
EXPECTED_PATCHES = 1_901
EXPECTED_UPLOAD_FILES = 55
ZENODO_DEFAULT_QUOTA_BYTES = 50_000_000_000
ZENODO_MAX_ALLOCATED_BYTES = 200_000_000_000
MAX_BUNDLE_MEMBER_BYTES = 32 * 1024 * 1024

CASE_ARCHIVE_RE = re.compile(r"^(TQA_BC_[A-Z2-7]{20})\.zip$")
CORE_AUXILIARY_FILES = frozenset(
    {
        package.MANIFEST_BUNDLE,
        package.PACKAGING_REPORT,
        package.UPLOAD_SHA256SUMS,
        package.UPLOAD_MD5SUMS,
    }
)
EXPECTED_BUNDLE_MEMBERS = tuple(
    sorted([*package.SOURCE_METADATA_FILES, package.ARCHIVE_MANIFEST])
)
PACKAGING_REPORT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "draft_only",
        "network_used",
        "upload_performed",
        "publication_performed",
        "source_retained",
        "case_count",
        "patch_count",
        "case_archive_count",
        "upload_file_count",
        "maximum_upload_file_count",
        "source_tree_bytes",
        "estimated_additional_disk_bytes",
        "archive_compression",
        "disk_tradeoff",
        "zip_member_timestamp",
        "case_archive_bytes",
        "manifest_bundle_bytes",
        "manifest_bundle",
        "manifest_bundle_members",
        "verification",
        "privacy_scope",
    }
)
PACKAGING_DISK_TRADEOFF = (
    "The sanitized source is retained and ZIP_STORED duplicates its TIFF "
    "bytes. Exact archive bytes are scoped to identical validated inputs "
    "under the same supported packager tool/runtime."
)
PACKAGING_VERIFICATION = (
    "Every ZIP roster, member size, CRC32, SHA-256, and MD5 was verified "
    "after writing; TIFF member bytes are lossless."
)
PACKAGING_PRIVACY_SCOPE = (
    "Public schemas, text patterns, file rosters, and TIFF metadata tags were "
    "validated. Independent visible-pixel and governance review remains "
    "required before publication."
)
ALLOWED_METADATA_FIELDS = frozenset(
    {
        "title",
        "description",
        "upload_type",
        "access_right",
        "license",
        "creators",
        "keywords",
        "related_identifiers",
        "version",
        "publication_date",
        "notes",
        "language",
    }
)
ALLOWED_CREATOR_FIELDS = frozenset({"name", "affiliation", "orcid", "gnd"})
ALLOWED_RELATED_IDENTIFIER_FIELDS = frozenset(
    {"identifier", "relation", "scheme", "resource_type"}
)
ORCID_RE = re.compile(r"^[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]$")
LANGUAGE_RE = re.compile(r"^[a-z]{3}$")
RELATED_IDENTIFIER_SCHEMES = frozenset(
    {
        "ads",
        "ark",
        "arxiv",
        "doi",
        "ean13",
        "handle",
        "isbn",
        "issn",
        "istc",
        "lsid",
        "pmcid",
        "pmid",
        "purl",
        "url",
        "urn",
    }
)
RELATED_IDENTIFIER_RELATIONS = (
    "isCitedBy",
    "cites",
    "isSupplementTo",
    "isSupplementedBy",
    "isContinuedBy",
    "continues",
    "isDescribedBy",
    "describes",
    "hasMetadata",
    "isMetadataFor",
    "isNewVersionOf",
    "isPreviousVersionOf",
    "isPartOf",
    "hasPart",
    "isReferencedBy",
    "references",
    "isDocumentedBy",
    "documents",
    "isCompiledBy",
    "compiles",
    "isVariantFormOf",
    "isOriginalFormOf",
    "isIdenticalTo",
    "isAlternateIdentifier",
    "isReviewedBy",
    "reviews",
    "isDerivedFrom",
    "isSourceOf",
    "requires",
    "isRequiredBy",
    "isObsoletedBy",
    "obsoletes",
)
RELATED_RELATION_BY_CASEFOLD = {
    value.casefold(): value for value in RELATED_IDENTIFIER_RELATIONS
}
LICENSE_CANONICAL_IDS = {
    "cc-by": "cc-by-4.0",
    "cc-by-sa": "cc-by-sa-4.0",
    "cc-by-nd": "cc-by-nd-4.0",
    "cc-by-nc": "cc-by-nc-4.0",
    "cc-by-nc-sa": "cc-by-nc-sa-4.0",
    "cc-by-nc-nd": "cc-by-nc-nd-4.0",
    "cc-zero": "cc0-1.0",
    "odc-by": "odc-by-1.0",
    "odc-odbl": "odbl-1.0",
    "odc-pddl": "pddl-1.0",
}


DepositError = base.DepositError


@dataclass(frozen=True)
class PatchBundle:
    members_by_case: dict[str, dict[str, package.FileDigest]]
    marker_counts: Counter[str]
    provenance_counts: Counter[str]
    decoded_pixel_bytes: int


@dataclass(frozen=True)
class ValidatedPackage:
    root: Path
    uploads: tuple[base.UploadFile, ...]
    case_archives: tuple[str, ...]
    total_size_bytes: int
    release_files_sha256: str


def _package_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except package.PackagingError as exc:
        raise DepositError(str(exc)) from exc


def _digest_bytes(payload: bytes) -> package.FileDigest:
    return package.FileDigest(
        len(payload),
        hashlib.sha256(payload).hexdigest(),
        hashlib.md5(payload, usedforsecurity=False).hexdigest(),
    )


def _positive_int(value: object, label: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise DepositError(f"Invalid {label}") from exc
    if parsed <= 0:
        raise DepositError(f"Invalid {label}")
    return parsed


def _read_csv_bytes(
    payload: bytes,
    expected_columns: tuple[str, ...],
    label: str,
) -> list[dict[str, str]]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeError as exc:
        raise DepositError(f"{label} is not valid UTF-8") from exc
    _package_call(package.validate_public_text, text, label)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != expected_columns:
        raise DepositError(f"{label} has an unexpected schema")
    return [dict(row) for row in reader]


def _parse_checksum_bytes(
    payload: bytes,
    algorithm: str,
    label: str,
) -> dict[str, str]:
    try:
        text = payload.decode("utf-8")
    except UnicodeError as exc:
        raise DepositError(f"{label} is not valid UTF-8") from exc
    _package_call(package.validate_public_text, text, label)
    digest_re = package.SHA256_RE if algorithm == "sha256" else package.MD5_RE
    result: dict[str, str] = {}
    previous = ""
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = package.CHECKSUM_LINE_RE.fullmatch(line)
        if match is None:
            raise DepositError(f"Malformed checksum at {label}:{line_number}")
        digest, relative = match.groups()
        _package_call(
            package.validate_relative_path,
            relative,
            f"checksum path at {label}:{line_number}",
        )
        if not digest_re.fullmatch(digest):
            raise DepositError(f"Invalid digest at {label}:{line_number}")
        if relative in result or (previous and relative <= previous):
            raise DepositError(f"{label} is duplicated or unsorted")
        result[relative] = digest
        previous = relative
    if not result:
        raise DepositError(f"{label} is empty")
    return result


def _validate_zip_info(info, *, require_zip64: bool) -> None:
    mode = info.external_attr >> 16
    if (
        info.is_dir()
        or info.date_time != package.FIXED_ZIP_DATETIME
        or info.compress_type != ZIP_STORED
        or info.compress_size != info.file_size
        or info.create_system != 3
        or not stat.S_ISREG(mode)
        or stat.S_IMODE(mode) != 0o644
        or info.comment
        or info.flag_bits & 0x1
    ):
        raise DepositError(f"Unsafe ZIP member metadata: {info.filename}")
    if require_zip64 and info.extract_version < 45:
        raise DepositError(f"Case ZIP member is not forced ZIP64: {info.filename}")


def _read_manifest_bundle(path: Path) -> dict[str, bytes]:
    try:
        with ZipFile(path, mode="r") as archive:
            if archive.comment:
                raise DepositError("Manifest bundle has a ZIP comment")
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if names != list(EXPECTED_BUNDLE_MEMBERS) or len(set(names)) != len(names):
                raise DepositError("Manifest bundle roster is not exact")
            result: dict[str, bytes] = {}
            for info in infos:
                _validate_zip_info(info, require_zip64=False)
                if info.file_size > MAX_BUNDLE_MEMBER_BYTES:
                    raise DepositError(
                        f"Manifest bundle member is unexpectedly large: {info.filename}"
                    )
                result[info.filename] = archive.read(info)
            return result
    except DepositError:
        raise
    except (BadZipFile, OSError, RuntimeError) as exc:
        raise DepositError("Cannot validate the manifest bundle") from exc


def _parse_patch_manifest(
    payload: bytes,
    case_aliases: set[str],
) -> PatchBundle:
    rows = _read_csv_bytes(payload, package.PATCH_COLUMNS, package.PATCH_MANIFEST)
    if len(rows) != EXPECTED_PATCHES:
        raise DepositError(f"Expected {EXPECTED_PATCHES} patch rows, found {len(rows)}")
    members_by_case: dict[str, dict[str, package.FileDigest]] = {
        alias: {} for alias in case_aliases
    }
    marker_counts: Counter[str] = Counter()
    provenance_counts: Counter[str] = Counter()
    seen_patch_aliases: set[str] = set()
    sort_keys: list[tuple[str, int, str]] = []
    decoded_pixel_bytes = 0
    for line_number, row in enumerate(rows, start=2):
        if row.get("schema_version") != str(package.SCHEMA_VERSION):
            raise DepositError(f"Invalid patch schema version at line {line_number}")
        case_alias = str(row.get("case_alias", ""))
        patch_alias = str(row.get("patch_alias", ""))
        marker = str(row.get("marker", ""))
        provenance = str(row.get("mpp_provenance", ""))
        if case_alias not in case_aliases or not package.CASE_ALIAS_RE.fullmatch(
            case_alias
        ):
            raise DepositError(f"Invalid case alias at patch line {line_number}")
        if (
            not package.PATCH_ALIAS_RE.fullmatch(patch_alias)
            or patch_alias in seen_patch_aliases
        ):
            raise DepositError(
                f"Invalid or duplicate patch alias at line {line_number}"
            )
        if marker not in package.MARKERS:
            raise DepositError(f"Invalid marker at patch line {line_number}")
        if provenance not in package.MPP_PROVENANCE_VALUES:
            raise DepositError(f"Invalid MPP provenance at patch line {line_number}")
        public_path = str(row.get("public_path", ""))
        _package_call(
            package.validate_relative_path,
            public_path,
            f"public path at patch line {line_number}",
        )
        expected_path = (
            f"patches/{case_alias}/{patch_alias}_"
            f"{package.MARKER_FILENAME[marker]}.tif"
        )
        if public_path != expected_path or public_path in members_by_case[case_alias]:
            raise DepositError(
                f"Invalid or duplicate public path at line {line_number}"
            )
        size = _positive_int(row.get("size_bytes"), f"patch size at line {line_number}")
        width = _positive_int(row.get("width"), f"patch width at line {line_number}")
        height = _positive_int(row.get("height"), f"patch height at line {line_number}")
        dtype = str(row.get("dtype", ""))
        if dtype not in {"uint8", "uint16"} or row.get("channels") != "3":
            raise DepositError(f"Invalid pixel type at patch line {line_number}")
        try:
            mpp = float(str(row.get("microns_per_pixel", "")))
        except ValueError as exc:
            raise DepositError(f"Invalid MPP at patch line {line_number}") from exc
        if not math.isfinite(mpp) or not 0.05 <= mpp <= 10.0:
            raise DepositError(f"Invalid MPP at patch line {line_number}")
        sha256 = str(row.get("sha256", ""))
        md5 = str(row.get("md5", ""))
        decoded_sha256 = str(row.get("decoded_rgb_sha256", ""))
        if (
            not package.SHA256_RE.fullmatch(sha256)
            or not package.MD5_RE.fullmatch(md5)
            or not package.SHA256_RE.fullmatch(decoded_sha256)
            or row.get("sanitization_profile") != package.SANITIZATION_PROFILE
        ):
            raise DepositError(f"Invalid digest/profile at patch line {line_number}")
        members_by_case[case_alias][public_path] = package.FileDigest(size, sha256, md5)
        seen_patch_aliases.add(patch_alias)
        marker_counts[marker] += 1
        provenance_counts[provenance] += 1
        decoded_pixel_bytes += width * height * 3 * (1 if dtype == "uint8" else 2)
        sort_keys.append((case_alias, package.MARKER_ORDER[marker], patch_alias))
    if sort_keys != sorted(sort_keys) or any(
        not members for members in members_by_case.values()
    ):
        raise DepositError("Patch manifest ordering/case coverage is not exact")
    return PatchBundle(
        members_by_case,
        marker_counts,
        provenance_counts,
        decoded_pixel_bytes,
    )


def _validate_case_marker_counts(payload: bytes, patches: PatchBundle) -> None:
    rows = _read_csv_bytes(
        payload,
        package.CASE_MARKER_COLUMNS,
        package.CASE_MARKER_COUNTS,
    )
    expected_counts: Counter[tuple[str, str]] = Counter()
    for alias, members in patches.members_by_case.items():
        for path in members:
            filename = Path(path).name
            for marker, suffix in package.MARKER_FILENAME.items():
                if filename.endswith(f"_{suffix}.tif"):
                    expected_counts[(alias, marker)] += 1
                    break
    expected = [
        (alias, marker, count)
        for (alias, marker), count in sorted(
            expected_counts.items(),
            key=lambda item: (item[0][0], package.MARKER_ORDER[item[0][1]]),
        )
    ]
    observed: list[tuple[str, str, int]] = []
    for line_number, row in enumerate(rows, start=2):
        if row.get("schema_version") != str(package.SCHEMA_VERSION):
            raise DepositError(f"Invalid case-marker schema at line {line_number}")
        alias = str(row.get("case_alias", ""))
        marker = str(row.get("marker", ""))
        if alias not in patches.members_by_case or marker not in package.MARKERS:
            raise DepositError(f"Invalid case-marker row at line {line_number}")
        observed.append(
            (
                alias,
                marker,
                _positive_int(
                    row.get("patch_count"),
                    f"case-marker patch count at line {line_number}",
                ),
            )
        )
    if observed != expected:
        raise DepositError("case_marker_counts.csv does not match patch_manifest.csv")


def _validate_preparation_report(payload: bytes, patches: PatchBundle) -> None:
    try:
        text = payload.decode("utf-8")
        report = json.loads(text)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DepositError("validation_report.json is invalid") from exc
    _package_call(package.validate_public_text, text, package.VALIDATION_REPORT)
    if not isinstance(report, dict) or set(report) != package.PREPARATION_REPORT_KEYS:
        raise DepositError("validation_report.json key roster is not exact")
    required = {
        "schema_version": package.SCHEMA_VERSION,
        "status": "passed",
        "draft_only": True,
        "network_used": False,
        "upload_performed": False,
        "publication_performed": False,
        "case_count": EXPECTED_CASES,
        "patch_count": EXPECTED_PATCHES,
        "sanitization_profile": package.SANITIZATION_PROFILE,
        "estimated_decoded_pixel_bytes": patches.decoded_pixel_bytes,
        "decoded_rgb_verification": package.PREPARATION_DECODED_RGB_VERIFICATION,
        "physical_scale_verification": package.PREPARATION_PHYSICAL_SCALE_VERIFICATION,
        "tiff_metadata_policy": package.PREPARATION_TIFF_METADATA_POLICY,
        "public_tables": [package.PATCH_MANIFEST, package.CASE_MARKER_COUNTS],
        "privacy_scope": package.PREPARATION_PRIVACY_SCOPE,
    }
    if any(report.get(key) != value for key, value in required.items()):
        raise DepositError("validation_report.json fixed fields are invalid")
    expected_markers = {
        marker: patches.marker_counts.get(marker, 0) for marker in package.MARKERS
    }
    expected_provenance = {
        value: patches.provenance_counts[value]
        for value in sorted(patches.provenance_counts)
    }
    if (
        report.get("marker_patch_counts") != expected_markers
        or report.get("mpp_provenance_counts") != expected_provenance
    ):
        raise DepositError("validation_report.json counts do not match patches")


def _validate_inner_checksums(
    members: dict[str, bytes],
    patches: PatchBundle,
) -> None:
    expected_sha: dict[str, str] = {}
    expected_md5: dict[str, str] = {}
    for case_members in patches.members_by_case.values():
        for name, digest in case_members.items():
            expected_sha[name] = digest.sha256
            expected_md5[name] = digest.md5
    for name in (
        package.PATCH_MANIFEST,
        package.CASE_MARKER_COUNTS,
        package.VALIDATION_REPORT,
    ):
        digest = _digest_bytes(members[name])
        expected_sha[name] = digest.sha256
        expected_md5[name] = digest.md5
    observed_sha = _parse_checksum_bytes(
        members[package.SOURCE_SHA256SUMS], "sha256", "bundle/SHA256SUMS"
    )
    observed_md5 = _parse_checksum_bytes(
        members[package.SOURCE_MD5SUMS], "md5", "bundle/MD5SUMS"
    )
    if observed_sha != expected_sha or observed_md5 != expected_md5:
        raise DepositError("Manifest-bundle checksum rosters do not match patches")


def _verify_case_archives(
    root: Path,
    patches: PatchBundle,
) -> dict[str, package.FileDigest]:
    result: dict[str, package.FileDigest] = {}
    for alias in sorted(patches.members_by_case):
        name = f"{alias}.zip"
        path = root / name
        _package_call(
            package.verify_zip,
            path,
            patches.members_by_case[alias],
            require_zip64=True,
        )
        result[name] = _package_call(package.digest_file, path)
    return result


def _validate_archive_manifest(
    payload: bytes,
    patches: PatchBundle,
    archives: dict[str, package.FileDigest],
) -> None:
    rows = _read_csv_bytes(
        payload,
        package.ARCHIVE_COLUMNS,
        package.ARCHIVE_MANIFEST,
    )
    if len(rows) != EXPECTED_CASES:
        raise DepositError("archive_manifest.csv has an unexpected row count")
    observed_aliases: list[str] = []
    for line_number, row in enumerate(rows, start=2):
        alias = str(row.get("case_alias", ""))
        name = str(row.get("archive_filename", ""))
        expected_name = f"{alias}.zip"
        digest = archives.get(name)
        members = patches.members_by_case.get(alias)
        if (
            row.get("schema_version") != str(package.SCHEMA_VERSION)
            or name != expected_name
            or digest is None
            or members is None
        ):
            raise DepositError(f"Invalid archive manifest row at line {line_number}")
        expected_values = {
            "member_count": len(members),
            "uncompressed_bytes": sum(item.size for item in members.values()),
            "archive_size_bytes": digest.size,
        }
        if (
            any(
                _positive_int(row.get(field), f"{field} at archive line {line_number}")
                != value
                for field, value in expected_values.items()
            )
            or row.get("sha256") != digest.sha256
            or row.get("md5") != digest.md5
        ):
            raise DepositError(f"Archive manifest mismatch at line {line_number}")
        observed_aliases.append(alias)
    if observed_aliases != sorted(patches.members_by_case):
        raise DepositError("archive_manifest.csv ordering is not exact")


def _validate_packaging_report(
    path: Path,
    archives: dict[str, package.FileDigest],
    bundle_digest: package.FileDigest,
) -> package.FileDigest:
    try:
        text = path.read_text(encoding="utf-8")
        report = json.loads(text)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DepositError("packaging_report.json is invalid") from exc
    if not isinstance(report, dict) or set(report) != PACKAGING_REPORT_KEYS:
        raise DepositError("packaging_report.json key roster is not exact")
    required = {
        "schema_version": package.SCHEMA_VERSION,
        "status": "packaged",
        "draft_only": True,
        "network_used": False,
        "upload_performed": False,
        "publication_performed": False,
        "source_retained": True,
        "case_count": EXPECTED_CASES,
        "patch_count": EXPECTED_PATCHES,
        "case_archive_count": EXPECTED_CASES,
        "upload_file_count": EXPECTED_UPLOAD_FILES,
        "maximum_upload_file_count": package.MAX_ZENODO_UPLOAD_FILES,
        "archive_compression": "ZIP_STORED",
        "disk_tradeoff": PACKAGING_DISK_TRADEOFF,
        "zip_member_timestamp": "1980-01-01T00:00:00",
        "case_archive_bytes": sum(item.size for item in archives.values()),
        "manifest_bundle_bytes": bundle_digest.size,
        "manifest_bundle": package.MANIFEST_BUNDLE,
        "manifest_bundle_members": list(EXPECTED_BUNDLE_MEMBERS),
        "verification": PACKAGING_VERIFICATION,
        "privacy_scope": PACKAGING_PRIVACY_SCOPE,
    }
    if any(report.get(key) != value for key, value in required.items()):
        raise DepositError("packaging_report.json fixed fields are invalid")
    for key in (
        "source_tree_bytes",
        "estimated_additional_disk_bytes",
    ):
        if type(report.get(key)) is not int or report[key] <= 0:
            raise DepositError(f"packaging_report.json has invalid {key}")
    return _package_call(package.digest_file, path)


def validate_package_directory(package_dir: Path) -> ValidatedPackage:
    candidate = package_dir.expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_dir():
        raise DepositError("--package-dir must be a non-symlink directory")
    root = candidate.resolve()
    entries = list(root.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise DepositError("Package directory contains a non-regular entry")
    names = {path.name for path in entries}
    case_names = sorted(name for name in names if CASE_ARCHIVE_RE.fullmatch(name))
    expected_names = set(case_names) | set(CORE_AUXILIARY_FILES)
    if (
        len(case_names) != EXPECTED_CASES
        or len(names) != EXPECTED_UPLOAD_FILES
        or names != expected_names
    ):
        raise DepositError(
            "Package directory must contain exactly 51 case ZIPs and four "
            "allowlisted auxiliary files"
        )
    for name in names:
        base.safe_remote_name(name)

    bundle_path = root / package.MANIFEST_BUNDLE
    bundle_members = _read_manifest_bundle(bundle_path)
    case_aliases = {CASE_ARCHIVE_RE.fullmatch(name).group(1) for name in case_names}
    patches = _parse_patch_manifest(
        bundle_members[package.PATCH_MANIFEST],
        case_aliases,
    )
    _validate_case_marker_counts(
        bundle_members[package.CASE_MARKER_COUNTS],
        patches,
    )
    _validate_preparation_report(
        bundle_members[package.VALIDATION_REPORT],
        patches,
    )
    _validate_inner_checksums(bundle_members, patches)
    archive_digests = _verify_case_archives(root, patches)
    _validate_archive_manifest(
        bundle_members[package.ARCHIVE_MANIFEST],
        patches,
        archive_digests,
    )
    bundle_digest = _package_call(package.digest_file, bundle_path)
    report_digest = _validate_packaging_report(
        root / package.PACKAGING_REPORT,
        archive_digests,
        bundle_digest,
    )

    expected_outer: dict[str, package.FileDigest] = dict(archive_digests)
    expected_outer[package.MANIFEST_BUNDLE] = bundle_digest
    expected_outer[package.PACKAGING_REPORT] = report_digest
    outer_sha = _parse_checksum_bytes(
        (root / package.UPLOAD_SHA256SUMS).read_bytes(),
        "sha256",
        package.UPLOAD_SHA256SUMS,
    )
    outer_md5 = _parse_checksum_bytes(
        (root / package.UPLOAD_MD5SUMS).read_bytes(),
        "md5",
        package.UPLOAD_MD5SUMS,
    )
    expected_payload_names = set(expected_outer)
    if (
        set(outer_sha) != expected_payload_names
        or set(outer_md5) != expected_payload_names
    ):
        raise DepositError("Outer checksum rosters are not exact")
    for name, digest in expected_outer.items():
        if outer_sha[name] != digest.sha256 or outer_md5[name] != digest.md5:
            raise DepositError(f"Outer checksum mismatch: {name}")

    all_digests = dict(expected_outer)
    all_digests[package.UPLOAD_SHA256SUMS] = _package_call(
        package.digest_file, root / package.UPLOAD_SHA256SUMS
    )
    all_digests[package.UPLOAD_MD5SUMS] = _package_call(
        package.digest_file, root / package.UPLOAD_MD5SUMS
    )
    uploads: list[base.UploadFile] = []
    for name in sorted(all_digests, key=str.casefold):
        digest = all_digests[name]
        if digest.size > base.ZENODO_MAX_FILE_BYTES:
            raise DepositError(f"File exceeds Zenodo's 50 GB limit: {name}")
        kind = "case-archive" if name in archive_digests else "release-metadata"
        uploads.append(
            base.UploadFile(
                root / name,
                name,
                digest.size,
                digest.sha256,
                digest.md5,
                kind,
            )
        )
    total_size = sum(item.size_bytes for item in uploads)
    if total_size > ZENODO_MAX_ALLOCATED_BYTES:
        raise DepositError("Package exceeds Zenodo's maximum allocatable record quota")
    file_fingerprint = hashlib.sha256()
    for upload in uploads:
        file_fingerprint.update(upload.remote_name.encode("ascii"))
        file_fingerprint.update(b"\x00")
        file_fingerprint.update(upload.sha256.encode("ascii"))
        file_fingerprint.update(b"\n")
    return ValidatedPackage(
        root,
        tuple(uploads),
        tuple(case_names),
        total_size,
        file_fingerprint.hexdigest(),
    )


def _required_metadata_text(
    payload: dict[str, object],
    field: str,
) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise DepositError(f"Zenodo metadata requires nonempty {field}")
    return value.strip()


def _validate_creators(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise DepositError("Zenodo metadata requires at least one named creator")
    result: list[dict[str, object]] = []
    for index, creator in enumerate(value, start=1):
        if not isinstance(creator, dict):
            raise DepositError(f"Zenodo creator {index} is not an object")
        if set(creator) - ALLOWED_CREATOR_FIELDS:
            raise DepositError(f"Zenodo creator {index} has unsupported fields")
        cleaned: dict[str, object] = {"name": _required_metadata_text(creator, "name")}
        for field in ("affiliation", "orcid", "gnd"):
            if field in creator:
                cleaned[field] = _required_metadata_text(creator, field)
        if "orcid" in cleaned and not ORCID_RE.fullmatch(str(cleaned["orcid"])):
            raise DepositError(f"Zenodo creator {index} has an invalid ORCID")
        result.append(cleaned)
    return result


def _canonical_license_id(value: str) -> str:
    folded = value.strip().casefold()
    return LICENSE_CANONICAL_IDS.get(folded, folded)


def _validate_related_identifiers(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise DepositError("Zenodo related_identifiers must be a nonempty list")
    result: list[dict[str, object]] = []
    for index, related in enumerate(value, start=1):
        if not isinstance(related, dict):
            raise DepositError(f"Zenodo related identifier {index} is not an object")
        if set(related) - ALLOWED_RELATED_IDENTIFIER_FIELDS:
            raise DepositError(
                f"Zenodo related identifier {index} has unsupported fields"
            )
        if not {"identifier", "relation", "scheme"}.issubset(related):
            raise DepositError(
                f"Zenodo related identifier {index} requires identifier, relation, "
                "and scheme"
            )
        scheme = _required_metadata_text(related, "scheme").casefold()
        if scheme not in RELATED_IDENTIFIER_SCHEMES:
            raise DepositError(
                f"Zenodo related identifier {index} has an unsupported scheme"
            )
        relation = RELATED_RELATION_BY_CASEFOLD.get(
            _required_metadata_text(related, "relation").casefold()
        )
        if relation is None:
            raise DepositError(
                f"Zenodo related identifier {index} has an unsupported relation"
            )
        identifier = _required_metadata_text(related, "identifier")
        normalized_identifier = _normalized_identifier(identifier)
        if scheme == "doi":
            if normalized_identifier is None or not normalized_identifier.startswith(
                "doi:"
            ):
                raise DepositError(f"Zenodo related identifier {index} is not a DOI")
            identifier = normalized_identifier[4:]
        elif normalized_identifier is not None and normalized_identifier.startswith(
            "doi:"
        ):
            raise DepositError(
                f"Zenodo related identifier {index} conflicts with detected DOI scheme"
            )
        cleaned: dict[str, object] = {
            "identifier": identifier,
            "relation": relation,
            "scheme": scheme,
        }
        if "resource_type" in related:
            cleaned["resource_type"] = _required_metadata_text(related, "resource_type")
        result.append(cleaned)
    return result


def public_metadata_from_file(path: Path) -> dict[str, object]:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_file():
        raise DepositError("Zenodo metadata must be a regular non-symlink file")
    payload = base.load_json(candidate, "Zenodo metadata file")
    if "metadata" in payload:
        if set(payload) - {"metadata", "template_status"}:
            raise DepositError("Zenodo metadata wrapper has unexpected fields")
        raw = payload.get("metadata")
    else:
        raw = payload
    if not isinstance(raw, dict):
        raise DepositError("Zenodo metadata must be a JSON object")
    metadata = dict(raw)
    unexpected = sorted(set(metadata) - ALLOWED_METADATA_FIELDS)
    if unexpected:
        raise DepositError(
            "Zenodo metadata contains unsupported fields: " + ", ".join(unexpected)
        )
    for field in ("title", "description", "upload_type", "access_right", "license"):
        metadata[field] = _required_metadata_text(metadata, field)
    if metadata["upload_type"].casefold() != "dataset":
        raise DepositError("Zenodo upload_type must be dataset")
    if metadata["access_right"].casefold() != "open":
        raise DepositError("Breast-IHC Zenodo metadata must use access_right=open")
    metadata["creators"] = _validate_creators(metadata.get("creators"))
    metadata["upload_type"] = "dataset"
    metadata["access_right"] = "open"
    metadata["license"] = _canonical_license_id(str(metadata["license"]))
    if "keywords" in metadata:
        keywords = metadata["keywords"]
        if (
            not isinstance(keywords, list)
            or not keywords
            or any(
                not isinstance(value, str) or not value.strip() for value in keywords
            )
        ):
            raise DepositError("Zenodo keywords must be a nonempty string list")
        metadata["keywords"] = [value.strip() for value in keywords]
    if "related_identifiers" in metadata:
        metadata["related_identifiers"] = _validate_related_identifiers(
            metadata["related_identifiers"]
        )
    for field in ("version", "publication_date", "notes"):
        if field in metadata:
            metadata[field] = _required_metadata_text(metadata, field)
    if "language" in metadata:
        language = _required_metadata_text(metadata, "language").casefold()
        if not LANGUAGE_RE.fullmatch(language):
            raise DepositError("Zenodo language must be a canonical three-letter code")
        metadata["language"] = language
    publication_date = metadata.get("publication_date")
    if publication_date is not None:
        try:
            parsed_publication_date = date.fromisoformat(str(publication_date))
        except ValueError as exc:
            raise DepositError(
                "Zenodo publication_date must be a valid YYYY-MM-DD date"
            ) from exc
        metadata["publication_date"] = parsed_publication_date.isoformat()
    encoded = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    if base.UNRESOLVED_PLACEHOLDER_RE.search(encoded):
        raise DepositError("Zenodo metadata contains an unresolved placeholder")
    return metadata


def validated_api_url(value: str) -> str:
    url = value.strip().rstrip("/")
    parsed = urlparse(url)
    if (
        url not in ALLOWED_API_URLS
        or parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise DepositError(
            "--api-url must be exactly https://zenodo.org/api or "
            "https://sandbox.zenodo.org/api"
        )
    return url


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _private_file(path: Path, label: str) -> Path:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_file():
        raise DepositError(f"{label} must be a regular non-symlink file")
    observed = candidate.stat()
    if stat.S_IMODE(observed.st_mode) != 0o600:
        raise DepositError(f"{label} must have exact mode 0600")
    if hasattr(os, "getuid") and observed.st_uid != os.getuid():
        raise DepositError(f"{label} must be owned by the current user")
    if observed.st_nlink != 1:
        raise DepositError(f"{label} must not have additional hard links")
    return candidate.resolve()


def resolve_deposit_write_token(token_file: Path, package_root: Path) -> str:
    path = _private_file(token_file, "Zenodo deposit:write token file")
    if _is_within(path, package_root):
        raise DepositError("Zenodo token file must be outside --package-dir")
    token = path.read_text(encoding="utf-8").strip()
    if not token or any(character.isspace() for character in token):
        raise DepositError("Zenodo token is empty or contains whitespace")
    return token


def _load_bound_state(
    state_file: Path,
    package_root: Path,
    api_url: str,
    fingerprint: str,
    uploads: tuple[base.UploadFile, ...],
) -> tuple[Path, dict[str, object] | None]:
    candidate = state_file.expanduser().absolute()
    resolved = candidate.resolve(strict=False)
    if _is_within(resolved, package_root):
        raise DepositError("Deposit state must be outside --package-dir")
    if not candidate.exists():
        if candidate.is_symlink():
            raise DepositError("Refusing a symlink deposit state")
        return resolved, None
    path = _private_file(candidate, "Zenodo deposit state")
    state = base.load_json(path, "Zenodo deposit state")
    expected_keys = {
        "schema_version",
        "dataset_format",
        "api_url",
        "deposition_id",
        "release_fingerprint_sha256",
        "file_count",
        "total_size_bytes",
        "status",
        "uploaded",
    }
    if set(state) != expected_keys:
        raise DepositError("Deposit state key roster is invalid")
    if (
        state.get("schema_version") != 1
        or state.get("dataset_format") != DATASET_FORMAT
        or state.get("api_url") != api_url
        or state.get("release_fingerprint_sha256") != fingerprint
        or state.get("file_count") != EXPECTED_UPLOAD_FILES
        or state.get("total_size_bytes") != sum(upload.size_bytes for upload in uploads)
        or state.get("status") != "draft"
    ):
        raise DepositError("Deposit state is not bound to this exact release")
    deposition_id = str(state.get("deposition_id", ""))
    uploaded = state.get("uploaded")
    expected_names = {upload.remote_name for upload in uploads}
    if (
        not deposition_id.isdigit()
        or not isinstance(uploaded, dict)
        or not set(uploaded).issubset(expected_names)
        or any(not isinstance(value, dict) for value in uploaded.values())
    ):
        raise DepositError("Deposit state contains invalid progress data")
    uploads_by_name = {upload.remote_name: upload for upload in uploads}
    for name, value in uploaded.items():
        upload = uploads_by_name[name]
        if (
            set(value) != {"size_bytes", "md5", "status"}
            or value.get("size_bytes") != upload.size_bytes
            or value.get("md5") != upload.md5
            or value.get("status") not in {"uploaded", "verified-existing"}
        ):
            raise DepositError("Deposit state contains invalid progress data")
    return path, state


def _semantic_text_equal(actual: object, expected: object) -> bool:
    return (
        isinstance(actual, str)
        and isinstance(expected, str)
        and unescape(actual) == unescape(expected)
    )


def _creators_match(actual: object, expected: object) -> bool:
    if (
        not isinstance(actual, list)
        or not isinstance(expected, list)
        or len(actual) != len(expected)
    ):
        return False
    for actual_creator, expected_creator in zip(actual, expected):
        if not isinstance(actual_creator, dict) or not isinstance(
            expected_creator, dict
        ):
            return False
        for key, expected_value in expected_creator.items():
            if key not in actual_creator:
                return False
            observed = actual_creator[key]
            if isinstance(expected_value, str):
                if not _semantic_text_equal(observed, expected_value):
                    return False
            elif observed != expected_value:
                return False
    return True


def _normalized_identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = unescape(value).strip()
    folded = text.casefold()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
    ):
        if folded.startswith(prefix):
            return "doi:" + folded[len(prefix) :]
    if re.fullmatch(r"10\.[0-9]{4,9}/\S+", text, re.IGNORECASE):
        return "doi:" + folded
    return text


def _related_identifiers_match(actual: object, expected: object) -> bool:
    if (
        not isinstance(actual, list)
        or not isinstance(expected, list)
        or len(actual) != len(expected)
    ):
        return False
    remaining = list(actual)
    for expected_item in expected:
        if not isinstance(expected_item, dict):
            return False
        match_index = None
        for index, actual_item in enumerate(remaining):
            if not isinstance(actual_item, dict):
                continue
            fields_match = True
            for key, expected_value in expected_item.items():
                observed = actual_item.get(key)
                if key == "identifier":
                    equal = _normalized_identifier(observed) == _normalized_identifier(
                        expected_value
                    )
                elif key == "scheme":
                    equal = (
                        isinstance(observed, str)
                        and isinstance(expected_value, str)
                        and observed.casefold() == expected_value.casefold()
                    )
                elif key == "relation":
                    observed_relation = (
                        RELATED_RELATION_BY_CASEFOLD.get(observed.casefold())
                        if isinstance(observed, str)
                        else None
                    )
                    equal = observed_relation == expected_value
                elif isinstance(expected_value, str):
                    equal = _semantic_text_equal(observed, expected_value)
                else:
                    equal = observed == expected_value
                if not equal:
                    fields_match = False
                    break
            if fields_match:
                match_index = index
                break
        if match_index is None:
            return False
        remaining.pop(match_index)
    return True


def validate_unpublished_editable(payload: dict[str, object]) -> None:
    if payload.get("submitted") is not False:
        raise DepositError("Zenodo deposition is not an unpublished draft")
    state = payload.get("state")
    if state not in {None, "inprogress", "unsubmitted"}:
        raise DepositError("Zenodo deposition is not editable")


def validate_open_unpublished_draft(
    payload: dict[str, object],
    expected_metadata: dict[str, object],
) -> None:
    validate_unpublished_editable(payload)
    actual = payload.get("metadata")
    if not isinstance(actual, dict):
        raise DepositError("Zenodo draft response has no metadata object")
    if str(actual.get("access_right", "")).casefold() != "open":
        raise DepositError("Zenodo draft is not configured for open access")
    for field, expected in expected_metadata.items():
        observed = actual.get(field)
        if field == "creators":
            matches = _creators_match(observed, expected)
        elif field == "related_identifiers":
            matches = _related_identifiers_match(observed, expected)
        elif field in {"title", "description", "notes"}:
            matches = _semantic_text_equal(observed, expected)
        elif field == "license":
            matches = (
                isinstance(observed, str)
                and isinstance(expected, str)
                and _canonical_license_id(observed) == _canonical_license_id(expected)
            )
        elif field in {"upload_type", "access_right", "language"}:
            matches = (
                isinstance(observed, str)
                and isinstance(expected, str)
                and observed.casefold() == expected.casefold()
            )
        else:
            matches = observed == expected
        if not matches:
            raise DepositError(
                f"Zenodo draft metadata does not match requested {field}"
            )


def strict_remote_files(
    payload: dict[str, object],
    *,
    api_url: str,
    deposition_id: str,
) -> dict[str, base.RemoteFile]:
    api_url = validated_api_url(api_url)
    if not deposition_id.isdigit():
        raise DepositError("Zenodo deposition ID must be numeric")
    raw_files = payload.get("files")
    if not isinstance(raw_files, list):
        raise DepositError("Zenodo draft response has no valid files array")
    raw_by_name: dict[str, dict[str, object]] = {}
    for item in raw_files:
        if not isinstance(item, dict):
            raise DepositError("Zenodo draft contains an invalid file object")
        name = str(item.get("filename") or item.get("key") or "").strip()
        base.safe_remote_name(name)
        if name in raw_by_name:
            raise DepositError(f"Draft contains duplicate file name: {name}")
        raw_by_name[name] = item
    files = base.parse_remote_files(payload)
    if len(files) != len(raw_files):
        raise DepositError("Zenodo draft file response is incomplete")
    if any(item.size_bytes is None or item.md5 is None for item in files.values()):
        raise DepositError("Zenodo draft file metadata lacks size or MD5")
    result: dict[str, base.RemoteFile] = {}
    for name, remote in files.items():
        delete_url = remote.delete_url
        if not delete_url:
            remote_id = str(raw_by_name[name].get("id") or "").strip()
            if remote_id:
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,255}", remote_id):
                    raise DepositError(
                        f"Zenodo draft has an unsafe file identifier: {name}"
                    )
                delete_url = (
                    f"{api_url}/deposit/depositions/{deposition_id}/files/"
                    f"{quote(remote_id, safe='')}"
                )
        result[name] = base.RemoteFile(
            remote.name,
            remote.size_bytes,
            remote.md5,
            delete_url,
        )
    return result


class HardenedZenodoClient(base.ZenodoClient):
    def __init__(
        self,
        token: str,
        api_url: str = DEFAULT_API_URL,
        *,
        retries: int = 5,
        session=None,
    ) -> None:
        super().__init__(
            token,
            validated_api_url(api_url),
            retries=retries,
            session=session,
        )

    def create_draft(self) -> dict[str, object]:
        response = self.request(
            "POST",
            f"{self.api_url}/deposit/depositions",
            expected=(201,),
            json_body={},
            retries=0,
        )
        return self.json_response(response, "Create-deposition request")


def validate_upload_response(
    payload: dict[str, object],
    upload: base.UploadFile,
) -> None:
    name = str(payload.get("key") or payload.get("filename") or "").strip()
    if name != upload.remote_name:
        raise DepositError(f"Zenodo upload response named the wrong file: {name!r}")
    raw_size = payload.get("size")
    if raw_size is None:
        raw_size = payload.get("filesize")
    try:
        size = int(raw_size)
    except (TypeError, ValueError) as exc:
        raise DepositError("Zenodo upload response omitted a valid file size") from exc
    checksum = str(payload.get("checksum") or "").strip().casefold()
    if checksum.startswith("md5:"):
        checksum = checksum[4:]
    if size != upload.size_bytes or checksum != upload.md5:
        raise DepositError(f"Zenodo upload verification failed: {upload.remote_name}")


def _plan_result(
    package_data: ValidatedPackage,
    fingerprint: str,
) -> dict[str, object]:
    additional = max(
        0,
        package_data.total_size_bytes - ZENODO_DEFAULT_QUOTA_BYTES,
    )
    return {
        "draft_only": True,
        "publication_capability": False,
        "access_right": "open",
        "file_count": len(package_data.uploads),
        "case_archive_count": len(package_data.case_archives),
        "patch_count": EXPECTED_PATCHES,
        "total_size_bytes": package_data.total_size_bytes,
        "default_quota_bytes": ZENODO_DEFAULT_QUOTA_BYTES,
        "additional_quota_required_bytes": additional,
        "requires_additional_quota": additional > 0,
        "release_fingerprint_sha256": fingerprint,
        "package_files_sha256": package_data.release_files_sha256,
        "files": [
            {
                "name": upload.remote_name,
                "size_bytes": upload.size_bytes,
                "kind": upload.kind,
            }
            for upload in package_data.uploads
        ],
    }


def _draft_html_fallback(api_url: str, deposition_id: str) -> str:
    parsed = urlparse(api_url)
    return f"{parsed.scheme}://{parsed.netloc}/deposit/{deposition_id}"


def deposit_breast_ihc(
    *,
    package_dir: Path,
    metadata_file: Path,
    state_file: Path,
    token_file: Path | None = None,
    api_url: str = DEFAULT_API_URL,
    retries: int = 5,
    replace_mismatched: bool = False,
    confirmed_quota_bytes: int | None = None,
    create_only: bool = False,
    plan: bool = False,
    session=None,
) -> dict[str, object]:
    if plan and create_only:
        raise DepositError("--plan and --create-only are mutually exclusive")
    if create_only and replace_mismatched:
        raise DepositError("--create-only cannot replace remote files")
    if retries < 0:
        raise DepositError("--retries must be non-negative")
    api_url = validated_api_url(api_url)
    package_data = validate_package_directory(package_dir)
    metadata = public_metadata_from_file(metadata_file)
    fingerprint = base.release_fingerprint(metadata, list(package_data.uploads))
    plan_result = _plan_result(package_data, fingerprint)
    if plan:
        return {"plan": True, **plan_result}
    if token_file is None:
        raise DepositError("A mode-0600 --token-file with deposit:write is required")
    if confirmed_quota_bytes is not None and (
        confirmed_quota_bytes < 0 or confirmed_quota_bytes > ZENODO_MAX_ALLOCATED_BYTES
    ):
        raise DepositError("--confirmed-quota-bytes is outside Zenodo limits")
    if (
        not create_only
        and package_data.total_size_bytes > ZENODO_DEFAULT_QUOTA_BYTES
        and (
            confirmed_quota_bytes is None
            or confirmed_quota_bytes < package_data.total_size_bytes
        )
    ):
        raise DepositError(
            "Package exceeds the default quota; run --create-only, allocate quota, "
            "then pass --confirmed-quota-bytes"
        )

    token = resolve_deposit_write_token(token_file, package_data.root)
    state_path, state = _load_bound_state(
        state_file,
        package_data.root,
        api_url,
        fingerprint,
        package_data.uploads,
    )
    client = HardenedZenodoClient(
        token,
        api_url,
        retries=retries,
        session=session,
    )
    if state is None:
        draft = client.create_draft()
        deposition_id = base.deposition_id_from_payload(draft)
        state = {
            "schema_version": 1,
            "dataset_format": DATASET_FORMAT,
            "api_url": api_url,
            "deposition_id": deposition_id,
            "release_fingerprint_sha256": fingerprint,
            "file_count": EXPECTED_UPLOAD_FILES,
            "total_size_bytes": package_data.total_size_bytes,
            "status": "draft",
            "uploaded": {},
        }
        base.atomic_json(state_path, state)
    else:
        deposition_id = str(state["deposition_id"])
        draft = client.get_draft(deposition_id)

    initial_remote = strict_remote_files(
        draft, api_url=api_url, deposition_id=deposition_id
    )
    expected_names = {upload.remote_name for upload in package_data.uploads}
    unexpected = sorted(set(initial_remote) - expected_names)
    if unexpected:
        raise DepositError("Zenodo draft contains unreviewed extra files")
    validate_unpublished_editable(draft)

    updated = client.update_metadata(deposition_id, metadata)
    validate_open_unpublished_draft(updated, metadata)
    refreshed = client.get_draft(deposition_id)
    validate_open_unpublished_draft(refreshed, metadata)
    remote_files = strict_remote_files(
        refreshed, api_url=api_url, deposition_id=deposition_id
    )
    unexpected = sorted(set(remote_files) - expected_names)
    if unexpected:
        raise DepositError("Zenodo draft contains unreviewed extra files")

    uploads_by_name = {upload.remote_name: upload for upload in package_data.uploads}
    for name, remote in remote_files.items():
        if not base.file_matches(remote, uploads_by_name[name]) and create_only:
            raise DepositError(f"Create-only draft has a mismatched file: {name}")
    if create_only:
        state["status"] = "draft"
        base.atomic_json(state_path, state)
        links = (
            refreshed.get("links") if isinstance(refreshed.get("links"), dict) else {}
        )
        return {
            "plan": False,
            "create_only": True,
            "status": "open-access-unpublished-draft",
            "deposition_id": deposition_id,
            "draft_url": str(
                links.get("html") or _draft_html_fallback(api_url, deposition_id)
            ),
            "remote_file_count": len(remote_files),
            **plan_result,
        }

    # Re-hash all 55 local files before any optional remote deletion.
    for upload in package_data.uploads:
        base.verify_local(upload)
    mismatched = [
        (upload, remote_files.get(upload.remote_name))
        for upload in package_data.uploads
        if remote_files.get(upload.remote_name) is not None
        and not base.file_matches(remote_files[upload.remote_name], upload)
    ]
    if mismatched and not replace_mismatched:
        raise DepositError(
            f"Draft file differs from local package: {mismatched[0][0].remote_name}; "
            "use --replace-mismatched only after review"
        )
    if any(remote is None or not remote.delete_url for _upload, remote in mismatched):
        raise DepositError("Zenodo omitted a deletion URL for a mismatched file")

    bucket_url = base.bucket_from_payload(refreshed)
    uploaded_state = state.get("uploaded")
    if not isinstance(uploaded_state, dict):
        raise DepositError("Deposit state uploaded map is invalid")
    for upload in package_data.uploads:
        existing = remote_files.get(upload.remote_name)
        if existing is not None and base.file_matches(existing, upload):
            status = "verified-existing"
        else:
            if existing is not None:
                client.delete_file(existing.delete_url)
            response = client.upload_file(bucket_url, upload)
            validate_upload_response(response, upload)
            status = "uploaded"
        uploaded_state[upload.remote_name] = {
            "size_bytes": upload.size_bytes,
            "md5": upload.md5,
            "status": status,
        }
        base.atomic_json(state_path, state)
        print(f"{status}: {upload.remote_name}", file=sys.stderr, flush=True)

    verified = client.get_draft(deposition_id)
    validate_open_unpublished_draft(verified, metadata)
    verified_remote = strict_remote_files(
        verified, api_url=api_url, deposition_id=deposition_id
    )
    if set(verified_remote) != expected_names:
        raise DepositError("Final Zenodo draft file roster is not exact")
    for upload in package_data.uploads:
        if not base.file_matches(verified_remote[upload.remote_name], upload):
            raise DepositError(
                f"Final Zenodo draft verification failed: {upload.remote_name}"
            )
    state["status"] = "draft"
    base.atomic_json(state_path, state)
    links = verified.get("links") if isinstance(verified.get("links"), dict) else {}
    return {
        "plan": False,
        "create_only": False,
        "status": "open-access-unpublished-draft",
        "deposition_id": deposition_id,
        "draft_url": str(
            links.get("html") or _draft_html_fallback(api_url, deposition_id)
        ),
        "remote_file_count": len(verified_remote),
        **plan_result,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument(
        "--token-file",
        type=Path,
        help="Mode-0600 Zenodo token file with deposit:write only",
    )
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--replace-mismatched", action="store_true")
    parser.add_argument("--confirmed-quota-bytes", type=int)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--plan",
        action="store_true",
        help="Fully validate locally without a token or network request",
    )
    actions.add_argument(
        "--create-only",
        action="store_true",
        help="Create/verify the draft without uploading, then stop for quota allocation",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = deposit_breast_ihc(
            package_dir=args.package_dir,
            metadata_file=args.metadata,
            state_file=args.state,
            token_file=args.token_file,
            api_url=args.api_url,
            retries=args.retries,
            replace_mismatched=args.replace_mismatched,
            confirmed_quota_bytes=args.confirmed_quota_bytes,
            create_only=args.create_only,
            plan=args.plan,
        )
    except (DepositError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
