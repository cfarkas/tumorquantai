from __future__ import annotations

import copy
import hashlib
import json
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
BIN_DIR = ROOT / "bin"
TEST_DIR = ROOT / "tests"
sys.path.insert(0, str(BIN_DIR))
sys.path.insert(0, str(TEST_DIR))

import test_zenodo_breast_ihc_deposit as deposit_helpers  # noqa: E402
import zenodo_breast_ihc_publish as publish  # noqa: E402


base = publish.base
draft = publish.draft


@pytest.fixture(scope="module")
def publication_release(
    tmp_path_factory: pytest.TempPathFactory,
) -> deposit_helpers.SyntheticRelease:
    return deposit_helpers.synthetic_release.__wrapped__(tmp_path_factory)


@pytest.fixture(scope="module")
def package_data(
    publication_release: deposit_helpers.SyntheticRelease,
) -> draft.ValidatedPackage:
    return draft.validate_package_directory(publication_release.package_dir)


def metadata_for(
    release: deposit_helpers.SyntheticRelease,
) -> dict[str, object]:
    return draft.public_metadata_from_file(release.metadata)


def release_fingerprint(
    release: deposit_helpers.SyntheticRelease,
    package_data: draft.ValidatedPackage,
) -> str:
    return base.release_fingerprint(
        metadata_for(release),
        list(package_data.uploads),
    )


