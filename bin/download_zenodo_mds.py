#!/usr/bin/env python3
"""Download and verify the raw-MDS TumorQuantAI lymphoma tutorial dataset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

import requests

import download_zenodo_dataset as base
from mds_manifest import (
    MdsManifestError,
    MdsManifestRow,
    REQUIRED_COLUMNS,
    load_manifest,
    parse_manifest_text as parse_strict_manifest,
)


DEFAULT_MANIFEST_NAME = "tumorquantai_lymphoma_mds_manifest.csv"
RAW_SAMPLES_NAME = "raw_samples.csv"
CHECKSUMS_NAME = "checksums.sha256"
ALLOWED_API_ORIGINS = {"zenodo.org", "sandbox.zenodo.org"}


def validated_api_url(value: str) -> str:
    url = value.strip().rstrip("/")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc not in ALLOWED_API_ORIGINS
        or parsed.path.rstrip("/") != "/api"
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise base.DownloadError(
            "--api-url must be https://zenodo.org/api or "
            "https://sandbox.zenodo.org/api"
        )
    return url


def require_api_origin(url: str, api_url: str, description: str) -> None:
    target = urlparse(url)
    api = urlparse(api_url)
    if (
        target.scheme != "https"
        or target.netloc != api.netloc
        or target.username is not None
        or target.password is not None
    ):
        raise base.DownloadError(
            f"Refusing {description} URL outside the trusted Zenodo origin"
        )



@contextmanager
def private_umask():
    previous = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(previous)


def parse_manifest_text(text: str, source: str) -> list[MdsManifestRow]:
    """Parse the shared schema while exposing DownloadError to CLI callers."""
    try:
        return parse_strict_manifest(text, source)
    except MdsManifestError as exc:
        raise base.DownloadError(str(exc)) from exc


def select_rows(
    rows: list[MdsManifestRow], requested: list[str]
) -> list[MdsManifestRow]:
    if not requested:
        return rows
    if len(set(requested)) != len(requested):
        raise base.DownloadError("--sample-id values must be unique")
    by_alias = {row.alias: row for row in rows}
    missing = [alias for alias in requested if alias not in by_alias]
    if missing:
        raise base.DownloadError("Requested aliases are absent: " + ", ".join(missing))
    return [by_alias[alias] for alias in requested]


def render_raw_samples(rows: list[MdsManifestRow]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=("sample_id", "mds_path", "source_mpp"),
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "sample_id": row.alias,
                "mds_path": row.dataset_path.removeprefix("raw/"),
                "source_mpp": f"{row.source_mpp:.6f}",
            }
        )
    return buffer.getvalue()


def secure_token(path: Path) -> str:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_file():
        raise base.DownloadError(f"Token is not a regular file: {candidate}")
    mode = stat.S_IMODE(candidate.stat().st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise base.DownloadError("Token file must have mode 0600")
    token = candidate.read_text(encoding="utf-8").strip()
    if not token or any(character.isspace() for character in token):
        raise base.DownloadError("Token is empty or contains whitespace")
    return token


def fetch_remote_manifest(
    session: requests.Session,
    remote_files: dict[str, base.RemoteFile],
    name: str,
    retries: int,
) -> bytes:
    remote = remote_files.get(name)
    if remote is None:
        raise base.DownloadError(
            f"Zenodo record does not contain authoritative manifest {name!r}"
        )
    limit = 10 * 1024 * 1024
    if remote.size_bytes is not None and remote.size_bytes > limit:
        raise base.DownloadError("Refusing an unexpectedly large MDS manifest")
    response = base.request(session, "GET", remote.url, retries=retries)
    try:
        payload = response.content
    finally:
        response.close()
    if len(payload) > limit:
        raise base.DownloadError("Refusing an unexpectedly large MDS manifest")
    if remote.size_bytes is not None and len(payload) != remote.size_bytes:
        raise base.DownloadError("Remote MDS manifest size does not match Zenodo")
    if remote.md5 is not None:
        actual_md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
        if actual_md5 != remote.md5:
            raise base.DownloadError("Remote MDS manifest MD5 does not match Zenodo")
    try:
        payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise base.DownloadError("Remote MDS manifest is not UTF-8") from exc
    return payload


def _load_local_manifest(path: Path) -> tuple[list[MdsManifestRow], bytes]:
    try:
        rows, _ = load_manifest(path)
    except MdsManifestError as exc:
        raise base.DownloadError(str(exc)) from exc
    return rows, path.expanduser().resolve().read_bytes()


def verified_local_rows(
    root: Path, rows: list[MdsManifestRow]
) -> list[MdsManifestRow]:
    verified: list[MdsManifestRow] = []
    for row in rows:
        target = base.safe_target(root, row.dataset_path)
        if target.exists() and base.verify_file(target, row):
            verified.append(row)
    return verified


def download_mds_dataset(
    *,
    manifest: Path | None,
    record: str | None,
    output_dir: Path,
    api_url: str = base.DEFAULT_API_URL,
    manifest_name: str = DEFAULT_MANIFEST_NAME,
    dry_run: bool = False,
    overwrite: bool = False,
    retries: int = 5,
    token_file: Path | None = None,
    sample_ids: list[str] | None = None,
    expected_count: int | None = None,
    session: requests.Session | None = None,
) -> dict[str, object]:
    api_url = validated_api_url(api_url)
    if retries < 0:
        raise base.DownloadError("--retries must be non-negative")
    if expected_count is not None and expected_count <= 0:
        raise base.DownloadError("--expected-count must be greater than zero")
    if manifest_name != Path(manifest_name).name or manifest_name in {"", ".", ".."}:
        raise base.DownloadError("--manifest-name must be a plain file name")

    http = session or requests.Session()
    if token_file is not None:
        http.headers.update({"Authorization": f"Bearer {secure_token(token_file)}"})

    local_rows: list[MdsManifestRow] | None = None
    local_bytes: bytes | None = None
    if manifest is not None:
        local_rows, local_bytes = _load_local_manifest(manifest)

    remote_files: dict[str, base.RemoteFile] | None = None
    if record:
        remote_files = base.record_files(http, api_url, record, retries)
        for remote in remote_files.values():
            require_api_origin(remote.url, api_url, "record file")
        remote_bytes = fetch_remote_manifest(
            http, remote_files, manifest_name, retries
        )
        if local_bytes is not None and local_bytes != remote_bytes:
            raise base.DownloadError(
                "Local manifest differs byte-for-byte from the Zenodo record"
            )
        manifest_bytes = remote_bytes
        rows = parse_manifest_text(remote_bytes.decode("utf-8-sig"), manifest_name)
    elif local_rows is not None and local_bytes is not None:
        rows = local_rows
        manifest_bytes = local_bytes
    else:
        raise base.DownloadError("Provide --record or --manifest")

    selected = select_rows(rows, sample_ids or [])
    if expected_count is not None and len(selected) != expected_count:
        raise base.DownloadError(
            f"Expected {expected_count} selected MDS files, found {len(selected)}"
        )
    if remote_files is not None:
        base.validate_record(selected, remote_files)
    if not dry_run and remote_files is None:
        raise base.DownloadError("--record is required unless --dry-run is used")

    output_candidate = output_dir.expanduser().absolute()
    if output_candidate.is_symlink():
        raise base.DownloadError(
            f"Refusing symlink output directory: {output_candidate}"
        )
    root = output_candidate.resolve()
    plans = [
        {
            "alias": row.alias,
            "source": row.zenodo_filename,
            "target": str(base.safe_target(root, row.dataset_path)),
            "size_bytes": row.size_bytes,
        }
        for row in selected
    ]
    if dry_run:
        return {
            "dry_run": True,
            "file_count": len(selected),
            "total_size_bytes": sum(row.size_bytes for row in selected),
            "manifest_file_count": len(rows),
            "files": plans,
        }

    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    try:
        manifest_text = manifest_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:  # already checked, defensive invariant
        raise base.DownloadError("MDS manifest is not UTF-8") from exc
    base.preflight_local_artifact(
        root, manifest_name, manifest_text, overwrite=overwrite
    )

    statuses: dict[str, int] = {}
    assert remote_files is not None
    for row in selected:
        target = base.safe_target(root, row.dataset_path)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(target.parent, 0o700)
        with private_umask():
            status = base.download_one(
                http,
                remote_files[row.zenodo_filename],
                row,
                target,
                retries=retries,
                overwrite=overwrite,
            )
        os.chmod(target, 0o600)
        statuses[status] = statuses.get(status, 0) + 1
        print(f"{status}: {row.zenodo_filename}", file=sys.stderr, flush=True)

    present = verified_local_rows(root, rows)
    local_contents = {
        manifest_name: manifest_text,
        RAW_SAMPLES_NAME: render_raw_samples(present),
        CHECKSUMS_NAME: "".join(
            f"{row.sha256}  {row.dataset_path}\n" for row in present
        ),
    }
    artifacts = {
        manifest_name: base.write_local_artifact(
            root, manifest_name, manifest_text, overwrite=overwrite
        ),
        RAW_SAMPLES_NAME: base.write_local_artifact(
            root, RAW_SAMPLES_NAME, local_contents[RAW_SAMPLES_NAME], overwrite=True
        ),
        CHECKSUMS_NAME: base.write_local_artifact(
            root, CHECKSUMS_NAME, local_contents[CHECKSUMS_NAME], overwrite=True
        ),
    }
    for name in artifacts:
        os.chmod(base.safe_target(root, name), 0o600)
    return {
        "dry_run": False,
        "selected_file_count": len(selected),
        "verified_local_file_count": len(present),
        "selected_size_bytes": sum(row.size_bytes for row in selected),
        "verified_local_size_bytes": sum(row.size_bytes for row in present),
        "statuses": statuses,
        "local_artifacts": artifacts,
        "output_dir": str(root),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Optional local copy; must exactly match the manifest in the record",
    )
    parser.add_argument("--manifest-name", default=DEFAULT_MANIFEST_NAME)
    parser.add_argument("--record", help="Zenodo record ID, DOI, or record URL")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--api-url", default=base.DEFAULT_API_URL)
    parser.add_argument("--token-file", type=Path, help="Only for restricted records")
    parser.add_argument(
        "--sample-id",
        action="append",
        default=[],
        help="Download only this alias; repeatable",
    )
    parser.add_argument(
        "--expected-count",
        type=int,
        help="Fail unless exactly this many files are selected",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--retries", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = download_mds_dataset(
            manifest=args.manifest,
            record=args.record,
            output_dir=args.output_dir,
            api_url=args.api_url,
            manifest_name=args.manifest_name,
            token_file=args.token_file,
            sample_ids=args.sample_id,
            expected_count=args.expected_count,
            dry_run=args.dry_run,
            overwrite=args.overwrite,
            retries=args.retries,
        )
    except (base.DownloadError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
