#!/usr/bin/env python3
"""Download and verify the public TumorQuantAI lymphoma WSI dataset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests


DEFAULT_API_URL = "https://zenodo.org/api"
DEFAULT_MANIFEST_NAME = "tumorquantai_lymphoma_manifest.csv"
LOCAL_SAMPLES_NAME = "samples.csv"
LOCAL_CHECKSUMS_NAME = "checksums.sha256"
ALIAS_RE = re.compile(r"^TumorQuantAI_LymphomaWSI_[0-9]{3}$")
HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HEX_MD5_RE = re.compile(r"^[0-9a-f]{32}$")
REQUIRED_COLUMNS = {
    "alias",
    "level",
    "source_mpp",
    "zenodo_filename",
    "dataset_path",
    "size_bytes",
    "sha256",
    "md5",
}
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class DownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class ManifestRow:
    alias: str
    level: int
    source_mpp: float
    zenodo_filename: str
    dataset_path: str
    size_bytes: int
    sha256: str
    md5: str


@dataclass(frozen=True)
class RemoteFile:
    name: str
    size_bytes: int | None
    md5: str | None
    url: str


def record_id(value: str) -> str:
    candidate = value.strip().rstrip("/")
    if candidate.isdigit():
        return candidate
    match = re.search(r"(?:zenodo[.]|/records/|/record/)([0-9]+)(?:$|[/?#])", candidate)
    if not match:
        raise DownloadError(
            "--record must be a numeric Zenodo record ID, DOI, or Zenodo record URL"
        )
    return match.group(1)


def parse_md5(value: object) -> str | None:
    text = str(value or "").strip().casefold()
    if text.startswith("md5:"):
        text = text[4:]
    return text if HEX_MD5_RE.fullmatch(text) else None


def retry_delay(response: requests.Response | None, attempt: int) -> float:
    if response is not None:
        raw = response.headers.get("Retry-After", "")
        try:
            return min(float(raw), 60.0)
        except (TypeError, ValueError):
            pass
    return min(2.0 ** attempt, 30.0)


def request(
    session: requests.Session,
    method: str,
    url: str,
    *,
    expected: Iterable[int] = (200,),
    retries: int = 5,
    timeout: tuple[float, float] = (15.0, 120.0),
    stream: bool = False,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    expected_set = set(expected)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        response: requests.Response | None = None
        try:
            response = session.request(
                method,
                url,
                timeout=timeout,
                stream=stream,
                headers=headers,
                allow_redirects=True,
            )
            if response.status_code in expected_set:
                return response
            if response.status_code not in RETRYABLE_STATUSES:
                raise DownloadError(
                    f"Zenodo request failed: {method} {urlparse(url).path} "
                    f"returned HTTP {response.status_code}"
                )
        except requests.RequestException as exc:
            last_error = exc
        if response is not None:
            response.close()
        if attempt == retries:
            break
        time.sleep(retry_delay(response, attempt))
    if last_error is not None:
        raise DownloadError(
            f"Zenodo request failed after {retries + 1} attempts: "
            f"{method} {urlparse(url).path}"
        ) from last_error
    raise DownloadError(
        f"Zenodo request failed after {retries + 1} attempts: "
        f"{method} {urlparse(url).path}"
    )


def record_files(
    session: requests.Session,
    api_url: str,
    identifier: str,
    retries: int,
) -> dict[str, RemoteFile]:
    url = f"{api_url.rstrip('/')}/records/{record_id(identifier)}"
    response = request(session, "GET", url, retries=retries)
    try:
        payload = response.json()
    except (ValueError, requests.JSONDecodeError) as exc:
        raise DownloadError("Zenodo record response was not valid JSON") from exc
    finally:
        response.close()
    files = payload.get("files")
    if not isinstance(files, list):
        raise DownloadError("Zenodo record response has no files list")
    result: dict[str, RemoteFile] = {}
    for item in files:
        if not isinstance(item, dict):
            continue
        name = str(item.get("key") or item.get("filename") or "").strip()
        links = item.get("links") if isinstance(item.get("links"), dict) else {}
        url_value = str(links.get("self") or links.get("content") or "").strip()
        if not name or not url_value:
            continue
        if name in result:
            raise DownloadError(f"Duplicate file name in Zenodo record: {name}")
        raw_size = item.get("size") if item.get("size") is not None else item.get("filesize")
        try:
            size = int(raw_size) if raw_size is not None else None
        except (TypeError, ValueError):
            size = None
        result[name] = RemoteFile(
            name=name,
            size_bytes=size,
            md5=parse_md5(item.get("checksum")),
            url=url_value,
        )
    return result


def parse_manifest_text(text: str, source: str) -> list[ManifestRow]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        raise DownloadError(
            f"Dataset manifest {source} is missing columns: {', '.join(sorted(missing))}"
        )
    rows: list[ManifestRow] = []
    seen_files: set[str] = set()
    seen_paths: set[str] = set()
    levels_by_alias: dict[str, set[int]] = {}
    source_mpp_values: set[float] = set()
    for line_number, raw in enumerate(reader, start=2):
        alias = str(raw.get("alias", "")).strip()
        if not ALIAS_RE.fullmatch(alias):
            raise DownloadError(f"Invalid public alias at {source}:{line_number}")
        try:
            level = int(str(raw.get("level", "")).strip())
            source_mpp = float(str(raw.get("source_mpp", "")).strip())
            size = int(str(raw.get("size_bytes", "")).strip())
        except ValueError as exc:
            raise DownloadError(f"Invalid numeric value at {source}:{line_number}") from exc
        if (
            level not in {0, 2}
            or not math.isfinite(source_mpp)
            or source_mpp <= 0
            or size <= 0
        ):
            raise DownloadError(
                f"Invalid level, source_mpp, or size at {source}:{line_number}"
            )
        filename = str(raw.get("zenodo_filename", "")).strip()
        dataset_path = str(raw.get("dataset_path", "")).strip()
        expected_filename = f"{alias}_L{level}_rgb.tif"
        expected_path = f"slides/{alias}/1_L{level}_rgb.tif"
        if filename != expected_filename or dataset_path != expected_path:
            raise DownloadError(
                f"Unsafe or inconsistent file mapping at {source}:{line_number}"
            )
        sha256 = str(raw.get("sha256", "")).strip().casefold()
        md5 = str(raw.get("md5", "")).strip().casefold()
        if not HEX_SHA256_RE.fullmatch(sha256) or not HEX_MD5_RE.fullmatch(md5):
            raise DownloadError(f"Invalid checksum at {source}:{line_number}")
        if filename in seen_files or dataset_path in seen_paths:
            raise DownloadError(f"Duplicate file/path at {source}:{line_number}")
        seen_files.add(filename)
        seen_paths.add(dataset_path)
        levels_by_alias.setdefault(alias, set()).add(level)
        source_mpp_values.add(source_mpp)
        rows.append(
            ManifestRow(alias, level, source_mpp, filename, dataset_path, size, sha256, md5)
        )
    if not rows:
        raise DownloadError(f"Dataset manifest {source} is empty")
    incomplete = [alias for alias, levels in levels_by_alias.items() if levels != {0, 2}]
    if incomplete:
        raise DownloadError(
            f"Manifest contains {len(incomplete)} alias(es) without a complete L0/L2 pair"
        )
    if len(source_mpp_values) != 1:
        raise DownloadError("Manifest must contain exactly one consistent source_mpp")
    return rows


def load_local_manifest(path: Path) -> list[ManifestRow]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise DownloadError(f"Dataset manifest does not exist: {path}")
    return parse_manifest_text(path.read_text(encoding="utf-8-sig"), str(path))


def load_remote_manifest(
    session: requests.Session,
    remote_files: dict[str, RemoteFile],
    name: str,
    retries: int,
) -> tuple[list[ManifestRow], str]:
    remote = remote_files.get(name)
    if remote is None:
        raise DownloadError(f"Zenodo record does not contain manifest {name!r}")
    if remote.size_bytes is not None and remote.size_bytes > 10 * 1024 * 1024:
        raise DownloadError("Refusing an unexpectedly large dataset manifest")
    response = request(session, "GET", remote.url, retries=retries)
    try:
        payload = response.content
    finally:
        response.close()
    if len(payload) > 10 * 1024 * 1024:
        raise DownloadError("Refusing an unexpectedly large dataset manifest")
    if remote.size_bytes is not None and len(payload) != remote.size_bytes:
        raise DownloadError("Remote dataset manifest size does not match Zenodo metadata")
    if remote.md5 is not None:
        payload_md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
        if payload_md5 != remote.md5:
            raise DownloadError("Remote dataset manifest MD5 does not match Zenodo metadata")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DownloadError("Dataset manifest is not UTF-8") from exc
    return parse_manifest_text(text, name), text


def render_samples(rows: list[ManifestRow]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=("sample_id", "slide_path"),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(
        {
            "sample_id": row.alias,
            "slide_path": row.dataset_path.removeprefix("slides/"),
        }
        for row in rows
        if row.level == 0
    )
    return buffer.getvalue()


def render_local_checksums(rows: list[ManifestRow]) -> str:
    return "".join(f"{row.sha256}  {row.dataset_path}\n" for row in rows)


def preflight_local_artifact(
    root: Path,
    name: str,
    content: str,
    *,
    overwrite: bool,
) -> None:
    target = safe_target(root, name)
    if not target.exists():
        return
    if target.is_symlink() or not target.is_file():
        raise DownloadError(f"Refusing unsafe local metadata target: {target}")
    if target.read_bytes() != content.encode("utf-8") and not overwrite:
        raise DownloadError(
            f"Existing local metadata differs from the record: {target}; "
            "use --overwrite"
        )


def write_local_artifact(
    root: Path,
    name: str,
    content: str,
    *,
    overwrite: bool,
) -> str:
    preflight_local_artifact(root, name, content, overwrite=overwrite)
    target = safe_target(root, name)
    encoded = content.encode("utf-8")
    if target.exists():
        if target.is_symlink() or not target.is_file():
            raise DownloadError(f"Refusing unsafe local metadata target: {target}")
        if target.read_bytes() == encoded:
            return "verified-existing"
        if not overwrite:
            raise DownloadError(
                f"Existing local metadata differs from the record: {target}; "
                "use --overwrite"
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return "written"


def validate_record(rows: list[ManifestRow], remote_files: dict[str, RemoteFile]) -> None:
    for row in rows:
        remote = remote_files.get(row.zenodo_filename)
        if remote is None:
            raise DownloadError(f"Zenodo record is missing {row.zenodo_filename}")
        if remote.size_bytes is not None and remote.size_bytes != row.size_bytes:
            raise DownloadError(f"Remote size mismatch for {row.zenodo_filename}")
        if remote.md5 is not None and remote.md5 != row.md5:
            raise DownloadError(f"Remote MD5 mismatch for {row.zenodo_filename}")


def digest_file(path: Path) -> tuple[int, str, str]:
    size = 0
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            size += len(chunk)
            sha256.update(chunk)
            md5.update(chunk)
    return size, sha256.hexdigest(), md5.hexdigest()


def verify_file(path: Path, row: ManifestRow) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    if path.stat().st_size != row.size_bytes:
        return False
    size, sha256, md5 = digest_file(path)
    return size == row.size_bytes and sha256 == row.sha256 and md5 == row.md5


def safe_target(output_dir: Path, dataset_path: str) -> Path:
    root = output_dir.expanduser().resolve()
    target = root / dataset_path
    cursor = root
    for part in Path(dataset_path).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise DownloadError(f"Refusing symlink in output path: {dataset_path}")
    resolved = target.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise DownloadError(f"Manifest path escapes output directory: {dataset_path}") from exc
    return target


def download_one(
    session: requests.Session,
    remote: RemoteFile,
    row: ManifestRow,
    target: Path,
    *,
    retries: int,
    overwrite: bool,
) -> str:
    if target.exists():
        if verify_file(target, row):
            return "verified-existing"
        if not overwrite:
            raise DownloadError(
                f"Existing target does not match the manifest: {target}; use --overwrite"
            )
        if target.is_symlink() or not target.is_file():
            raise DownloadError(f"Refusing to overwrite unsafe target: {target}")
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.part")
    if partial.exists() and (partial.is_symlink() or not partial.is_file()):
        raise DownloadError(f"Refusing unsafe partial download path: {partial}")
    if partial.exists() and partial.stat().st_size > row.size_bytes:
        partial.unlink()
    if partial.exists() and partial.stat().st_size == row.size_bytes:
        if verify_file(partial, row):
            os.replace(partial, target)
            return "verified-partial"
        if not overwrite:
            raise DownloadError(
                f"Complete partial file has invalid checksums: {partial}; use --overwrite"
            )
        partial.unlink()

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        offset = partial.stat().st_size if partial.exists() else 0
        if offset == row.size_bytes:
            break
        headers = {"Range": f"bytes={offset}-"} if offset else None
        response: requests.Response | None = None
        try:
            response = request(
                session,
                "GET",
                remote.url,
                expected=(200, 206),
                retries=0,
                timeout=(15.0, 300.0),
                stream=True,
                headers=headers,
            )
            mode = "ab"
            if response.status_code == 200:
                mode = "wb"
            elif offset:
                content_range = response.headers.get("Content-Range", "")
                if not content_range.startswith(f"bytes {offset}-"):
                    raise DownloadError(
                        f"Server returned an invalid byte range for {row.zenodo_filename}"
                    )
            written = offset if mode == "ab" else 0
            with partial.open(mode) as handle:
                for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                    if chunk:
                        if written + len(chunk) > row.size_bytes:
                            raise DownloadError(
                                f"Downloaded too many bytes for {row.zenodo_filename}"
                            )
                        handle.write(chunk)
                        written += len(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if partial.stat().st_size == row.size_bytes:
                break
            if partial.stat().st_size > row.size_bytes:
                raise DownloadError(f"Downloaded too many bytes for {row.zenodo_filename}")
            last_error = DownloadError(
                f"Incomplete transfer for {row.zenodo_filename}"
            )
        except (requests.RequestException, OSError, DownloadError) as exc:
            last_error = exc
        finally:
            if response is not None:
                response.close()
        if attempt < retries:
            time.sleep(min(2.0 ** attempt, 30.0))
    if not partial.exists() or partial.stat().st_size != row.size_bytes:
        raise DownloadError(
            f"Could not complete {row.zenodo_filename} after {retries + 1} attempts"
        ) from last_error
    if not verify_file(partial, row):
        raise DownloadError(f"Checksum verification failed for {row.zenodo_filename}")
    os.replace(partial, target)
    return "downloaded"


def download_dataset(
    *,
    manifest: Path | None,
    record: str | None,
    output_dir: Path,
    api_url: str = DEFAULT_API_URL,
    manifest_name: str = DEFAULT_MANIFEST_NAME,
    dry_run: bool = False,
    overwrite: bool = False,
    retries: int = 5,
    session: requests.Session | None = None,
) -> dict[str, object]:
    if retries < 0:
        raise DownloadError("--retries must be non-negative")
    http = session or requests.Session()
    remote_files: dict[str, RemoteFile] | None = None
    if record:
        remote_files = record_files(http, api_url, record, retries)
    if manifest is not None:
        manifest_path = manifest.expanduser().resolve()
        with manifest_path.open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            manifest_text = handle.read()
        rows = parse_manifest_text(manifest_text, str(manifest_path))
    else:
        rows, manifest_text = load_remote_manifest(
            http,
            remote_files or {},
            manifest_name,
            retries,
        )
    if remote_files is not None:
        validate_record(rows, remote_files)
    if not dry_run and remote_files is None:
        raise DownloadError("--record is required unless --dry-run is used")

    root = output_dir.expanduser().resolve()
    plans = [
        {
            "alias": row.alias,
            "level": row.level,
            "source": row.zenodo_filename,
            "target": str(safe_target(root, row.dataset_path)),
            "size_bytes": row.size_bytes,
        }
        for row in rows
    ]
    if dry_run:
        return {
            "dry_run": True,
            "file_count": len(rows),
            "total_size_bytes": sum(row.size_bytes for row in rows),
            "files": plans,
        }

    local_contents = {
        manifest_name: manifest_text,
        LOCAL_SAMPLES_NAME: render_samples(rows),
        LOCAL_CHECKSUMS_NAME: render_local_checksums(rows),
    }
    for name, content in local_contents.items():
        preflight_local_artifact(root, name, content, overwrite=overwrite)

    statuses: dict[str, int] = {}
    assert remote_files is not None
    for row in rows:
        status = download_one(
            http,
            remote_files[row.zenodo_filename],
            row,
            safe_target(root, row.dataset_path),
            retries=retries,
            overwrite=overwrite,
        )
        statuses[status] = statuses.get(status, 0) + 1
        print(f"{status}: {row.zenodo_filename}", file=sys.stderr)
    local_artifacts = {
        manifest_name: write_local_artifact(
            root, manifest_name, local_contents[manifest_name], overwrite=overwrite
        ),
        LOCAL_SAMPLES_NAME: write_local_artifact(
            root,
            LOCAL_SAMPLES_NAME,
            local_contents[LOCAL_SAMPLES_NAME],
            overwrite=overwrite
        ),
        LOCAL_CHECKSUMS_NAME: write_local_artifact(
            root,
            LOCAL_CHECKSUMS_NAME,
            local_contents[LOCAL_CHECKSUMS_NAME],
            overwrite=overwrite,
        ),
    }
    return {
        "dry_run": False,
        "file_count": len(rows),
        "total_size_bytes": sum(row.size_bytes for row in rows),
        "statuses": statuses,
        "local_artifacts": local_artifacts,
        "output_dir": str(root),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, help="Local public manifest CSV")
    parser.add_argument("--record", help="Zenodo record ID, DOI, or record URL")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--manifest-name", default=DEFAULT_MANIFEST_NAME)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--retries", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.manifest is None and args.record is None:
        parser.error("provide --manifest for an offline dry-run or --record")
    try:
        result = download_dataset(
            manifest=args.manifest,
            record=args.record,
            output_dir=args.output_dir,
            api_url=args.api_url,
            manifest_name=args.manifest_name,
            dry_run=args.dry_run,
            overwrite=args.overwrite,
            retries=args.retries,
        )
    except (DownloadError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
