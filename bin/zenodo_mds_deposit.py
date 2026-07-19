#!/usr/bin/env python3
"""Create or resume a restricted, unpublished Zenodo draft of sanitized MDS files.

This command is intentionally draft-only: it has no publication option. It
uploads every sanitized MDS plus the authoritative public manifest, verifies
local hashes, resumes matching remote files, and records state atomically.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlparse

import zenodo_deposit as base
from mds_manifest import MdsManifestError, load_manifest


DEFAULT_MANIFEST_NAME = "tumorquantai_lymphoma_mds_manifest.csv"
EXPECTED_MDS_COUNT = 21
EXPECTED_MDS_BYTES = 17_370_771_968
ALLOWED_API_ORIGINS = {"zenodo.org", "sandbox.zenodo.org"}
MDS_PRIVATE_COLUMNS = {
    "alias",
    "staged_path",
    "sanitized_sha256",
    "sanitized_md5",
    "pixel_stream_count",
    "pixel_sample_sha256",
    "pixel_full_sha256",
    "source_markers_absent",
    "validation_status",
}


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
        raise base.DepositError(
            "--api-url must be https://zenodo.org/api or "
            "https://sandbox.zenodo.org/api"
        )
    return url


class ProgressReader:
    """File wrapper that reports upload progress without exposing credentials."""

    def __init__(self, handle: BinaryIO, name: str, size: int) -> None:
        self.handle = handle
        self.name = name
        self.size = size
        self.last_reported = 0
        self.threshold = max(64 * 1024 * 1024, size // 20)

    def __len__(self) -> int:
        return self.size

    def read(self, amount: int = -1) -> bytes:
        chunk = self.handle.read(amount)
        position = self.handle.tell()
        if position == self.size or position - self.last_reported >= self.threshold:
            percent = 100.0 * position / self.size if self.size else 100.0
            print(
                f"uploading: {self.name} {position}/{self.size} bytes ({percent:.1f}%)",
                file=sys.stderr,
                flush=True,
            )
            self.last_reported = position
        return chunk

    def seek(self, offset: int, whence: int = 0) -> int:
        result = self.handle.seek(offset, whence)
        if result == 0:
            self.last_reported = 0
        return result

    def tell(self) -> int:
        return self.handle.tell()

    def fileno(self) -> int:
        return self.handle.fileno()

    @property
    def mode(self) -> str:
        return str(getattr(self.handle, "mode", "rb"))


class ProgressZenodoClient(base.ZenodoClient):
    def upload_file(self, bucket_url: str, upload: base.UploadFile) -> dict[str, object]:
        url = f"{bucket_url.rstrip('/')}/{base.quote(upload.remote_name, safe='')}"
        with upload.local_path.open("rb") as handle:
            progress = ProgressReader(handle, upload.remote_name, upload.size_bytes)
            response = self.request(
                "PUT",
                url,
                expected=(200, 201),
                data=progress,
                timeout=(15.0, 6 * 60 * 60.0),
            )
        return self.json_response(response, f"Upload of {upload.remote_name}")


def read_rows(path: Path, required: set[str], description: str) -> list[dict[str, str]]:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_file():
        raise base.DepositError(f"{description} is not a regular file: {candidate}")
    with candidate.resolve().open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = required - fields
        if missing:
            raise base.DepositError(
                f"{description} is missing columns: {', '.join(sorted(missing))}"
            )
        return [dict(row) for row in reader]


def truthy(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes"}


def collect_mds_uploads(
    public_manifest: Path, private_mapping: Path
) -> list[base.UploadFile]:
    try:
        public_rows, _ = load_manifest(public_manifest)
    except MdsManifestError as exc:
        raise base.DepositError(str(exc)) from exc
    private_path = base.secure_file(private_mapping, "MDS private mapping")
    private_rows = read_rows(
        private_path, MDS_PRIVATE_COLUMNS, "MDS private mapping"
    )
    private_by_alias: dict[str, dict[str, str]] = {}
    for private in private_rows:
        alias = str(private.get("alias", "")).strip()
        if not base.ALIAS_RE.fullmatch(alias) or alias in private_by_alias:
            raise base.DepositError(
                "MDS private mapping contains an unsafe/duplicate alias"
            )
        private_by_alias[alias] = private

    uploads: list[base.UploadFile] = []
    seen_aliases: set[str] = set()
    seen_names: set[str] = set()
    for row in public_rows:
        alias = row.alias
        name = base.safe_remote_name(row.zenodo_filename)
        if not base.ALIAS_RE.fullmatch(alias) or alias in seen_aliases:
            raise base.DepositError(
                "MDS public manifest contains an unsafe/duplicate alias"
            )
        if name != f"{alias}.mds" or name in seen_names:
            raise base.DepositError(
                "MDS Zenodo filename must be the exact alias plus .mds"
            )
        private = private_by_alias.get(alias)
        if private is None:
            raise base.DepositError(f"MDS private mapping lacks alias: {alias}")
        if not truthy(str(private.get("source_markers_absent", ""))):
            raise base.DepositError(f"MDS privacy validation is incomplete: {alias}")
        if not str(private.get("validation_status", "")).startswith("validated-"):
            raise base.DepositError(
                f"MDS structural validation is incomplete: {alias}"
            )
        candidate = (
            Path(str(private.get("staged_path", "")).strip())
            .expanduser()
            .absolute()
        )
        if candidate.is_symlink() or not candidate.is_file():
            raise base.DepositError(f"Staged MDS is not a regular file: {alias}")
        path = candidate.resolve()
        expected_sha = row.sha256
        expected_md5 = row.md5
        if (
            str(private.get("sanitized_sha256", "")).strip().casefold()
            != expected_sha
        ):
            raise base.DepositError(f"Public/private SHA-256 mismatch: {alias}")
        if (
            str(private.get("sanitized_md5", "")).strip().casefold()
            != expected_md5
        ):
            raise base.DepositError(f"Public/private MD5 mismatch: {alias}")
        try:
            private_stream_count = int(
                str(private.get("pixel_stream_count", "")).strip()
            )
        except ValueError as exc:
            raise base.DepositError(
                f"Invalid private pixel stream count: {alias}"
            ) from exc
        if private_stream_count != row.pixel_stream_count:
            raise base.DepositError(
                f"Public/private pixel stream count mismatch: {alias}"
            )
        if (
            str(private.get("pixel_sample_sha256", "")).strip().casefold()
            != row.pixel_sample_sha256
        ):
            raise base.DepositError(
                f"Public/private pixel fingerprint mismatch: {alias}"
            )
        if (
            str(private.get("pixel_full_sha256", "")).strip().casefold()
            != row.pixel_full_sha256
        ):
            raise base.DepositError(
                f"Public/private full pixel fingerprint mismatch: {alias}"
            )
        size, sha256, md5 = base.digest_file(path)
        if (size, sha256, md5) != (row.size_bytes, expected_sha, expected_md5):
            raise base.DepositError(f"Staged MDS differs from manifests: {alias}")
        uploads.append(
            base.UploadFile(path, name, size, sha256, md5, "sanitized-mds")
        )
        seen_aliases.add(alias)
        seen_names.add(name)

    if len(uploads) != EXPECTED_MDS_COUNT:
        raise base.DepositError(
            f"Expected {EXPECTED_MDS_COUNT} MDS files, found {len(uploads)}"
        )
    mds_bytes = sum(item.size_bytes for item in uploads)
    if mds_bytes != EXPECTED_MDS_BYTES:
        raise base.DepositError(
            f"Expected {EXPECTED_MDS_BYTES} MDS bytes, found {mds_bytes}"
        )
    if set(private_by_alias) != seen_aliases:
        raise base.DepositError(
            "MDS private mapping contains unreviewed extra aliases"
        )

    manifest_candidate = public_manifest.expanduser().absolute()
    if manifest_candidate.is_symlink() or not manifest_candidate.is_file():
        raise base.DepositError("MDS public manifest is not a regular file")
    uploads.append(
        base.make_small_upload(
            manifest_candidate.resolve(),
            DEFAULT_MANIFEST_NAME,
            "public-manifest",
        )
    )
    if len(uploads) > base.ZENODO_MAX_FILES:
        raise base.DepositError("MDS deposit exceeds Zenodo's 100-file limit")
    if any(item.size_bytes > base.ZENODO_MAX_FILE_BYTES for item in uploads):
        raise base.DepositError("An MDS file exceeds Zenodo's 50 GB file limit")
    return sorted(uploads, key=lambda item: item.remote_name.casefold())


def restricted_metadata_from_file(path: Path) -> dict[str, object]:
    payload = base.load_json(path, "Zenodo metadata file")
    raw = payload.get("metadata", payload)
    if not isinstance(raw, dict):
        raise base.DepositError("Zenodo metadata must be a JSON object")
    metadata = dict(raw)
    required = (
        "title",
        "description",
        "upload_type",
        "access_right",
        "access_conditions",
    )
    missing = [field for field in required if not str(metadata.get(field, "")).strip()]
    if missing:
        raise base.DepositError(
            "Restricted Zenodo metadata is missing: " + ", ".join(missing)
        )
    if str(metadata["upload_type"]).strip().casefold() != "dataset":
        raise base.DepositError("Zenodo upload_type must be dataset")
    if str(metadata["access_right"]).strip().casefold() != "restricted":
        raise base.DepositError("Raw pathology MDS drafts must be restricted")
    creators = metadata.get("creators")
    if (
        not isinstance(creators, list)
        or not creators
        or any(
            not isinstance(item, dict)
            or not str(item.get("name", "")).strip()
            for item in creators
        )
    ):
        raise base.DepositError(
            "Restricted Zenodo metadata requires named creators"
        )
    license_id = str(metadata.get("license", "")).strip()
    if license_id:
        metadata["license"] = license_id
    else:
        metadata.pop("license", None)
    return metadata


def validate_draft_metadata(
    payload: dict[str, object], expected: dict[str, object]
) -> None:
    actual = payload.get("metadata")
    if not isinstance(actual, dict):
        raise base.DepositError("Zenodo draft response has no metadata object")
    fields = (
        "title",
        "description",
        "upload_type",
        "access_right",
        "license",
        "creators",
        "access_conditions",
        "keywords",
        "related_identifiers",
    )
    for field in fields:
        if field in expected and actual.get(field) != expected.get(field):
            raise base.DepositError(
                f"Zenodo draft metadata does not match requested {field}"
            )
    if str(actual.get("access_right", "")).casefold() != "restricted":
        raise base.DepositError("Zenodo draft is not restricted")
    if not str(actual.get("access_conditions", "")).strip():
        raise base.DepositError("Zenodo draft lacks restricted access conditions")
    if payload.get("submitted") is not False:
        raise base.DepositError("Zenodo deposition is not an unpublished draft")
    if payload.get("state") not in {None, "inprogress", "unsubmitted"}:
        raise base.DepositError("Zenodo deposition is not editable")


def deposit_mds(
    *,
    public_manifest: Path,
    private_mapping: Path,
    metadata_file: Path,
    state_file: Path,
    token_env: str = base.DEFAULT_TOKEN_ENV,
    token_file: Path | None = None,
    api_url: str = base.DEFAULT_API_URL,
    retries: int = 5,
    replace_mismatched: bool = False,
    plan: bool = False,
    session=None,
) -> dict[str, object]:
    api_url = validated_api_url(api_url)
    metadata = restricted_metadata_from_file(metadata_file)
    if str(metadata.get("access_right", "")).strip().casefold() != "restricted":
        raise base.DepositError(
            "Raw pathology MDS drafts must use access_right=restricted"
        )
    if not str(metadata.get("access_conditions", "")).strip():
        raise base.DepositError(
            "Restricted raw pathology MDS drafts require access_conditions"
        )
    uploads = collect_mds_uploads(public_manifest, private_mapping)
    fingerprint = base.release_fingerprint(metadata, uploads)
    plan_result = {
        "draft_only": True,
        "restricted": True,
        "file_count": len(uploads),
        "mds_file_count": len(
            [item for item in uploads if item.kind == "sanitized-mds"]
        ),
        "mds_total_size_bytes": sum(
            item.size_bytes for item in uploads if item.kind == "sanitized-mds"
        ),
        "total_size_bytes": sum(item.size_bytes for item in uploads),
        "release_fingerprint_sha256": fingerprint,
        "files": [
            {
                "name": item.remote_name,
                "size_bytes": item.size_bytes,
                "kind": item.kind,
            }
            for item in uploads
        ],
    }
    if plan:
        return {"plan": True, **plan_result}

    token = base.resolve_token(token_env, token_file)
    client = ProgressZenodoClient(
        token, api_url, retries=retries, session=session
    )
    state_path = state_file.expanduser().absolute()
    state = base.load_state(state_path)
    if state is not None:
        if str(state.get("api_url", "")).rstrip("/") != api_url.rstrip("/"):
            raise base.DepositError("Deposit state belongs to another API URL")
        if (
            state.get("schema_version") != 1
            or state.get("dataset_format") != "sanitized-mds"
            or state.get("status") != "draft"
            or state.get("release_fingerprint_sha256") != fingerprint
            or not isinstance(state.get("uploaded"), dict)
        ):
            raise base.DepositError(
                "Deposit state schema, format, status, or fingerprint is invalid"
            )
        deposition_id = str(state.get("deposition_id", "")).strip()
        if not deposition_id.isdigit():
            raise base.DepositError("Deposit state has no numeric deposition ID")
        draft = client.get_draft(deposition_id)
    else:
        draft = client.create_draft()
        deposition_id = base.deposition_id_from_payload(draft)
        state = {
            "schema_version": 1,
            "dataset_format": "sanitized-mds",
            "api_url": api_url.rstrip("/"),
            "deposition_id": deposition_id,
            "release_fingerprint_sha256": fingerprint,
            "status": "draft",
            "uploaded": {},
        }
        base.atomic_json(state_path, state)

    state["release_fingerprint_sha256"] = fingerprint
    expected_remote_names = {item.remote_name for item in uploads}
    initial_remote = base.parse_remote_files(draft)
    unexpected = sorted(set(initial_remote) - expected_remote_names)
    if unexpected:
        raise base.DepositError(
            "Draft contains unreviewed extra files before upload"
        )
    bucket_url = base.bucket_from_payload(draft)
    updated = client.update_metadata(deposition_id, metadata)
    validate_draft_metadata(updated, metadata)
    refreshed = client.get_draft(deposition_id)
    validate_draft_metadata(refreshed, metadata)
    remote_files = base.parse_remote_files(refreshed)
    unexpected = sorted(set(remote_files) - expected_remote_names)
    if unexpected:
        raise base.DepositError(
            "Draft contains unreviewed extra files before upload"
        )
    uploaded_state = state.get("uploaded")
    if not isinstance(uploaded_state, dict):
        uploaded_state = {}
        state["uploaded"] = uploaded_state

    for upload in uploads:
        existing = remote_files.get(upload.remote_name)
        if existing is not None and base.file_matches(existing, upload):
            status = "verified-existing"
        else:
            if existing is not None:
                if not replace_mismatched:
                    raise base.DepositError(
                        f"Draft file differs: {upload.remote_name}; "
                        "review before replacement"
                    )
                if not existing.delete_url:
                    raise base.DepositError("Zenodo omitted a deletion URL")
                client.delete_file(existing.delete_url)
            base.verify_local(upload)
            response = client.upload_file(bucket_url, upload)
            base.validate_upload_response(response, upload)
            status = "uploaded"
        uploaded_state[upload.remote_name] = {
            "size_bytes": upload.size_bytes,
            "md5": upload.md5,
            "status": status,
        }
        base.atomic_json(state_path, state)
        print(f"{status}: {upload.remote_name}", file=sys.stderr, flush=True)

    verified = client.get_draft(deposition_id)
    validate_draft_metadata(verified, metadata)
    remote = base.parse_remote_files(verified)
    for upload in uploads:
        candidate = remote.get(upload.remote_name)
        if candidate is None or not base.file_matches(candidate, upload):
            raise base.DepositError(
                f"Final verification failed: {upload.remote_name}"
            )
    unexpected = sorted(set(remote) - {item.remote_name for item in uploads})
    if unexpected:
        raise base.DepositError("Draft contains unreviewed extra files")
    state["status"] = "draft"
    base.atomic_json(state_path, state)
    links = verified.get("links") if isinstance(verified.get("links"), dict) else {}
    return {
        "plan": False,
        "deposition_id": deposition_id,
        "status": "restricted-unpublished-draft",
        "draft_url": str(
            links.get("html") or f"https://zenodo.org/deposit/{deposition_id}"
        ),
        **plan_result,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-manifest", required=True, type=Path)
    parser.add_argument("--private-mapping", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--token-env", default=base.DEFAULT_TOKEN_ENV)
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--api-url", default=base.DEFAULT_API_URL)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--replace-mismatched", action="store_true")
    parser.add_argument("--plan", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = deposit_mds(
            public_manifest=args.public_manifest,
            private_mapping=args.private_mapping,
            metadata_file=args.metadata,
            state_file=args.state,
            token_env=args.token_env,
            token_file=args.token_file,
            api_url=args.api_url,
            retries=args.retries,
            replace_mismatched=args.replace_mismatched,
            plan=args.plan,
        )
    except (base.DepositError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
