#!/usr/bin/env python3
"""Publish one fully verified breast-IHC Zenodo draft, exactly once.

This command is separate from the draft uploader. It cannot create a draft,
upload a file, replace a file, or modify metadata. Publication requires an
existing fingerprint-bound draft state and an independent mode-0600 approval.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import zenodo_breast_ihc_deposit as draft


base = draft.base
DepositError = draft.DepositError
PUBLISH_CONFIRMATIONS = base.PUBLISH_CONFIRMATIONS
AUTHORIZATION_KEYS = frozenset(
    {
        *PUBLISH_CONFIRMATIONS,
        "authorized_by",
        "authorized_at",
        "license",
        "release_fingerprint_sha256",
    }
)
PUBLICATION_PROOF_KEYS = frozenset(
    {
        "authorization_sha256",
        "authorized_by",
        "authorized_at",
        "license",
        "release_fingerprint_sha256",
    }
)
DRAFT_STATE_KEYS = frozenset(
    {
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
)
TRANSITION_STATE_KEYS = DRAFT_STATE_KEYS | {"publication"}
VERIFYING_STATE_KEYS = TRANSITION_STATE_KEYS | {"record_id"}
PUBLISHED_STATE_KEYS = VERIFYING_STATE_KEYS | {
    "doi",
    "doi_url",
    "published_at",
    "record_url",
}
TRANSITION_STATUSES = frozenset(
    {"draft", "publish-intent", "verifying-publication", "published"}
)


@dataclass(frozen=True)
class PublicationAuthorization:
    path: Path
    payload: dict[str, object]
    proof: dict[str, object]


@dataclass(frozen=True)
class PublishedRecord:
    record_url: str
    doi: str
    doi_url: str


def _private_json_bytes(path: Path, label: str) -> tuple[Path, bytes]:
    resolved = draft._private_file(path, label)
    before = resolved.stat()
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        raise DepositError(f"Cannot read {label}") from exc
    after = resolved.stat()
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
        before.st_mode,
        before.st_uid,
        before.st_nlink,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
        after.st_mode,
        after.st_uid,
        after.st_nlink,
    )
    if identity_before != identity_after:
        raise DepositError(f"{label} changed while it was read")
    return resolved, raw


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DepositError(f"Publication authorization has a duplicate key: {key}")
        result[key] = value
    return result


def validate_publication_authorization(
    path: Path,
    *,
    metadata: dict[str, object],
    fingerprint: str,
    package_root: Path,
    state_path: Path,
    token_path: Path | None,
) -> PublicationAuthorization:
    resolved, raw = _private_json_bytes(path, "Publication authorization")
    if draft._is_within(resolved, package_root):
        raise DepositError("Publication authorization must be outside --package-dir")
    forbidden_paths = {state_path.resolve(strict=False)}
    if token_path is not None:
        forbidden_paths.add(token_path.expanduser().absolute().resolve(strict=False))
    if resolved in forbidden_paths:
        raise DepositError("Publication authorization must be an independent file")
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DepositError("Publication authorization is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict) or set(payload) != AUTHORIZATION_KEYS:
        raise DepositError("Publication authorization key roster is not exact")
    missing = [key for key in PUBLISH_CONFIRMATIONS if payload.get(key) is not True]
    if missing:
        raise DepositError(
            "Publication authorization lacks true confirmations: " + ", ".join(missing)
        )
    authorized_by = payload.get("authorized_by")
    authorized_at = payload.get("authorized_at")
    license_id = payload.get("license")
    if not isinstance(authorized_by, str) or not authorized_by.strip():
        raise DepositError("Publication authorization requires authorized_by")
    if not isinstance(authorized_at, str) or not authorized_at.strip():
        raise DepositError("Publication authorization requires authorized_at")
    if not isinstance(license_id, str) or not license_id.strip():
        raise DepositError("Publication authorization requires license")
    if base.UNRESOLVED_PLACEHOLDER_RE.search(authorized_by):
        raise DepositError("Publication authorization contains an unresolved signer")
    try:
        authorization_time = datetime.fromisoformat(
            authorized_at.strip().replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise DepositError(
            "Publication authorization authorized_at is not ISO-8601"
        ) from exc
    if authorization_time.tzinfo is None:
        raise DepositError(
            "Publication authorization authorized_at requires a timezone"
        )
    expected_license = str(metadata.get("license", ""))
    if license_id.strip() != expected_license:
        raise DepositError(
            "Authorized license does not exactly match canonical Zenodo metadata"
        )
    observed_fingerprint = str(payload.get("release_fingerprint_sha256", "")).strip()
    if not re.fullmatch(r"[0-9a-f]{64}", observed_fingerprint):
        raise DepositError(
            "Publication authorization fingerprint must be lowercase SHA-256"
        )
    if observed_fingerprint != fingerprint:
        raise DepositError(
            "Publication authorization is not bound to this exact release"
        )
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    proof = {
        "authorization_sha256": hashlib.sha256(canonical).hexdigest(),
        "authorized_by": authorized_by.strip(),
        "authorized_at": authorization_time.isoformat(),
        "license": expected_license,
        "release_fingerprint_sha256": fingerprint,
    }
    return PublicationAuthorization(resolved, dict(payload), proof)


def _validate_uploaded_state(
    uploaded: object,
    uploads: tuple[base.UploadFile, ...],
) -> None:
    if not isinstance(uploaded, dict):
        raise DepositError("Deposit state uploaded map is invalid")
    expected = {item.remote_name: item for item in uploads}
    if set(uploaded) != set(expected):
        raise DepositError("Deposit state does not record all exact 55 verified files")
    for name, value in uploaded.items():
        upload = expected[name]
        if (
            not isinstance(value, dict)
            or set(value) != {"size_bytes", "md5", "status"}
            or value.get("size_bytes") != upload.size_bytes
            or value.get("md5") != upload.md5
            or value.get("status") not in {"uploaded", "verified-existing"}
        ):
            raise DepositError("Deposit state contains invalid upload verification")


def load_publication_state(
    state_file: Path,
    *,
    package_data: draft.ValidatedPackage,
    api_url: str,
    fingerprint: str,
    deposition_id: str,
) -> tuple[Path, dict[str, object]]:
    if not deposition_id.isdigit():
        raise DepositError("--deposition-id must be numeric")
    candidate = state_file.expanduser().absolute()
    resolved = candidate.resolve(strict=False)
    if draft._is_within(resolved, package_data.root):
        raise DepositError("Publication state must be outside --package-dir")
    if not candidate.exists():
        raise DepositError("Publication requires an existing deposit state")
    path = draft._private_file(candidate, "Zenodo deposit state")
    state = base.load_json(path, "Zenodo deposit state")
    status = state.get("status")
    if status not in TRANSITION_STATUSES:
        raise DepositError("Zenodo deposit state has an invalid publication status")
    expected_keys = {
        "draft": DRAFT_STATE_KEYS,
        "publish-intent": TRANSITION_STATE_KEYS,
        "verifying-publication": VERIFYING_STATE_KEYS,
        "published": PUBLISHED_STATE_KEYS,
    }[str(status)]
    if set(state) != expected_keys:
        raise DepositError("Zenodo deposit state key roster is invalid")
    if (
        state.get("schema_version") != 1
        or state.get("dataset_format") != draft.DATASET_FORMAT
        or state.get("api_url") != api_url
        or state.get("deposition_id") != deposition_id
        or state.get("release_fingerprint_sha256") != fingerprint
        or state.get("file_count") != draft.EXPECTED_UPLOAD_FILES
        or state.get("total_size_bytes") != package_data.total_size_bytes
    ):
        raise DepositError(
            "Zenodo deposit state is not bound to this exact release/deposition"
        )
    _validate_uploaded_state(state.get("uploaded"), package_data.uploads)
    if status != "draft":
        publication = state.get("publication")
        if (
            not isinstance(publication, dict)
            or set(publication) != PUBLICATION_PROOF_KEYS
        ):
            raise DepositError("Zenodo deposit state publication proof is invalid")
    if status in {"verifying-publication", "published"}:
        if not str(state.get("record_id", "")).isdigit():
            raise DepositError("Zenodo deposit state record_id is invalid")
    if status == "published":
        for key in ("doi", "doi_url", "record_url"):
            value = state.get(key)
            if not isinstance(value, str) or not value.strip():
                raise DepositError(f"Zenodo deposit state {key} is invalid")
        if not re.fullmatch(r"10\.[0-9]{4,9}/\S+", str(state["doi"]), re.IGNORECASE):
            raise DepositError("Zenodo deposit state DOI is invalid")
        published_at = state.get("published_at")
        if not isinstance(published_at, str):
            raise DepositError("Zenodo deposit state published_at is invalid")
        try:
            parsed = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DepositError("Zenodo deposit state published_at is invalid") from exc
        if parsed.tzinfo is None:
            raise DepositError("Zenodo deposit state published_at needs a timezone")
    return path, state


@contextmanager
def exclusive_state_lock(path: Path):
    lock_path = path.with_name(f".{path.name}.publish.lock")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    handle = os.fdopen(descriptor, "r+b")
    try:
        observed = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_IMODE(observed.st_mode) != 0o600
            or observed.st_nlink != 1
            or (hasattr(os, "getuid") and observed.st_uid != os.getuid())
        ):
            raise DepositError(
                "Publication lock must be a current-owner, single-link mode-0600 file"
            )
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DepositError(
                "Another publication process holds the state lock"
            ) from exc
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def resolve_publication_token(
    token_file: Path,
    *,
    package_root: Path,
    state_path: Path,
    authorization_path: Path,
) -> str:
    path = draft._private_file(
        token_file,
        "Zenodo deposit:write + deposit:actions token file",
    )
    if draft._is_within(path, package_root):
        raise DepositError("Zenodo token file must be outside --package-dir")
    if path in {state_path, authorization_path}:
        raise DepositError("Zenodo token, state, and authorization must be distinct")
    token = path.read_text(encoding="utf-8").strip()
    if not token or any(character.isspace() for character in token):
        raise DepositError("Zenodo token is empty or contains whitespace")
    return token


def _metadata_projection_matches(
    payload: dict[str, object],
    metadata: dict[str, object],
) -> None:
    actual = payload.get("metadata")
    if not isinstance(actual, dict):
        raise DepositError("Zenodo response has no metadata object")
    draft.validate_open_unpublished_draft(
        {
            "submitted": False,
            "state": "unsubmitted",
            "metadata": actual,
        },
        metadata,
    )


def _published_record_metadata_projection_matches(
    payload: dict[str, object],
    metadata: dict[str, object],
) -> None:
    """Match the public Records API resource-type representation strictly."""
    actual = payload.get("metadata")
    if not isinstance(actual, dict):
        raise DepositError("Zenodo response has no metadata object")
    projected_actual = dict(actual)
    if "upload_type" in actual:
        if "resource_type" in actual:
            raise DepositError(
                "Zenodo public record has ambiguous upload/resource types"
            )
    else:
        resource_type = actual.get("resource_type")
        if not isinstance(resource_type, dict):
            raise DepositError("Zenodo public record has no valid resource type")
        type_values: list[str] = []
        for field in ("type", "id"):
            if field not in resource_type:
                continue
            value = resource_type[field]
            if not isinstance(value, str) or not value.strip():
                raise DepositError("Zenodo public record has no valid resource type")
            type_values.append(value.strip())
        if not type_values:
            raise DepositError("Zenodo public record has no valid resource type")
        if len({value.casefold() for value in type_values}) != 1:
            raise DepositError("Zenodo public record has ambiguous resource types")
        projected_actual.pop("resource_type")
        projected_actual["upload_type"] = type_values[0]
    observed_license = actual.get("license")
    if isinstance(observed_license, dict):
        license_id = observed_license.get("id")
        if not isinstance(license_id, str) or not license_id.strip():
            raise DepositError("Zenodo public record has no valid license ID")
        projected_actual["license"] = license_id.strip()
    _metadata_projection_matches(
        {**payload, "metadata": projected_actual},
        metadata,
    )


def _published_record_html_url(links: dict[str, object]) -> str:
    urls: list[str] = []
    for field in ("self_html", "html"):
        if field not in links:
            continue
        value = links[field]
        if not isinstance(value, str) or not value.strip():
            raise DepositError("Zenodo record response has no public record URL")
        urls.append(value.strip())
    if not urls:
        raise DepositError("Zenodo record response has no public record URL")
    if len(set(urls)) != 1:
        raise DepositError("Zenodo record response has conflicting public URLs")
    return urls[0]


def exact_remote_files(
    payload: dict[str, object],
    uploads: tuple[base.UploadFile, ...],
) -> dict[str, base.RemoteFile]:
    raw_files = payload.get("files")
    if not isinstance(raw_files, list):
        raise DepositError("Zenodo response has no valid files array")
    for item in raw_files:
        if not isinstance(item, dict):
            raise DepositError("Zenodo response contains an invalid file object")
        name = str(item.get("filename") or item.get("key") or "").strip()
        base.safe_remote_name(name)
    files = base.parse_remote_files(payload)
    if len(files) != len(raw_files) or any(
        item.size_bytes is None or item.md5 is None for item in files.values()
    ):
        raise DepositError("Zenodo response file metadata is incomplete")
    expected = {item.remote_name: item for item in uploads}
    if set(files) != set(expected):
        raise DepositError("Zenodo remote file roster is not the exact 55-file release")
    for name, upload in expected.items():
        if not base.file_matches(files[name], upload):
            raise DepositError(f"Zenodo remote file differs from release: {name}")
    return files


def validate_editable_draft_for_publication(
    payload: dict[str, object],
    *,
    deposition_id: str,
    metadata: dict[str, object],
    uploads: tuple[base.UploadFile, ...],
) -> None:
    if str(payload.get("id") or "") != deposition_id:
        raise DepositError("Zenodo draft response has the wrong deposition ID")
    if payload.get("submitted") is not False:
        raise DepositError("Zenodo deposition is not an unpublished draft")
    if payload.get("state") not in {"unsubmitted", "inprogress"}:
        raise DepositError("Zenodo deposition is not explicitly editable")
    _metadata_projection_matches(payload, metadata)
    exact_remote_files(payload, uploads)


def _record_id(payload: dict[str, object], deposition_id: str) -> str:
    response_deposition_id = payload.get("id")
    if (
        response_deposition_id is not None
        and str(response_deposition_id) != deposition_id
    ):
        raise DepositError("Zenodo publish response names another deposition")
    record_id = str(payload.get("record_id") or "").strip()
    if not record_id.isdigit():
        raise DepositError("Zenodo published deposition has no numeric record_id")
    return record_id


def validate_published_deposition(
    payload: dict[str, object],
    *,
    deposition_id: str,
    metadata: dict[str, object],
    uploads: tuple[base.UploadFile, ...],
) -> str:
    if str(payload.get("id") or "") != deposition_id:
        raise DepositError("Zenodo published deposition has the wrong ID")
    if payload.get("submitted") is not True:
        raise DepositError("Zenodo deposition is not confirmed published")
    if payload.get("state") != "done":
        raise DepositError("Zenodo deposition is not in the published done state")
    _metadata_projection_matches(payload, metadata)
    exact_remote_files(payload, uploads)
    return _record_id(payload, deposition_id)


def validate_published_record(
    payload: dict[str, object],
    *,
    record_id: str,
    api_url: str,
    metadata: dict[str, object],
    uploads: tuple[base.UploadFile, ...],
) -> PublishedRecord:
    if str(payload.get("id") or "") != record_id:
        raise DepositError("Zenodo record response has the wrong record ID")
    _published_record_metadata_projection_matches(payload, metadata)
    exact_remote_files(payload, uploads)
    links = payload.get("links") if isinstance(payload.get("links"), dict) else {}
    record_url = _published_record_html_url(links)
    doi = str(payload.get("doi") or "").strip()
    doi_url = str(links.get("doi") or "").strip()
    if not re.fullmatch(r"10\.[0-9]{4,9}/\S+", doi, re.IGNORECASE):
        raise DepositError("Zenodo record response has no valid DOI")
    parsed = draft.urlparse(record_url)
    expected_origin = draft.urlparse(api_url)
    if (
        parsed.scheme != expected_origin.scheme
        or parsed.netloc != expected_origin.netloc
    ):
        raise DepositError("Zenodo record response has an unsafe public URL")
    parsed_doi = draft.urlparse(doi_url)
    if (
        parsed_doi.scheme != "https"
        or parsed_doi.netloc.casefold() != "doi.org"
        or parsed_doi.path.lstrip("/").casefold() != doi.casefold()
    ):
        raise DepositError("Zenodo record response has an invalid DOI URL")
    return PublishedRecord(record_url, doi, doi_url)


class PublishZenodoClient(draft.HardenedZenodoClient):
    def publish_once(self, deposition_id: str) -> dict[str, object]:
        response = self.request(
            "POST",
            f"{self.api_url}/deposit/depositions/{deposition_id}/actions/publish",
            expected=(202,),
            retries=0,
        )
        return self.json_response(response, "Publish-deposition request")

    def get_public_record(self, record_id: str) -> dict[str, object]:
        url = f"{self.api_url}/records/{record_id}"
        try:
            response = self.session.request(
                "GET",
                url,
                headers={"Accept": "application/json"},
                timeout=(15.0, 120.0),
                allow_redirects=False,
            )
        except base.requests.RequestException as exc:
            raise DepositError("Public Zenodo record verification failed") from exc
        if response.status_code != 200:
            response.close()
            raise DepositError(
                "Public Zenodo record is not yet available for verification"
            )
        return self.json_response(response, "Get-record request")


def _proof_matches(state: dict[str, object], proof: dict[str, object]) -> None:
    if state.get("publication") != proof:
        raise DepositError(
            "Publication authorization differs from the state-bound proof"
        )


def _mark_transition(
    state_path: Path,
    state: dict[str, object],
    *,
    status: str,
    proof: dict[str, object],
    record_id: str | None = None,
    published_record: PublishedRecord | None = None,
) -> None:
    state["status"] = status
    state["publication"] = proof
    if record_id is not None:
        state["record_id"] = record_id
    if status == "published":
        if published_record is None:
            raise DepositError("Published state requires verified record details")
        state["doi"] = published_record.doi
        state["doi_url"] = published_record.doi_url
        state["record_url"] = published_record.record_url
        state["published_at"] = datetime.now(timezone.utc).isoformat()
    base.atomic_json(state_path, state)


def _execute_publication_locked(
    *,
    package_data: draft.ValidatedPackage,
    metadata: dict[str, object],
    state_path: Path,
    state: dict[str, object],
    deposition_id: str,
    authorization: PublicationAuthorization,
    token_file: Path,
    api_url: str,
    retries: int,
    session,
) -> dict[str, object]:
    status = str(state["status"])
    if status == "published":
        _proof_matches(state, authorization.proof)
        raise DepositError("Deposit state is already marked published")
    if status != "draft":
        _proof_matches(state, authorization.proof)

    token = resolve_publication_token(
        token_file,
        package_root=package_data.root,
        state_path=state_path,
        authorization_path=authorization.path,
    )
    client = PublishZenodoClient(
        token,
        api_url,
        retries=retries,
        session=session,
    )
    if status == "draft":
        remote_draft = client.get_draft(deposition_id)
        validate_editable_draft_for_publication(
            remote_draft,
            deposition_id=deposition_id,
            metadata=metadata,
            uploads=package_data.uploads,
        )
        for upload in package_data.uploads:
            base.verify_local(upload)
        _mark_transition(
            state_path,
            state,
            status="publish-intent",
            proof=authorization.proof,
        )
        publish_response = client.publish_once(deposition_id)
        response_record_id = validate_published_deposition(
            publish_response,
            deposition_id=deposition_id,
            metadata=metadata,
            uploads=package_data.uploads,
        )
        published_deposition = client.get_draft(deposition_id)
        record_id = validate_published_deposition(
            published_deposition,
            deposition_id=deposition_id,
            metadata=metadata,
            uploads=package_data.uploads,
        )
        if record_id != response_record_id:
            raise DepositError("Zenodo publish response and deposition disagree")
        _mark_transition(
            state_path,
            state,
            status="verifying-publication",
            proof=authorization.proof,
            record_id=record_id,
        )
    elif status == "publish-intent":
        published_deposition = client.get_draft(deposition_id)
        if published_deposition.get("submitted") is not True:
            raise DepositError(
                "Publication outcome is ambiguous; refusing a second publish action"
            )
        record_id = validate_published_deposition(
            published_deposition,
            deposition_id=deposition_id,
            metadata=metadata,
            uploads=package_data.uploads,
        )
        _mark_transition(
            state_path,
            state,
            status="verifying-publication",
            proof=authorization.proof,
            record_id=record_id,
        )
    else:
        record_id = str(state["record_id"])

    record = client.get_public_record(record_id)
    published_record = validate_published_record(
        record,
        record_id=record_id,
        api_url=api_url,
        metadata=metadata,
        uploads=package_data.uploads,
    )
    _mark_transition(
        state_path,
        state,
        status="published",
        proof=authorization.proof,
        record_id=record_id,
        published_record=published_record,
    )
    return {
        "status": "published",
        "record_id": record_id,
        "record_url": published_record.record_url,
        "doi": published_record.doi,
        "doi_url": published_record.doi_url,
    }


def publish_breast_ihc(
    *,
    package_dir: Path,
    metadata_file: Path,
    state_file: Path,
    deposition_id: str,
    authorization_file: Path | None = None,
    token_file: Path | None = None,
    api_url: str = draft.DEFAULT_API_URL,
    retries: int = 5,
    plan: bool = False,
    publish: bool = False,
    session=None,
) -> dict[str, object]:
    if retries < 0:
        raise DepositError("--retries must be non-negative")
    if plan == publish:
        raise DepositError("Select exactly one of --plan or --publish")
    if plan and (authorization_file is not None or token_file is not None):
        raise DepositError("--plan does not accept credentials or authorization")
    api_url = draft.validated_api_url(api_url)
    package_data = draft.validate_package_directory(package_dir)
    metadata = draft.public_metadata_from_file(metadata_file)
    fingerprint = base.release_fingerprint(metadata, list(package_data.uploads))
    state_path, state = load_publication_state(
        state_file,
        package_data=package_data,
        api_url=api_url,
        fingerprint=fingerprint,
        deposition_id=deposition_id,
    )
    plan_result = {
        "publication_capability": True,
        "deposition_id": deposition_id,
        "release_fingerprint_sha256": fingerprint,
        "license": metadata["license"],
        "file_count": len(package_data.uploads),
        "case_archive_count": len(package_data.case_archives),
        "required_confirmations": list(PUBLISH_CONFIRMATIONS),
        "required_authorization_fields": [
            "authorized_by",
            "authorized_at",
            "license",
            "release_fingerprint_sha256",
        ],
        "state_status": state["status"],
    }
    if plan:
        return {"plan": True, **plan_result}
    if authorization_file is None:
        raise DepositError("Publication requires --authorization")
    if token_file is None:
        raise DepositError(
            "Publication requires a mode-0600 --token-file with deposit:actions"
        )
    authorization = validate_publication_authorization(
        authorization_file,
        metadata=metadata,
        fingerprint=fingerprint,
        package_root=package_data.root,
        state_path=state_path,
        token_path=token_file,
    )
    with exclusive_state_lock(state_path):
        state_path, state = load_publication_state(
            state_file,
            package_data=package_data,
            api_url=api_url,
            fingerprint=fingerprint,
            deposition_id=deposition_id,
        )
        outcome = _execute_publication_locked(
            package_data=package_data,
            metadata=metadata,
            state_path=state_path,
            state=state,
            deposition_id=deposition_id,
            authorization=authorization,
            token_file=token_file,
            api_url=api_url,
            retries=retries,
            session=session,
        )
    return {
        "plan": False,
        "deposition_id": deposition_id,
        **plan_result,
        **outcome,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--deposition-id", required=True)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--api-url", default=draft.DEFAULT_API_URL)
    parser.add_argument("--retries", type=int, default=5)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--plan",
        action="store_true",
        help="Revalidate local package/state and print the authorization requirements",
    )
    action.add_argument(
        "--publish",
        action="store_true",
        help="Publish the verified draft exactly once after independent authorization",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = publish_breast_ihc(
            package_dir=args.package_dir,
            metadata_file=args.metadata,
            state_file=args.state,
            deposition_id=args.deposition_id,
            authorization_file=args.authorization,
            token_file=args.token_file,
            api_url=args.api_url,
            retries=args.retries,
            plan=args.plan,
            publish=args.publish,
        )
    except (DepositError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