def write_private_json(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def authorization_payload(
    metadata: dict[str, object],
    fingerprint: str,
) -> dict[str, object]:
    return {
        **{key: True for key in publish.PUBLISH_CONFIRMATIONS},
        "authorized_by": "Synthetic Release Approver",
        "authorized_at": "2026-08-04T16:00:00Z",
        "license": metadata["license"],
        "release_fingerprint_sha256": fingerprint,
    }


def exact_uploaded_state(
    package_data: draft.ValidatedPackage,
) -> dict[str, dict[str, object]]:
    return {
        upload.remote_name: {
            "size_bytes": upload.size_bytes,
            "md5": upload.md5,
            "status": "verified-existing",
        }
        for upload in package_data.uploads
    }


def draft_state_payload(
    package_data: draft.ValidatedPackage,
    fingerprint: str,
    *,
    deposition_id: str = "42",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "dataset_format": draft.DATASET_FORMAT,
        "api_url": draft.DEFAULT_API_URL,
        "deposition_id": deposition_id,
        "release_fingerprint_sha256": fingerprint,
        "file_count": draft.EXPECTED_UPLOAD_FILES,
        "total_size_bytes": package_data.total_size_bytes,
        "status": "draft",
        "uploaded": exact_uploaded_state(package_data),
    }


def publication_inputs(
    tmp_path: Path,
    release: deposit_helpers.SyntheticRelease,
    package_data: draft.ValidatedPackage,
) -> tuple[Path, Path, str, dict[str, object]]:
    metadata = metadata_for(release)
    fingerprint = release_fingerprint(release, package_data)
    state_path = write_private_json(
        tmp_path / "deposit-state.json",
        draft_state_payload(package_data, fingerprint),
    )
    authorization = write_private_json(
        tmp_path / "publication-authorization.json",
        authorization_payload(metadata, fingerprint),
    )
    return state_path, authorization, fingerprint, metadata


def remote_files(
    package_data: draft.ValidatedPackage,
) -> list[dict[str, object]]:
    return [
        {
            "filename": upload.remote_name,
            "filesize": upload.size_bytes,
            "checksum": f"md5:{upload.md5}",
        }
        for upload in package_data.uploads
    ]


@dataclass
class FakePublicationServer:
    package_data: draft.ValidatedPackage
    metadata: dict[str, object]
    published: bool = False
    malformed_publish_response: bool = False
    remote_mutation: str | None = None
    record_id: str = "314159"
    calls: list[tuple[str, str]] = field(default_factory=list)
    publish_count: int = 0

    def files(self) -> list[dict[str, object]]:
        files = remote_files(self.package_data)
        if self.remote_mutation == "extra":
            files.append(
                {
                    "filename": "unreviewed-extra.txt",
                    "filesize": 1,
                    "checksum": "md5:"
                    + hashlib.md5(b"x", usedforsecurity=False).hexdigest(),
                }
            )
        elif self.remote_mutation == "mismatch":
            files[0] = dict(files[0], checksum="md5:" + "0" * 32)
        return files

    def deposition(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": 42,
            "submitted": self.published,
            "state": "done" if self.published else "unsubmitted",
            "metadata": copy.deepcopy(self.metadata),
            "files": self.files(),
        }
        if self.published:
            payload["record_id"] = int(self.record_id)
        return payload

    def record(self) -> dict[str, object]:
        doi = f"10.5281/zenodo.{self.record_id}"
        record_metadata = copy.deepcopy(self.metadata)
        upload_type = record_metadata.pop("upload_type")
        record_metadata["resource_type"] = {
            "type": upload_type,
            "title": "Dataset",
        }
        record_metadata["license"] = {"id": record_metadata["license"]}
        return {
            "id": int(self.record_id),
            "doi": doi,
            "metadata": record_metadata,
            "files": self.files(),
            "links": {
                "self_html": f"https://zenodo.org/records/{self.record_id}",
                "doi": f"https://doi.org/{doi}",
            },
        }


def fake_publish_client(server: FakePublicationServer):
    class FakePublishClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def get_draft(self, deposition_id: str) -> dict[str, object]:
            assert deposition_id == "42"
            server.calls.append(("GET", "deposition"))
            return server.deposition()

        def publish_once(self, deposition_id: str) -> dict[str, object]:
            assert deposition_id == "42"
            server.calls.append(("POST", "publish"))
            server.publish_count += 1
            server.published = True
            if server.malformed_publish_response:
                return {"id": 42, "submitted": False}
            return server.deposition()

        def get_public_record(self, record_id: str) -> dict[str, object]:
            assert record_id == server.record_id
            server.calls.append(("GET", "record"))
            return server.record()

    return FakePublishClient


def json_response(status: int, payload: dict[str, object]):
    response = base.requests.Response()
    response.status_code = status
    response.url = "https://zenodo.org/api/test"
    response._content = json.dumps(payload).encode("utf-8")
    response._content_consumed = True
    return response


def run_publication(
    release: deposit_helpers.SyntheticRelease,
    state_path: Path,
    authorization: Path,
    monkeypatch: pytest.MonkeyPatch,
    server: FakePublicationServer,
    package_data: draft.ValidatedPackage,
) -> dict[str, object]:
    monkeypatch.setattr(
        draft,
        "validate_package_directory",
        lambda _path: package_data,
    )
    monkeypatch.setattr(
        publish,
        "PublishZenodoClient",
        fake_publish_client(server),
    )
    return publish.publish_breast_ihc(
        package_dir=release.package_dir,
        metadata_file=release.metadata,
        state_file=state_path,
        deposition_id="42",
        authorization_file=authorization,
        token_file=release.token,
        publish=True,
    )


def test_plan_revalidates_local_release_and_exact_full_draft_state(
    publication_release: deposit_helpers.SyntheticRelease,
    package_data: draft.ValidatedPackage,
    tmp_path: Path,
) -> None:
    state_path, _authorization, fingerprint, metadata = publication_inputs(
        tmp_path,
        publication_release,
        package_data,
    )
    state_before = state_path.read_bytes()
    result = publish.publish_breast_ihc(
        package_dir=publication_release.package_dir,
        metadata_file=publication_release.metadata,
        state_file=state_path,
        deposition_id="42",
        plan=True,
    )
    assert result == {
        "plan": True,
        "publication_capability": True,
        "deposition_id": "42",
        "release_fingerprint_sha256": fingerprint,
        "license": metadata["license"],
        "file_count": 55,
        "case_archive_count": 51,
        "required_confirmations": list(publish.PUBLISH_CONFIRMATIONS),
        "required_authorization_fields": [
            "authorized_by",
            "authorized_at",
            "license",
            "release_fingerprint_sha256",
        ],
        "state_status": "draft",
    }
    assert state_path.read_bytes() == state_before


def test_exact_authorization_is_mode_and_release_bound(
    publication_release: deposit_helpers.SyntheticRelease,
    package_data: draft.ValidatedPackage,
    tmp_path: Path,
) -> None:
    metadata = metadata_for(publication_release)
    fingerprint = release_fingerprint(publication_release, package_data)
    payload = authorization_payload(metadata, fingerprint)
    path = write_private_json(tmp_path / "authorization.json", payload)
    result = publish.validate_publication_authorization(
        path,
        metadata=metadata,
        fingerprint=fingerprint,
        package_root=package_data.root,
        state_path=tmp_path / "state.json",
        token_path=publication_release.token,
    )
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert result.payload == payload
    assert result.proof == {
        "authorization_sha256": hashlib.sha256(canonical).hexdigest(),
        "authorized_by": "Synthetic Release Approver",
        "authorized_at": "2026-08-04T16:00:00+00:00",
        "license": metadata["license"],
        "release_fingerprint_sha256": fingerprint,
    }
    path.chmod(0o644)
    with pytest.raises(publish.DepositError, match="exact mode 0600"):
        publish.validate_publication_authorization(
            path,
            metadata=metadata,
            fingerprint=fingerprint,
            package_root=package_data.root,
            state_path=tmp_path / "state.json",
            token_path=publication_release.token,
        )


@pytest.mark.parametrize("confirmation", publish.PUBLISH_CONFIRMATIONS)
def test_authorization_requires_each_of_the_seven_true_confirmations(
    publication_release: deposit_helpers.SyntheticRelease,
    package_data: draft.ValidatedPackage,
    tmp_path: Path,
    confirmation: str,
) -> None:
    metadata = metadata_for(publication_release)
    fingerprint = release_fingerprint(publication_release, package_data)
    payload = authorization_payload(metadata, fingerprint)
    payload[confirmation] = False
    path = write_private_json(tmp_path / f"authorization-{confirmation}.json", payload)
    with pytest.raises(publish.DepositError, match=confirmation):
        publish.validate_publication_authorization(
            path,
            metadata=metadata,
            fingerprint=fingerprint,
            package_root=package_data.root,
            state_path=tmp_path / "state.json",
            token_path=publication_release.token,
        )


@pytest.mark.parametrize(
    ("field", "invalid", "message"),
    [
        ("license", "cc0-1.0", "Authorized license"),
        ("release_fingerprint_sha256", "0" * 64, "exact release"),
    ],
)
def test_authorization_rejects_license_or_fingerprint_drift(
    publication_release: deposit_helpers.SyntheticRelease,
    package_data: draft.ValidatedPackage,
    tmp_path: Path,
    field: str,
    invalid: str,
    message: str,
) -> None:
    metadata = metadata_for(publication_release)
    fingerprint = release_fingerprint(publication_release, package_data)
    payload = authorization_payload(metadata, fingerprint)
    payload[field] = invalid
    path = write_private_json(tmp_path / f"bad-{field}.json", payload)
    with pytest.raises(publish.DepositError, match=message):
        publish.validate_publication_authorization(
            path,
            metadata=metadata,
            fingerprint=fingerprint,
            package_root=package_data.root,
            state_path=tmp_path / "state.json",
            token_path=publication_release.token,
        )


def test_state_requires_exact_full_roster_mode_and_release_binding(
    publication_release: deposit_helpers.SyntheticRelease,
    package_data: draft.ValidatedPackage,
    tmp_path: Path,
) -> None:
    fingerprint = release_fingerprint(publication_release, package_data)
    payload = draft_state_payload(package_data, fingerprint)
    path = write_private_json(tmp_path / "state.json", payload)
    resolved, loaded = publish.load_publication_state(
        path,
        package_data=package_data,
        api_url=draft.DEFAULT_API_URL,
        fingerprint=fingerprint,
        deposition_id="42",
    )
    assert resolved == path.resolve()
    assert loaded == payload
    assert len(loaded["uploaded"]) == 55

    missing = copy.deepcopy(payload)
    missing["uploaded"].pop(next(iter(missing["uploaded"])))
    write_private_json(path, missing)
    with pytest.raises(publish.DepositError, match="all exact 55"):
        publish.load_publication_state(
            path,
            package_data=package_data,
            api_url=draft.DEFAULT_API_URL,
            fingerprint=fingerprint,
            deposition_id="42",
        )

    drifted = copy.deepcopy(payload)
    drifted["release_fingerprint_sha256"] = "0" * 64
    write_private_json(path, drifted)
    with pytest.raises(publish.DepositError, match="not bound"):
        publish.load_publication_state(
            path,
            package_data=package_data,
            api_url=draft.DEFAULT_API_URL,
            fingerprint=fingerprint,
            deposition_id="42",
        )

    write_private_json(path, payload).chmod(0o644)
    with pytest.raises(publish.DepositError, match="exact mode 0600"):
        publish.load_publication_state(
            path,
            package_data=package_data,
            api_url=draft.DEFAULT_API_URL,
            fingerprint=fingerprint,
            deposition_id="42",
        )


def test_success_posts_once_then_verifies_deposition_and_public_record(
    publication_release: deposit_helpers.SyntheticRelease,
    package_data: draft.ValidatedPackage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path, authorization, fingerprint, metadata = publication_inputs(
        tmp_path,
        publication_release,
        package_data,
    )
    server = FakePublicationServer(package_data, metadata)
    result = run_publication(
        publication_release,
        state_path,
        authorization,
        monkeypatch,
        server,
        package_data,
    )
    assert result["status"] == "published"
    assert result["record_id"] == server.record_id
    assert result["record_url"] == (f"https://zenodo.org/records/{server.record_id}")
    assert result["doi"] == f"10.5281/zenodo.{server.record_id}"
    assert result["doi_url"] == (f"https://doi.org/10.5281/zenodo.{server.record_id}")
    assert result["release_fingerprint_sha256"] == fingerprint
    assert server.publish_count == 1
    assert server.calls == [
        ("GET", "deposition"),
        ("POST", "publish"),
        ("GET", "deposition"),
        ("GET", "record"),
    ]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "published"
    assert state["record_id"] == server.record_id
    assert state["doi"] == f"10.5281/zenodo.{server.record_id}"
    assert state["record_url"] == f"https://zenodo.org/records/{server.record_id}"
    assert state["publication"]["release_fingerprint_sha256"] == fingerprint
    assert "published_at" in state
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("legacy_upload_type", "legacy_license"),
    [(True, False), (False, True), (True, True)],
)
def test_public_record_accepts_legacy_and_mixed_metadata_representations(
    publication_release: deposit_helpers.SyntheticRelease,
    package_data: draft.ValidatedPackage,
    legacy_upload_type: bool,
    legacy_license: bool,
) -> None:
    metadata = metadata_for(publication_release)
    server = FakePublicationServer(package_data, metadata, published=True)
    payload = server.record()
    record_metadata = payload["metadata"]
    assert isinstance(record_metadata, dict)
    if legacy_upload_type:
        resource_type = record_metadata.pop("resource_type")
        assert isinstance(resource_type, dict)
        record_metadata["upload_type"] = resource_type["type"]
    if legacy_license:
        observed_license = record_metadata["license"]
        assert isinstance(observed_license, dict)
        record_metadata["license"] = observed_license["id"]
    result = publish.validate_published_record(
        payload,
        record_id=server.record_id,
        api_url=draft.DEFAULT_API_URL,
        metadata=metadata,
        uploads=package_data.uploads,
    )
    assert result.doi == f"10.5281/zenodo.{server.record_id}"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "no valid resource type"),
        ("scalar", "no valid resource type"),
        ("no-discriminator", "no valid resource type"),
        ("empty", "no valid resource type"),
        ("wrong", "requested upload_type"),
        ("disagreeing", "ambiguous resource types"),
        ("both-schemas", "ambiguous upload/resource types"),
    ],
)
def test_public_record_rejects_wrong_missing_or_ambiguous_resource_type(
    publication_release: deposit_helpers.SyntheticRelease,
    package_data: draft.ValidatedPackage,
    mutation: str,
    message: str,
) -> None:
    metadata = metadata_for(publication_release)
    server = FakePublicationServer(package_data, metadata, published=True)
    payload = server.record()
    record_metadata = payload["metadata"]
    assert isinstance(record_metadata, dict)
    if mutation == "missing":
        record_metadata.pop("resource_type")
    elif mutation == "scalar":
        record_metadata["resource_type"] = "dataset"
    elif mutation == "no-discriminator":
        record_metadata["resource_type"] = {"title": "Dataset"}
    elif mutation == "empty":
        record_metadata["resource_type"] = {"type": ""}
    elif mutation == "wrong":
        record_metadata["resource_type"] = {
            "type": "software",
            "title": "Software",
        }
    elif mutation == "disagreeing":
        record_metadata["resource_type"] = {
            "type": "dataset",
            "id": "software",
            "title": "Dataset",
        }
    else:
        record_metadata["upload_type"] = "dataset"
    with pytest.raises(publish.DepositError, match=message):
        publish.validate_published_record(
            payload,
            record_id=server.record_id,
            api_url=draft.DEFAULT_API_URL,
            metadata=metadata,
            uploads=package_data.uploads,
        )


