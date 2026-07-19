#!/usr/bin/env python3
"""Create, resume, verify, and optionally publish a Zenodo WSI deposit.

The default outcome is a draft.  Publication requires both ``--publish`` and
an independent authorization JSON that explicitly confirms de-identification,
redistribution rights, licensing, metadata review, and publication finality.
Tokens are accepted only from an environment variable or a mode-0600 file.
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
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Iterable
from urllib.parse import quote, urlparse

import requests


DEFAULT_API_URL = "https://zenodo.org/api"
DEFAULT_TOKEN_ENV = "ZENODO_TOKEN"
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
SAFE_REMOTE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HEX_MD5_RE = re.compile(r"^[0-9a-f]{32}$")
ALIAS_RE = re.compile(r"^TumorQuantAI_LymphomaWSI_[0-9]{3}$")
UNRESOLVED_PLACEHOLDER_RE = re.compile(
    r"\{\{[^{}\n]+\}\}|\bPENDING(?:_[A-Z0-9_]+)?\b|"
    r"\b(?:REPLACE|TODO|TBD)_[A-Z0-9_]+\b"
)
PUBLIC_MANIFEST_COLUMNS = {
    "alias",
    "level",
    "source_mpp",
    "zenodo_filename",
    "dataset_path",
    "size_bytes",
    "sha256",
    "md5",
    "width",
    "height",
    "channels",
    "dtype",
    "photometric",
    "is_tiled",
}
GENERATED_PUBLIC_FILES = {
    "tumorquantai_lymphoma_manifest.csv",
    "samples.csv",
    "SHA256SUMS",
    "MD5SUMS",
    "tiff_validation_report.json",
}
ZENODO_MAX_FILES = 100
ZENODO_MAX_FILE_BYTES = 50_000_000_000
PUBLISH_CONFIRMATIONS = (
    "deidentification_review_complete",
    "pixel_content_privacy_review_complete",
    "public_redistribution_authorized",
    "dataset_rights_confirmed",
    "license_confirmed",
    "metadata_review_complete",
    "publish_irreversibility_acknowledged",
)
AUTHORIZED_METADATA_FIELDS = (
    "title",
    "description",
    "upload_type",
    "access_right",
    "license",
    "creators",
)


class DepositError(RuntimeError):
    pass


@dataclass(frozen=True)
class UploadFile:
    local_path: Path
    remote_name: str
    size_bytes: int
    sha256: str
    md5: str
    kind: str


@dataclass(frozen=True)
class RemoteFile:
    name: str
    size_bytes: int | None
    md5: str | None
    delete_url: str | None


@dataclass(frozen=True)
class PublicManifestRow:
    alias: str
    level: int
    source_mpp: float
    zenodo_filename: str
    dataset_path: str
    size_bytes: int
    sha256: str
    md5: str
    width: int
    height: int
    channels: int
    dtype: str
    photometric: str
    is_tiled: bool


def safe_remote_name(name: str) -> str:
    value = name.strip()
    if not SAFE_REMOTE_NAME_RE.fullmatch(value) or value in {".", ".."}:
        raise DepositError(f"Unsafe Zenodo file name: {name!r}")
    return value


def secure_file(path: Path, description: str) -> Path:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_file():
        raise DepositError(f"{description} is not a regular file: {candidate}")
    path = candidate.resolve()
    mode = stat.S_IMODE(candidate.stat().st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise DepositError(f"{description} must not be accessible by group/other: {path}")
    return path


def resolve_token(token_env: str, token_file: Path | None) -> str:
    if token_file is not None:
        path = secure_file(token_file, "Zenodo token file")
        token = path.read_text(encoding="utf-8").strip()
    else:
        token = os.environ.get(token_env, "").strip()
    if not token:
        source = str(token_file) if token_file else f"environment variable {token_env}"
        raise DepositError(f"No Zenodo token found in {source}")
    if any(character.isspace() for character in token):
        raise DepositError("Zenodo token contains whitespace")
    return token


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    candidate = path.expanduser().absolute()
    if candidate.exists() and candidate.is_symlink():
        raise DepositError(f"Refusing to write through a symlink: {candidate}")
    path = candidate.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
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


def load_json(path: Path, description: str) -> dict[str, object]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise DepositError(f"{description} does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DepositError(f"{description} is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise DepositError(f"{description} must contain a JSON object")
    return payload


def metadata_from_file(path: Path) -> dict[str, object]:
    payload = load_json(path, "Zenodo metadata file")
    metadata = payload.get("metadata", payload)
    if not isinstance(metadata, dict):
        raise DepositError("Zenodo metadata must be a JSON object")
    required_strings = ("title", "description", "upload_type", "access_right", "license")
    missing = [key for key in required_strings if not str(metadata.get(key, "")).strip()]
    if missing:
        raise DepositError("Zenodo metadata is missing: " + ", ".join(missing))
    if str(metadata["upload_type"]).strip().casefold() != "dataset":
        raise DepositError("Zenodo upload_type must be 'dataset'")
    creators = metadata.get("creators")
    if not isinstance(creators, list) or not creators:
        raise DepositError("Zenodo metadata must contain at least one creator")
    if any(not isinstance(item, dict) or not str(item.get("name", "")).strip() for item in creators):
        raise DepositError("Every Zenodo creator must contain a non-empty name")
    return dict(metadata)


def digest_file(path: Path) -> tuple[int, str, str]:
    before = path.stat()
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            size += len(chunk)
            sha256.update(chunk)
            md5.update(chunk)
    after = path.stat()
    identity = lambda item: (
        item.st_dev,
        item.st_ino,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
    )
    if identity(before) != identity(after):
        raise DepositError(f"File changed while it was verified: {path.name}")
    return size, sha256.hexdigest(), md5.hexdigest()


def make_small_upload(path: Path, remote_name: str, kind: str) -> UploadFile:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_file():
        raise DepositError(f"Upload source is not a regular file: {candidate}")
    path = candidate.resolve()
    size, sha256, md5 = digest_file(path)
    return UploadFile(path, safe_remote_name(remote_name), size, sha256, md5, kind)


def read_csv(
    path: Path,
    required: set[str],
    description: str,
    *,
    exact_columns: set[str] | None = None,
) -> list[dict[str, str]]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise DepositError(f"{description} does not exist: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        if reader.fieldnames is None or not required.issubset(fields):
            missing = required - fields
            raise DepositError(
                f"{description} is missing columns: {', '.join(sorted(missing))}"
            )
        if exact_columns is not None and fields != exact_columns:
            raise DepositError(
                f"{description} columns differ from the preparation-tool schema"
            )
        return [dict(row) for row in reader]


def parse_manifest_bool(value: object, line_number: int, field: str) -> bool:
    text = str(value).strip().casefold()
    if text == "true":
        return True
    if text == "false":
        return False
    raise DepositError(f"Invalid {field} at public manifest line {line_number}")


def load_public_manifest(public_manifest: Path) -> list[PublicManifestRow]:
    raw_rows = read_csv(
        public_manifest,
        PUBLIC_MANIFEST_COLUMNS,
        "Public dataset manifest",
        exact_columns=PUBLIC_MANIFEST_COLUMNS,
    )
    rows: list[PublicManifestRow] = []
    seen_names: set[str] = set()
    seen_paths: set[str] = set()
    levels_by_alias: dict[str, set[int]] = {}
    source_mpps: set[float] = set()
    for line_number, raw in enumerate(raw_rows, start=2):
        alias = str(raw.get("alias", "")).strip()
        try:
            level = int(str(raw.get("level", "")).strip())
            source_mpp = float(str(raw.get("source_mpp", "")).strip())
            size = int(str(raw.get("size_bytes", "")).strip())
            width = int(str(raw.get("width", "")).strip())
            height = int(str(raw.get("height", "")).strip())
            channels = int(str(raw.get("channels", "")).strip())
        except ValueError as exc:
            raise DepositError(
                f"Invalid numeric value at public manifest line {line_number}"
            ) from exc
        if (
            not ALIAS_RE.fullmatch(alias)
            or level not in {0, 2}
            or not math.isfinite(source_mpp)
            or source_mpp <= 0
            or size <= 0
            or width <= 0
            or height <= 0
            or channels not in {1, 3, 4}
        ):
            raise DepositError(
                f"Invalid public manifest value at line {line_number}"
            )
        remote_name = safe_remote_name(
            str(raw.get("zenodo_filename", "")).strip()
        )
        dataset_path = str(raw.get("dataset_path", "")).strip()
        expected_name = f"{alias}_L{level}_rgb.tif"
        expected_path = f"slides/{alias}/1_L{level}_rgb.tif"
        if remote_name != expected_name or dataset_path != expected_path:
            raise DepositError(
                f"Unsafe or inconsistent public mapping at manifest line {line_number}"
            )
        sha256 = str(raw.get("sha256", "")).strip().casefold()
        md5 = str(raw.get("md5", "")).strip().casefold()
        if not HEX_SHA256_RE.fullmatch(sha256) or not HEX_MD5_RE.fullmatch(md5):
            raise DepositError(
                f"Invalid public checksum at manifest line {line_number}"
            )
        if remote_name in seen_names or dataset_path in seen_paths:
            raise DepositError(
                f"Duplicate public file/path at manifest line {line_number}"
            )
        seen_names.add(remote_name)
        seen_paths.add(dataset_path)
        levels_by_alias.setdefault(alias, set()).add(level)
        source_mpps.add(source_mpp)
        rows.append(
            PublicManifestRow(
                alias=alias,
                level=level,
                source_mpp=source_mpp,
                zenodo_filename=remote_name,
                dataset_path=dataset_path,
                size_bytes=size,
                sha256=sha256,
                md5=md5,
                width=width,
                height=height,
                channels=channels,
                dtype=str(raw.get("dtype", "")).strip(),
                photometric=str(raw.get("photometric", "")).strip(),
                is_tiled=parse_manifest_bool(
                    raw.get("is_tiled", ""), line_number, "is_tiled"
                ),
            )
        )
    if not rows:
        raise DepositError("Public dataset manifest is empty")
    incomplete = [
        alias for alias, levels in levels_by_alias.items() if levels != {0, 2}
    ]
    if incomplete:
        raise DepositError(
            f"Public manifest contains {len(incomplete)} incomplete L0/L2 pair(s)"
        )
    if len(source_mpps) != 1:
        raise DepositError(
            "Public manifest must contain one finite, consistent source MPP"
        )
    return rows


def slide_uploads_from_rows(
    public_rows: list[PublicManifestRow], private_mapping: Path
) -> list[UploadFile]:
    mapping_path = secure_file(private_mapping, "Private source mapping")
    private_rows = read_csv(
        mapping_path,
        {"alias", "level", "export_path", "zenodo_filename", "sha256", "md5"},
        "Private source mapping",
    )
    private_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in private_rows:
        key = (str(row["alias"]).strip(), str(row["level"]).strip())
        if key in private_by_key:
            raise DepositError(f"Duplicate private mapping for {key[0]} L{key[1]}")
        private_by_key[key] = row

    uploads: list[UploadFile] = []
    for line_number, row in enumerate(public_rows, start=2):
        key = (row.alias, str(row.level))
        private = private_by_key.get(key)
        if private is None:
            raise DepositError(
                f"No private source mapping for {row.alias} L{row.level}"
            )
        if row.zenodo_filename != str(private.get("zenodo_filename", "")).strip():
            raise DepositError(
                f"Public/private file name mismatch at manifest line {line_number}"
            )
        if (
            row.sha256 != str(private.get("sha256", "")).strip().casefold()
            or row.md5 != str(private.get("md5", "")).strip().casefold()
        ):
            raise DepositError(
                f"Public/private checksum mismatch at manifest line {line_number}"
            )
        source_candidate = Path(
            str(private.get("export_path", "")).strip()
        ).expanduser().absolute()
        if source_candidate.is_symlink() or not source_candidate.is_file():
            raise DepositError(
                f"Mapped WSI export is not a regular file for "
                f"{row.alias} L{row.level}"
            )
        source = source_candidate.resolve()
        if source.stat().st_size != row.size_bytes:
            raise DepositError(
                f"Mapped WSI size changed for {row.alias} L{row.level}"
            )
        uploads.append(
            UploadFile(
                source,
                row.zenodo_filename,
                row.size_bytes,
                row.sha256,
                row.md5,
                "wsi",
            )
        )
    return uploads


def load_slide_uploads(
    public_manifest: Path, private_mapping: Path
) -> list[UploadFile]:
    return slide_uploads_from_rows(
        load_public_manifest(public_manifest), private_mapping
    )


def required_public_artifacts(
    public_dir: Path, public_manifest: Path
) -> dict[str, Path]:
    public_candidate = public_dir.expanduser().absolute()
    if not public_candidate.is_dir() or public_candidate.is_symlink():
        raise DepositError(
            f"Public artifact directory is not a regular directory: {public_candidate}"
        )
    resolved_dir = public_candidate.resolve()
    paths = {name: resolved_dir / name for name in GENERATED_PUBLIC_FILES}
    missing = sorted(name for name, path in paths.items() if not path.exists())
    if missing:
        raise DepositError(
            "Missing required generated public artifact(s): " + ", ".join(missing)
        )
    unsafe = sorted(
        name
        for name, path in paths.items()
        if path.is_symlink() or not path.is_file()
    )
    if unsafe:
        raise DepositError(
            "Generated public artifact(s) are not regular files: "
            + ", ".join(unsafe)
        )
    manifest_candidate = public_manifest.expanduser().absolute()
    if (
        manifest_candidate.is_symlink()
        or manifest_candidate.resolve()
        != paths["tumorquantai_lymphoma_manifest.csv"].resolve()
    ):
        raise DepositError(
            "The public manifest must be the generated manifest in --public-dir"
        )
    return paths


def validate_samples(path: Path, public_rows: list[PublicManifestRow]) -> None:
    rows = read_csv(
        path,
        {"sample_id", "slide_path"},
        "Public sample sheet",
        exact_columns={"sample_id", "slide_path"},
    )
    expected = [
        {
            "sample_id": row.alias,
            "slide_path": row.dataset_path.removeprefix("slides/"),
        }
        for row in public_rows
        if row.level == 0
    ]
    if rows != expected:
        raise DepositError("samples.csv does not exactly match the public manifest")


def validate_checksum_file(
    path: Path,
    public_rows: list[PublicManifestRow],
    *,
    algorithm: str,
) -> None:
    if algorithm == "sha256":
        digest_re = HEX_SHA256_RE
        expected = {row.zenodo_filename: row.sha256 for row in public_rows}
        label = "SHA256SUMS"
    elif algorithm == "md5":
        digest_re = HEX_MD5_RE
        expected = {row.zenodo_filename: row.md5 for row in public_rows}
        label = "MD5SUMS"
    else:  # defensive invariant
        raise DepositError(f"Unsupported checksum algorithm: {algorithm}")
    found: dict[str, str] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        digest, separator, filename = line.partition("  ")
        if (
            not separator
            or not digest_re.fullmatch(digest.casefold())
            or not SAFE_REMOTE_NAME_RE.fullmatch(filename)
        ):
            raise DepositError(f"Invalid {label} entry at line {line_number}")
        if filename in found:
            raise DepositError(f"Duplicate {label} entry for {filename}")
        found[filename] = digest.casefold()
    if found != expected:
        raise DepositError(f"{label} does not exactly match the public manifest")


def validate_public_report(
    path: Path, public_rows: list[PublicManifestRow]
) -> None:
    report = load_json(path, "TIFF validation report")
    pair_count = len({row.alias for row in public_rows})
    total_size = sum(row.size_bytes for row in public_rows)
    if report.get("status") != "passed":
        raise DepositError("TIFF validation report did not pass")
    if (
        type(report.get("pair_count")) is not int
        or report["pair_count"] != pair_count
        or type(report.get("file_count")) is not int
        or report["file_count"] != len(public_rows)
        or type(report.get("total_size_bytes")) is not int
        or report["total_size_bytes"] != total_size
    ):
        raise DepositError(
            "TIFF validation report counts/sizes do not match the public manifest"
        )
    try:
        report_mpp = float(report.get("source_mpp"))
    except (TypeError, ValueError) as exc:
        raise DepositError("TIFF validation report has invalid source MPP") from exc
    manifest_mpp = public_rows[0].source_mpp
    if (
        not math.isfinite(report_mpp)
        or report_mpp <= 0
        or f"{report_mpp:.6f}" != f"{manifest_mpp:.6f}"
    ):
        raise DepositError(
            "TIFF validation report source MPP does not match the public manifest"
        )
    raw_files = report.get("files")
    if not isinstance(raw_files, list) or len(raw_files) != len(public_rows):
        raise DepositError(
            "TIFF validation report files do not match the public manifest"
        )
    expected = {(row.alias, row.level): row for row in public_rows}
    seen: set[tuple[str, int]] = set()
    for item in raw_files:
        if not isinstance(item, dict):
            raise DepositError("TIFF validation report contains an invalid file entry")
        try:
            key = (str(item.get("alias", "")).strip(), int(item.get("level")))
        except (TypeError, ValueError) as exc:
            raise DepositError(
                "TIFF validation report contains an invalid alias/level"
            ) from exc
        row = expected.get(key)
        if row is None or key in seen:
            raise DepositError(
                "TIFF validation report files do not match the public manifest"
            )
        seen.add(key)
        if (
            item.get("status") != "passed"
            or str(item.get("zenodo_filename", "")).strip()
            != row.zenodo_filename
            or item.get("width") != row.width
            or item.get("height") != row.height
            or item.get("channels") != row.channels
            or str(item.get("dtype", "")).strip() != row.dtype
            or str(item.get("photometric", "")).strip() != row.photometric
            or item.get("is_tiled") is not row.is_tiled
            or item.get("sensitive_tag_count") != 0
            or item.get("source_identifier_hit_count") != 0
        ):
            raise DepositError(
                "TIFF validation report file metadata does not match "
                f"the public manifest for {row.zenodo_filename}"
            )
    if seen != set(expected):
        raise DepositError(
            "TIFF validation report files do not match the public manifest"
        )


def validate_generated_artifacts(
    paths: dict[str, Path], public_rows: list[PublicManifestRow]
) -> None:
    validate_samples(paths["samples.csv"], public_rows)
    validate_checksum_file(
        paths["SHA256SUMS"], public_rows, algorithm="sha256"
    )
    validate_checksum_file(paths["MD5SUMS"], public_rows, algorithm="md5")
    validate_public_report(paths["tiff_validation_report.json"], public_rows)


def parse_extra_file(value: str) -> tuple[Path, str]:
    raw_path, separator, raw_name = value.rpartition("=")
    if separator:
        return Path(raw_path), safe_remote_name(raw_name)
    path = Path(value)
    return path, safe_remote_name(path.name)


def collect_uploads(
    public_manifest: Path,
    private_mapping: Path,
    public_dir: Path,
    extra_files: list[str],
) -> list[UploadFile]:
    public_paths = required_public_artifacts(public_dir, public_manifest)
    public_rows = load_public_manifest(
        public_paths["tumorquantai_lymphoma_manifest.csv"]
    )
    validate_generated_artifacts(public_paths, public_rows)
    uploads = slide_uploads_from_rows(public_rows, private_mapping)
    resolved_public_dir = public_dir.expanduser().resolve()
    if private_mapping.expanduser().resolve().is_relative_to(resolved_public_dir):
        raise DepositError(
            "Private source mapping must be outside the public artifact directory"
        )

    uploads.extend(
        make_small_upload(path, path.name, "public-artifact")
        for path in sorted(public_paths.values())
    )
    for value in extra_files:
        path, remote_name = parse_extra_file(value)
        uploads.append(make_small_upload(path, remote_name, "extra-public-file"))

    by_name: dict[str, UploadFile] = {}
    for upload in uploads:
        if upload.remote_name in by_name:
            raise DepositError(f"Duplicate upload file name: {upload.remote_name}")
        by_name[upload.remote_name] = upload
    if len(uploads) > ZENODO_MAX_FILES:
        raise DepositError(
            f"Deposit contains {len(uploads)} files; Zenodo accepts at most "
            f"{ZENODO_MAX_FILES}"
        )
    oversized = [
        item.remote_name for item in uploads if item.size_bytes > ZENODO_MAX_FILE_BYTES
    ]
    if oversized:
        raise DepositError(
            f"{len(oversized)} file(s) exceed Zenodo's 50 GB per-file limit"
        )
    return sorted(uploads, key=lambda item: item.remote_name.casefold())

def release_fingerprint(
    metadata: dict[str, object], uploads: list[UploadFile]
) -> str:
    """Bind a human publication authorization to exact metadata and file hashes."""
    payload = {
        "metadata": metadata,
        "files": [
            {
                "name": item.remote_name,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256,
                "kind": item.kind,
            }
            for item in sorted(uploads, key=lambda value: value.remote_name.casefold())
        ],
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def retry_delay(response: requests.Response | None, attempt: int) -> float:
    if response is not None:
        try:
            return min(float(response.headers.get("Retry-After", "")), 60.0)
        except (TypeError, ValueError):
            pass
    return min(2.0 ** attempt, 30.0)


def validated_api_url(value: str) -> str:
    url = value.strip().rstrip("/")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise DepositError(
            "Zenodo API URL must be an HTTPS URL without credentials, query, or fragment"
        )
    return url


class ZenodoClient:
    def __init__(
        self,
        token: str,
        api_url: str = DEFAULT_API_URL,
        *,
        retries: int = 5,
        session: requests.Session | None = None,
    ) -> None:
        if retries < 0:
            raise DepositError("--retries must be non-negative")
        self._token = token
        self.api_url = validated_api_url(api_url)
        self.retries = retries
        self.session = session or requests.Session()

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}

    def request(
        self,
        method: str,
        url: str,
        *,
        expected: Iterable[int],
        json_body: dict[str, object] | None = None,
        data: BinaryIO | None = None,
        timeout: tuple[float, float] = (15.0, 120.0),
        retries: int | None = None,
    ) -> requests.Response:
        parsed_api = urlparse(self.api_url)
        parsed_target = urlparse(url)
        if (
            parsed_target.scheme != parsed_api.scheme
            or parsed_target.netloc != parsed_api.netloc
        ):
            raise DepositError("Refusing to send Zenodo credentials to another origin")
        attempts = self.retries if retries is None else retries
        expected_set = set(expected)
        last_error: Exception | None = None
        for attempt in range(attempts + 1):
            response: requests.Response | None = None
            try:
                if data is not None and attempt:
                    data.seek(0)
                response = self.session.request(
                    method,
                    url,
                    headers=self.headers,
                    json=json_body,
                    data=data,
                    timeout=timeout,
                    allow_redirects=False,
                )
                if response.status_code in expected_set:
                    return response
                if response.status_code not in RETRYABLE_STATUSES:
                    raise DepositError(
                        f"Zenodo API request failed: {method} {urlparse(url).path} "
                        f"returned HTTP {response.status_code}"
                    )
            except requests.RequestException as exc:
                last_error = exc
            if response is not None:
                response.close()
            if attempt == attempts:
                break
            time.sleep(retry_delay(response, attempt))
        if last_error is not None:
            raise DepositError(
                f"Zenodo API request failed after {attempts + 1} attempts: "
                f"{method} {urlparse(url).path}"
            ) from last_error
        raise DepositError(
            f"Zenodo API request failed after {attempts + 1} attempts: "
            f"{method} {urlparse(url).path}"
        )

    @staticmethod
    def json_response(response: requests.Response, description: str) -> dict[str, object]:
        try:
            payload = response.json()
        except (ValueError, requests.JSONDecodeError) as exc:
            raise DepositError(f"{description} returned invalid JSON") from exc
        finally:
            response.close()
        if not isinstance(payload, dict):
            raise DepositError(f"{description} returned an invalid JSON object")
        return payload

    def create_draft(self) -> dict[str, object]:
        response = self.request(
            "POST",
            f"{self.api_url}/deposit/depositions",
            expected=(201,),
            json_body={},
        )
        return self.json_response(response, "Create-deposition request")

    def get_draft(self, deposition_id: str) -> dict[str, object]:
        response = self.request(
            "GET",
            f"{self.api_url}/deposit/depositions/{deposition_id}",
            expected=(200,),
        )
        return self.json_response(response, "Get-deposition request")

    def update_metadata(
        self, deposition_id: str, metadata: dict[str, object]
    ) -> dict[str, object]:
        response = self.request(
            "PUT",
            f"{self.api_url}/deposit/depositions/{deposition_id}",
            expected=(200,),
            json_body={"metadata": metadata},
        )
        return self.json_response(response, "Metadata update")

    def delete_file(self, url: str) -> None:
        response = self.request("DELETE", url, expected=(200, 204))
        response.close()

    def upload_file(self, bucket_url: str, upload: UploadFile) -> dict[str, object]:
        url = f"{bucket_url.rstrip('/')}/{quote(upload.remote_name, safe='')}"
        with upload.local_path.open("rb") as handle:
            response = self.request(
                "PUT",
                url,
                expected=(200, 201),
                data=handle,
                timeout=(15.0, 6 * 60 * 60.0),
            )
        return self.json_response(response, f"Upload of {upload.remote_name}")

    def publish(self, deposition_id: str) -> dict[str, object]:
        response = self.request(
            "POST",
            f"{self.api_url}/deposit/depositions/{deposition_id}/actions/publish",
            expected=(200, 201, 202),
        )
        return self.json_response(response, "Publish request")


def parse_remote_files(payload: dict[str, object]) -> dict[str, RemoteFile]:
    raw_files = payload.get("files")
    if not isinstance(raw_files, list):
        return {}
    files: dict[str, RemoteFile] = {}
    for item in raw_files:
        if not isinstance(item, dict):
            continue
        name = str(item.get("filename") or item.get("key") or "").strip()
        if not name:
            continue
        raw_size = item.get("filesize") if item.get("filesize") is not None else item.get("size")
        try:
            size = int(raw_size) if raw_size is not None else None
        except (TypeError, ValueError):
            size = None
        checksum = str(item.get("checksum") or "").strip().casefold()
        if checksum.startswith("md5:"):
            checksum = checksum[4:]
        md5 = checksum if HEX_MD5_RE.fullmatch(checksum) else None
        links = item.get("links") if isinstance(item.get("links"), dict) else {}
        delete_url = str(links.get("self") or "").strip() or None
        if name in files:
            raise DepositError(f"Draft contains duplicate file name: {name}")
        files[name] = RemoteFile(name, size, md5, delete_url)
    return files


def file_matches(remote: RemoteFile, upload: UploadFile) -> bool:
    return remote.size_bytes == upload.size_bytes and remote.md5 == upload.md5


def verify_local(upload: UploadFile) -> None:
    if upload.local_path.is_symlink() or not upload.local_path.is_file():
        raise DepositError(f"Upload source is not a regular file: {upload.remote_name}")
    size, sha256, md5 = digest_file(upload.local_path)
    if (size, sha256, md5) != (upload.size_bytes, upload.sha256, upload.md5):
        raise DepositError(f"Local file changed since preparation: {upload.remote_name}")


def bucket_from_payload(payload: dict[str, object]) -> str:
    links = payload.get("links") if isinstance(payload.get("links"), dict) else {}
    bucket = str(links.get("bucket") or "").strip()
    if not bucket:
        raise DepositError("Zenodo draft response did not include an upload bucket")
    return bucket


def deposition_id_from_payload(payload: dict[str, object]) -> str:
    value = str(payload.get("id") or "").strip()
    if not value.isdigit():
        raise DepositError("Zenodo draft response did not include a numeric deposition ID")
    return value


def validate_upload_response(payload: dict[str, object], upload: UploadFile) -> None:
    raw_size = payload.get("size") if payload.get("size") is not None else payload.get("filesize")
    try:
        size = int(raw_size) if raw_size is not None else None
    except (TypeError, ValueError):
        size = None
    checksum = str(payload.get("checksum") or "").strip().casefold()
    if checksum.startswith("md5:"):
        checksum = checksum[4:]
    if size is not None and size != upload.size_bytes:
        raise DepositError(f"Zenodo reported a size mismatch for {upload.remote_name}")
    if checksum and checksum != upload.md5:
        raise DepositError(f"Zenodo reported an MD5 mismatch for {upload.remote_name}")


def validate_authorization(
    path: Path,
    metadata: dict[str, object],
    expected_fingerprint: str,
) -> dict[str, object]:
    payload = load_json(path, "Publication authorization")
    missing = [key for key in PUBLISH_CONFIRMATIONS if payload.get(key) is not True]
    if missing:
        raise DepositError(
            "Publication authorization lacks true confirmations: " + ", ".join(missing)
        )
    authorized_by = str(payload.get("authorized_by", "")).strip()
    authorized_at = str(payload.get("authorized_at", "")).strip()
    if not authorized_by or not authorized_at:
        raise DepositError("Publication authorization requires authorized_by and authorized_at")
    try:
        authorization_time = datetime.fromisoformat(authorized_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DepositError("Publication authorization authorized_at is not ISO-8601") from exc
    if authorization_time.tzinfo is None:
        raise DepositError("Publication authorization authorized_at requires a timezone")
    metadata_license = str(metadata.get("license", "")).strip()
    if str(payload.get("license", "")).strip() != metadata_license:
        raise DepositError("Authorized license does not exactly match Zenodo metadata")
    if (
        str(payload.get("release_fingerprint_sha256", "")).strip().casefold()
        != expected_fingerprint
    ):
        raise DepositError(
            "Publication authorization is not bound to this exact metadata/file set"
        )
    return payload


def reject_unresolved_publication_placeholders(
    metadata: dict[str, object], uploads: list[UploadFile]
) -> None:
    unresolved: list[str] = []
    metadata_text = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    if UNRESOLVED_PLACEHOLDER_RE.search(metadata_text):
        unresolved.append("Zenodo metadata")
    for upload in uploads:
        if upload.kind != "extra-public-file":
            continue
        if upload.local_path.suffix.casefold() not in {".md", ".txt", ".json", ".csv"}:
            continue
        if upload.size_bytes > 10 * 1024 * 1024:
            raise DepositError(
                "Text release file is too large for placeholder review: "
                f"{upload.remote_name}"
            )
        try:
            text = upload.local_path.read_text(encoding="utf-8")
        except UnicodeError as exc:
            raise DepositError(
                f"Text release file is not valid UTF-8: {upload.remote_name}"
            ) from exc
        if UNRESOLVED_PLACEHOLDER_RE.search(text):
            unresolved.append(upload.remote_name)
    if unresolved:
        raise DepositError(
            "Publication contains unresolved release placeholders in: "
            + ", ".join(unresolved)
        )


def validate_draft_metadata(
    draft: dict[str, object], expected: dict[str, object]
) -> None:
    remote = draft.get("metadata")
    if not isinstance(remote, dict):
        raise DepositError(
            "Final Zenodo draft did not return metadata for pre-publication verification"
        )
    mismatched = [
        field
        for field in AUTHORIZED_METADATA_FIELDS
        if remote.get(field) != expected.get(field)
    ]
    if mismatched:
        raise DepositError(
            "Final Zenodo draft metadata differs from the authorized metadata: "
            + ", ".join(mismatched)
        )


def load_state(path: Path) -> dict[str, object] | None:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink():
        raise DepositError(f"Refusing a symlink deposit state: {candidate}")
    path = candidate.resolve()
    if not candidate.exists():
        return None
    return load_json(path, "Deposit state")


def deposit(
    *,
    public_manifest: Path,
    private_mapping: Path,
    public_dir: Path,
    metadata_file: Path,
    state_file: Path,
    extra_files: list[str],
    token_env: str = DEFAULT_TOKEN_ENV,
    token_file: Path | None = None,
    api_url: str = DEFAULT_API_URL,
    retries: int = 5,
    replace_mismatched: bool = False,
    publish: bool = False,
    authorization: Path | None = None,
    plan: bool = False,
    session: requests.Session | None = None,
) -> dict[str, object]:
    api_url = validated_api_url(api_url)
    metadata = metadata_from_file(metadata_file)
    uploads = collect_uploads(public_manifest, private_mapping, public_dir, extra_files)
    fingerprint = release_fingerprint(metadata, uploads)
    plan_result = {
        "draft_only": not publish,
        "file_count": len(uploads),
        "total_size_bytes": sum(item.size_bytes for item in uploads),
        "release_fingerprint_sha256": fingerprint,
        "required_publish_confirmations": list(PUBLISH_CONFIRMATIONS),
        "required_authorization_fields": [
            "authorized_by",
            "authorized_at",
            "license",
            "release_fingerprint_sha256",
        ],
        "files": [
            {"name": item.remote_name, "size_bytes": item.size_bytes, "kind": item.kind}
            for item in uploads
        ],
    }
    if plan:
        return {"plan": True, **plan_result}
    if publish and authorization is None:
        raise DepositError("--publish requires --authorization")
    if publish:
        reject_unresolved_publication_placeholders(metadata, uploads)
        validate_authorization(authorization, metadata, fingerprint)

    token = resolve_token(token_env, token_file)
    client = ZenodoClient(token, api_url, retries=retries, session=session)
    state_path = state_file.expanduser().absolute()
    state = load_state(state_path)
    if state is not None:
        if str(state.get("api_url", "")).rstrip("/") != api_url.rstrip("/"):
            raise DepositError("Deposit state belongs to a different Zenodo API URL")
        if state.get("status") == "published":
            raise DepositError("Deposit state is already marked published")
        deposition_id = str(state.get("deposition_id", "")).strip()
        if not deposition_id.isdigit():
            raise DepositError("Deposit state has no valid deposition_id")
        draft = client.get_draft(deposition_id)
    else:
        draft = client.create_draft()
        deposition_id = deposition_id_from_payload(draft)
        state = {
            "schema_version": 1,
            "api_url": api_url.rstrip("/"),
            "deposition_id": deposition_id,
            "status": "draft",
            "uploaded": {},
        }
        atomic_json(state_path, state)

    bucket_url = bucket_from_payload(draft)
    client.update_metadata(deposition_id, metadata)
    remote_files = parse_remote_files(client.get_draft(deposition_id))
    uploaded_state = state.get("uploaded")
    if not isinstance(uploaded_state, dict):
        uploaded_state = {}
        state["uploaded"] = uploaded_state

    for upload in uploads:
        existing = remote_files.get(upload.remote_name)
        if existing is not None and file_matches(existing, upload):
            status = "verified-existing"
        else:
            if existing is not None:
                if not replace_mismatched:
                    raise DepositError(
                        f"Draft file differs from local manifest: {upload.remote_name}; "
                        "use --replace-mismatched after review"
                    )
                if not existing.delete_url:
                    raise DepositError(
                        f"Zenodo did not provide a deletion URL for {upload.remote_name}"
                    )
                client.delete_file(existing.delete_url)
            verify_local(upload)
            response_payload = client.upload_file(bucket_url, upload)
            validate_upload_response(response_payload, upload)
            status = "uploaded"
        uploaded_state[upload.remote_name] = {
            "size_bytes": upload.size_bytes,
            "md5": upload.md5,
            "status": status,
        }
        atomic_json(state_path, state)
        print(f"{status}: {upload.remote_name}", file=sys.stderr)

    verified_draft = client.get_draft(deposition_id)
    verified_remote = parse_remote_files(verified_draft)
    if publish:
        validate_draft_metadata(verified_draft, metadata)
    for upload in uploads:
        remote = verified_remote.get(upload.remote_name)
        if remote is None or not file_matches(remote, upload):
            raise DepositError(f"Final draft verification failed for {upload.remote_name}")
    unexpected = sorted(set(verified_remote) - {item.remote_name for item in uploads})
    if publish and unexpected:
        raise DepositError(
            f"Draft contains {len(unexpected)} unreviewed extra file(s); add them "
            "with --extra-file or remove them before publication"
        )

    result: dict[str, object] = {
        "plan": False,
        "deposition_id": deposition_id,
        "status": "draft",
        **plan_result,
    }
    if publish:
        published = client.publish(deposition_id)
        state["status"] = "published"
        state["record_id"] = published.get("record_id") or published.get("id")
        atomic_json(state_path, state)
        result["status"] = "published"
        result["record_id"] = state["record_id"]
    else:
        state["status"] = "draft"
        atomic_json(state_path, state)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-manifest", required=True, type=Path)
    parser.add_argument("--private-mapping", required=True, type=Path)
    parser.add_argument("--public-dir", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument(
        "--extra-file",
        action="append",
        default=[],
        metavar="PATH[=ZENODO_NAME]",
        help="Additional explicitly public small file (repeatable)",
    )
    parser.add_argument("--token-env", default=DEFAULT_TOKEN_ENV)
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--replace-mismatched", action="store_true")
    parser.add_argument("--plan", action="store_true", help="Validate and print a local-only plan")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--authorization", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = deposit(
            public_manifest=args.public_manifest,
            private_mapping=args.private_mapping,
            public_dir=args.public_dir,
            metadata_file=args.metadata,
            state_file=args.state,
            extra_files=args.extra_file,
            token_env=args.token_env,
            token_file=args.token_file,
            api_url=args.api_url,
            retries=args.retries,
            replace_mismatched=args.replace_mismatched,
            publish=args.publish,
            authorization=args.authorization,
            plan=args.plan,
        )
    except (DepositError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