@pytest.mark.parametrize(
    ("observed_license", "message"),
    [
        ({}, "no valid license ID"),
        ({"id": None}, "no valid license ID"),
        ({"id": ""}, "no valid license ID"),
        ({"id": "cc0-1.0"}, "requested license"),
    ],
)
def test_public_record_rejects_malformed_or_wrong_license_dict(
    publication_release: deposit_helpers.SyntheticRelease,
    package_data: draft.ValidatedPackage,
    observed_license: dict[str, object],
    message: str,
) -> None:
    metadata = metadata_for(publication_release)
    server = FakePublicationServer(package_data, metadata, published=True)
    payload = server.record()
    record_metadata = payload["metadata"]
    assert isinstance(record_metadata, dict)
    record_metadata["license"] = observed_license
    with pytest.raises(publish.DepositError, match=message):
        publish.validate_published_record(
            payload,
            record_id=server.record_id,
            api_url=draft.DEFAULT_API_URL,
            metadata=metadata,
            uploads=package_data.uploads,
        )


def test_public_record_accepts_legacy_html_link(
    publication_release: deposit_helpers.SyntheticRelease,
    package_data: draft.ValidatedPackage,
) -> None:
    metadata = metadata_for(publication_release)
    server = FakePublicationServer(package_data, metadata, published=True)
    payload = server.record()
    links = payload["links"]
    assert isinstance(links, dict)
    links["html"] = links.pop("self_html")
    result = publish.validate_published_record(
        payload,
        record_id=server.record_id,
        api_url=draft.DEFAULT_API_URL,
        metadata=metadata,
        uploads=package_data.uploads,
    )
    assert result.record_url == f"https://zenodo.org/records/{server.record_id}"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "no public record URL"),
        ("wrong-type", "no public record URL"),
        ("conflicting", "conflicting public URLs"),
    ],
)
def test_public_record_rejects_invalid_or_conflicting_html_links(
    publication_release: deposit_helpers.SyntheticRelease,
    package_data: draft.ValidatedPackage,
    mutation: str,
    message: str,
) -> None:
    metadata = metadata_for(publication_release)
    server = FakePublicationServer(package_data, metadata, published=True)
    payload = server.record()
    links = payload["links"]
    assert isinstance(links, dict)
    if mutation == "missing":
        links.pop("self_html")
    elif mutation == "wrong-type":
        links["self_html"] = 123
    else:
        links["html"] = "https://zenodo.org/records/999999"
    with pytest.raises(publish.DepositError, match=message):
        publish.validate_published_record(
            payload,
            record_id=server.record_id,
            api_url=draft.DEFAULT_API_URL,
            metadata=metadata,
            uploads=package_data.uploads,
        )


@pytest.mark.parametrize("remote_mutation", ["extra", "mismatch"])
def test_remote_extra_or_mismatch_blocks_publish_and_preserves_draft(
    publication_release: deposit_helpers.SyntheticRelease,
    package_data: draft.ValidatedPackage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    remote_mutation: str,
) -> None:
    state_path, authorization, _fingerprint, metadata = publication_inputs(
        tmp_path,
        publication_release,
        package_data,
    )
    server = FakePublicationServer(
        package_data,
        metadata,
        remote_mutation=remote_mutation,
    )
    with pytest.raises(publish.DepositError):
        run_publication(
            publication_release,
            state_path,
            authorization,
            monkeypatch,
            server,
            package_data,
        )
    assert server.publish_count == 0
    assert server.calls == [("GET", "deposition")]
    assert json.loads(state_path.read_text(encoding="utf-8"))["status"] == "draft"


def test_failed_publish_response_leaves_transition_and_rerun_never_posts_again(
    publication_release: deposit_helpers.SyntheticRelease,
    package_data: draft.ValidatedPackage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path, authorization, _fingerprint, metadata = publication_inputs(
        tmp_path,
        publication_release,
        package_data,
    )
    server = FakePublicationServer(
        package_data,
        metadata,
        malformed_publish_response=True,
    )
    with pytest.raises(publish.DepositError, match="not confirmed published"):
        run_publication(
            publication_release,
            state_path,
            authorization,
            monkeypatch,
            server,
            package_data,
        )
    transition = json.loads(state_path.read_text(encoding="utf-8"))
    assert transition["status"] == "publish-intent"
    assert "publication" in transition
    assert server.publish_count == 1

    server.malformed_publish_response = False
    result = run_publication(
        publication_release,
        state_path,
        authorization,
        monkeypatch,
        server,
        package_data,
    )
    assert result["status"] == "published"
    assert server.publish_count == 1
    assert server.calls.count(("POST", "publish")) == 1
    assert server.calls[-2:] == [("GET", "deposition"), ("GET", "record")]


def test_official_publish_action_requires_202_and_disables_retries() -> None:
    class RetryableFailureSession:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict[str, object]]] = []

        def request(self, method: str, url: str, **kwargs: object):
            self.calls.append((method, url, kwargs))
            return json_response(503, {"message": "synthetic transient failure"})

    session = RetryableFailureSession()
    client = publish.PublishZenodoClient(
        "synthetic-secret",
        draft.DEFAULT_API_URL,
        retries=9,
        session=session,
    )
    with pytest.raises(publish.DepositError, match="after 1 attempts"):
        client.publish_once("42")
    assert len(session.calls) == 1
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "https://zenodo.org/api/deposit/depositions/42/actions/publish"
    assert kwargs["headers"]["Authorization"] == "Bearer synthetic-secret"
    assert "synthetic-secret" not in url


def test_public_record_verification_is_anonymous() -> None:
    class PublicRecordSession:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict[str, object]]] = []

        def request(self, method: str, url: str, **kwargs: object):
            self.calls.append((method, url, kwargs))
            return json_response(200, {"id": 314159})

    session = PublicRecordSession()
    client = publish.PublishZenodoClient(
        "synthetic-secret",
        draft.DEFAULT_API_URL,
        session=session,
    )
    assert client.get_public_record("314159") == {"id": 314159}
    assert len(session.calls) == 1
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == "https://zenodo.org/api/records/314159"
    assert kwargs["headers"] == {"Accept": "application/json"}
    assert "synthetic-secret" not in url


def test_publish_parser_is_separate_and_exposes_no_draft_mutation_surface() -> None:
    parser = publish.build_parser()
    options = {option for action in parser._actions for option in action.option_strings}
    assert {
        "--package-dir",
        "--metadata",
        "--state",
        "--deposition-id",
        "--authorization",
        "--token-file",
        "--plan",
        "--publish",
    }.issubset(options)
    assert {
        "--create-only",
        "--replace-mismatched",
        "--confirmed-quota-bytes",
        "--extra-file",
        "--supplement",
        "--title",
        "--description",
        "--license",
    }.isdisjoint(options)
    assert publish.build_parser is not draft.build_parser
