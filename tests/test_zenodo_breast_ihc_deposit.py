from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
BIN_DIR = ROOT / "bin"
sys.path.insert(0, str(BIN_DIR))
SCRIPT = BIN_DIR / "zenodo_breast_ihc_deposit.py"
SPEC = importlib.util.spec_from_file_location("zenodo_breast_ihc_deposit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
deposit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = deposit
SPEC.loader.exec_module(deposit)

package = deposit.package
base = deposit.base


def public_alias(prefix: str, index: int) -> str:
    token = base64.b32encode(
        hashlib.sha256(f"{prefix}:{index}".encode("ascii")).digest()
    ).decode("ascii")[:20]
    return f"{prefix}{token}"


def write_csv(
    path: Path,
    columns: tuple[str, ...],
    rows: list[dict[str, object]],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=columns,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_checksums(
    path: Path,
    digests: dict[str, package.FileDigest],
    algorithm: str,
) -> None:
    lines = []
    for name in sorted(digests):
        value = getattr(digests[name], algorithm)
        lines.append(f"{value}  {name}\n")
    path.write_text("".join(lines), encoding="utf-8")


@dataclass(frozen=True)
class SyntheticRelease:
    package_dir: Path
    metadata: Path
    token: Path
    state: Path


@pytest.fixture(scope="module")
def synthetic_release(tmp_path_factory: pytest.TempPathFactory) -> SyntheticRelease:
    root = tmp_path_factory.mktemp("breast-ihc-deposit")
    package_dir = root / "package"
    package_dir.mkdir()
    scratch = root / "scratch"
    scratch.mkdir()

    payload = scratch / "synthetic-patch.tif"
    payload.write_bytes(b"synthetic sanitized TIFF payload\n")
    payload_digest = package.digest_file(payload)

    case_aliases = [
        public_alias("TQA_BC_", index) for index in range(deposit.EXPECTED_CASES)
    ]
    patch_rows: list[dict[str, object]] = []
    patches_by_case: dict[str, list[tuple[str, Path, package.FileDigest]]] = (
        defaultdict(list)
    )
    provenance = "externally_verified_calibration"
    for index in range(deposit.EXPECTED_PATCHES):
        case_alias = case_aliases[index % len(case_aliases)]
        patch_alias = public_alias("TQA_PATCH_", index)
        marker = package.MARKERS[index % len(package.MARKERS)]
        public_path = (
            f"patches/{case_alias}/{patch_alias}_"
            f"{package.MARKER_FILENAME[marker]}.tif"
        )
        patch_rows.append(
            {
                "schema_version": package.SCHEMA_VERSION,
                "case_alias": case_alias,
                "patch_alias": patch_alias,
                "marker": marker,
                "public_path": public_path,
                "microns_per_pixel": "1.000000",
                "mpp_provenance": provenance,
                "width": 1,
                "height": 1,
                "channels": 3,
                "dtype": "uint8",
                "size_bytes": payload_digest.size,
                "sha256": payload_digest.sha256,
                "md5": payload_digest.md5,
                "decoded_rgb_sha256": hashlib.sha256(
                    f"decoded:{index}".encode("ascii")
                ).hexdigest(),
                "sanitization_profile": package.SANITIZATION_PROFILE,
            }
        )
        patches_by_case[case_alias].append((public_path, payload, payload_digest))
    patch_rows.sort(
        key=lambda row: (
            str(row["case_alias"]),
            package.MARKER_ORDER[str(row["marker"])],
            str(row["patch_alias"]),
        )
    )
    for members in patches_by_case.values():
        members.sort(key=lambda item: item[0])

    patch_manifest = scratch / package.PATCH_MANIFEST
    write_csv(patch_manifest, package.PATCH_COLUMNS, patch_rows)

    case_marker_counter = Counter(
        (str(row["case_alias"]), str(row["marker"])) for row in patch_rows
    )
    case_marker_rows = [
        {
            "schema_version": package.SCHEMA_VERSION,
            "case_alias": alias,
            "marker": marker,
            "patch_count": count,
        }
        for (alias, marker), count in sorted(
            case_marker_counter.items(),
            key=lambda item: (
                item[0][0],
                package.MARKER_ORDER[item[0][1]],
            ),
        )
    ]
    case_marker_counts = scratch / package.CASE_MARKER_COUNTS
    write_csv(
        case_marker_counts,
        package.CASE_MARKER_COLUMNS,
        case_marker_rows,
    )

    marker_counts = Counter(str(row["marker"]) for row in patch_rows)
    validation_payload = {
        "schema_version": package.SCHEMA_VERSION,
        "status": "passed",
        "draft_only": True,
        "network_used": False,
        "upload_performed": False,
        "publication_performed": False,
        "case_count": deposit.EXPECTED_CASES,
        "patch_count": deposit.EXPECTED_PATCHES,
        "marker_patch_counts": {
            marker: marker_counts.get(marker, 0) for marker in package.MARKERS
        },
        "mpp_provenance_counts": {provenance: deposit.EXPECTED_PATCHES},
        "estimated_decoded_pixel_bytes": deposit.EXPECTED_PATCHES * 3,
        "sanitization_profile": package.SANITIZATION_PROFILE,
        "decoded_rgb_verification": package.PREPARATION_DECODED_RGB_VERIFICATION,
        "physical_scale_verification": package.PREPARATION_PHYSICAL_SCALE_VERIFICATION,
        "tiff_metadata_policy": package.PREPARATION_TIFF_METADATA_POLICY,
        "public_tables": [package.PATCH_MANIFEST, package.CASE_MARKER_COUNTS],
        "privacy_scope": package.PREPARATION_PRIVACY_SCOPE,
    }
    validation_report = scratch / package.VALIDATION_REPORT
    validation_report.write_text(
        json.dumps(validation_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    inner_digests = {str(row["public_path"]): payload_digest for row in patch_rows}
    for path in (patch_manifest, case_marker_counts, validation_report):
        inner_digests[path.name] = package.digest_file(path)
    inner_sha = scratch / package.SOURCE_SHA256SUMS
    inner_md5 = scratch / package.SOURCE_MD5SUMS
    write_checksums(inner_sha, inner_digests, "sha256")
    write_checksums(inner_md5, inner_digests, "md5")

    archive_rows: list[dict[str, object]] = []
    archive_digests: dict[str, package.FileDigest] = {}
    for case_alias in sorted(case_aliases):
        archive_name = f"{case_alias}.zip"
        archive_path = package_dir / archive_name
        members = patches_by_case[case_alias]
        package.create_zip(archive_path, members, force_zip64=True)
        digest = package.digest_file(archive_path)
        archive_digests[archive_name] = digest
        archive_rows.append(
            {
                "schema_version": package.SCHEMA_VERSION,
                "case_alias": case_alias,
                "archive_filename": archive_name,
                "member_count": len(members),
                "uncompressed_bytes": sum(
                    item.size for _name, _source, item in members
                ),
                "archive_size_bytes": digest.size,
                "sha256": digest.sha256,
                "md5": digest.md5,
            }
        )

    archive_manifest = scratch / package.ARCHIVE_MANIFEST
    write_csv(archive_manifest, package.ARCHIVE_COLUMNS, archive_rows)
    bundle_sources = [
        patch_manifest,
        case_marker_counts,
        validation_report,
        inner_sha,
        inner_md5,
        archive_manifest,
    ]
    bundle_members = [
        (path.name, path, package.digest_file(path)) for path in bundle_sources
    ]
    bundle = package_dir / package.MANIFEST_BUNDLE
    package.create_zip(bundle, bundle_members, force_zip64=False)
    bundle_digest = package.digest_file(bundle)

    packaging_report = package_dir / package.PACKAGING_REPORT
    report_payload = {
        "schema_version": package.SCHEMA_VERSION,
        "status": "packaged",
        "draft_only": True,
        "network_used": False,
        "upload_performed": False,
        "publication_performed": False,
        "source_retained": True,
        "case_count": deposit.EXPECTED_CASES,
        "patch_count": deposit.EXPECTED_PATCHES,
        "case_archive_count": deposit.EXPECTED_CASES,
        "upload_file_count": deposit.EXPECTED_UPLOAD_FILES,
        "maximum_upload_file_count": package.MAX_ZENODO_UPLOAD_FILES,
        "source_tree_bytes": 1,
        "estimated_additional_disk_bytes": 1,
        "archive_compression": "ZIP_STORED",
        "disk_tradeoff": deposit.PACKAGING_DISK_TRADEOFF,
        "zip_member_timestamp": "1980-01-01T00:00:00",
        "case_archive_bytes": sum(item.size for item in archive_digests.values()),
        "manifest_bundle_bytes": bundle_digest.size,
        "manifest_bundle": package.MANIFEST_BUNDLE,
        "manifest_bundle_members": list(deposit.EXPECTED_BUNDLE_MEMBERS),
        "verification": deposit.PACKAGING_VERIFICATION,
        "privacy_scope": deposit.PACKAGING_PRIVACY_SCOPE,
    }
    packaging_report.write_text(
        json.dumps(report_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    outer_digests = dict(archive_digests)
    outer_digests[package.MANIFEST_BUNDLE] = bundle_digest
    outer_digests[package.PACKAGING_REPORT] = package.digest_file(packaging_report)
    write_checksums(
        package_dir / package.UPLOAD_SHA256SUMS,
        outer_digests,
        "sha256",
    )
    write_checksums(
        package_dir / package.UPLOAD_MD5SUMS,
        outer_digests,
        "md5",
    )
    assert len(list(package_dir.iterdir())) == deposit.EXPECTED_UPLOAD_FILES

    metadata = root / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "metadata": {
                    "title": "Synthetic breast IHC patches",
                    "description": "Synthetic uploader test fixture",
                    "upload_type": "dataset",
                    "access_right": "open",
                    "license": "cc-by-4.0",
                    "creators": [{"name": "Doe, Jane"}],
                    "keywords": ["synthetic", "digital pathology"],
                }
            }
        ),
        encoding="utf-8",
    )
    token = root / "zenodo-token"
    token.write_text("synthetic-deposit-write-token\n", encoding="utf-8")
    token.chmod(0o600)
    return SyntheticRelease(
        package_dir=package_dir,
        metadata=metadata,
        token=token,
        state=root / "state.json",
    )


def clone_release(
    source: SyntheticRelease,
    tmp_path: Path,
) -> SyntheticRelease:
    package_dir = tmp_path / "package"
    shutil.copytree(source.package_dir, package_dir)
    metadata = tmp_path / "metadata.json"
    shutil.copy2(source.metadata, metadata)
    token = tmp_path / "token"
    shutil.copy2(source.token, token)
    token.chmod(0o600)
    return SyntheticRelease(package_dir, metadata, token, tmp_path / "state.json")


@dataclass
class FakeZenodoServer:
    files: dict[str, tuple[int, str]] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    upload_count: int = 0
    delete_count: int = 0
    submitted: bool = False
    state: str = "unsubmitted"

    def draft(self) -> dict[str, object]:
        return {
            "id": 42,
            "submitted": self.submitted,
            "state": self.state,
            "metadata": dict(self.metadata),
            "files": [
                {
                    "filename": name,
                    "filesize": str(size),
                    "checksum": md5,
                    "links": {
                        "self": (
                            "https://zenodo.org/api/deposit/depositions/42/"
                            f"files/{name}"
                        )
                    },
                }
                for name, (size, md5) in sorted(self.files.items())
            ],
            "links": {
                "bucket": "https://zenodo.org/api/files/synthetic-bucket",
                "html": "https://zenodo.org/uploads/42",
            },
        }


def fake_client(server: FakeZenodoServer):
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def create_draft(self) -> dict[str, object]:
            server.calls.append(("POST", "create"))
            return server.draft()

        def get_draft(self, _deposition_id: str) -> dict[str, object]:
            server.calls.append(("GET", "draft"))
            return server.draft()

        def update_metadata(
            self,
            _deposition_id: str,
            metadata: dict[str, object],
        ) -> dict[str, object]:
            server.calls.append(("PUT", "metadata"))
            server.metadata = dict(metadata)
            return server.draft()

        def upload_file(
            self,
            _bucket_url: str,
            upload: base.UploadFile,
        ) -> dict[str, object]:
            server.calls.append(("PUT", upload.remote_name))
            server.upload_count += 1
            server.files[upload.remote_name] = (
                upload.size_bytes,
                upload.md5,
            )
            return {
                "key": upload.remote_name,
                "size": upload.size_bytes,
                "checksum": f"md5:{upload.md5}",
            }

        def delete_file(self, url: str) -> None:
            server.calls.append(("DELETE", url))
            server.delete_count += 1
            name = url.rsplit("/", 1)[-1]
            server.files.pop(name, None)

    return FakeClient


def run_deposit(
    release: SyntheticRelease,
    monkeypatch: pytest.MonkeyPatch,
    server: FakeZenodoServer,
    **overrides: object,
) -> dict[str, object]:
    monkeypatch.setattr(deposit, "HardenedZenodoClient", fake_client(server))
    arguments: dict[str, object] = {
        "package_dir": release.package_dir,
        "metadata_file": release.metadata,
        "state_file": release.state,
        "token_file": release.token,
    }
    arguments.update(overrides)
    return deposit.deposit_breast_ihc(**arguments)


def test_plan_fully_validates_exact_fixed_release_without_token_or_state(
    synthetic_release: SyntheticRelease,
) -> None:
    result = deposit.deposit_breast_ihc(
        package_dir=synthetic_release.package_dir,
        metadata_file=synthetic_release.metadata,
        state_file=synthetic_release.state,
        plan=True,
    )
    assert result["plan"] is True
    assert result["draft_only"] is True
    assert result["publication_capability"] is False
    assert result["file_count"] == 55
    assert result["case_archive_count"] == 51
    assert result["patch_count"] == 1901
    assert len(result["files"]) == 55
    assert not synthetic_release.state.exists()


@pytest.mark.parametrize("mutation", ["missing", "extra", "directory", "symlink"])
def test_rejects_every_nonexact_or_nonregular_package_entry(
    synthetic_release: SyntheticRelease,
    tmp_path: Path,
    mutation: str,
) -> None:
    release = clone_release(synthetic_release, tmp_path)
    if mutation == "missing":
        (release.package_dir / package.PACKAGING_REPORT).unlink()
    elif mutation == "extra":
        (release.package_dir / "supplement.txt").write_text(
            "not part of the fixed release\n",
            encoding="utf-8",
        )
    elif mutation == "directory":
        (release.package_dir / "unexpected-directory").mkdir()
    else:
        (release.package_dir / "unexpected-link").symlink_to(
            release.package_dir / package.PACKAGING_REPORT
        )
    with pytest.raises(deposit.DepositError):
        deposit.deposit_breast_ihc(
            package_dir=release.package_dir,
            metadata_file=release.metadata,
            state_file=release.state,
            plan=True,
        )


def test_uploads_exact_draft_and_resumes_without_reupload(
    synthetic_release: SyntheticRelease,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = clone_release(synthetic_release, tmp_path)
    server = FakeZenodoServer()
    first = run_deposit(release, monkeypatch, server)
    assert first["status"] == "open-access-unpublished-draft"
    assert first["remote_file_count"] == 55
    assert server.upload_count == 55
    assert set(server.files) == {item["name"] for item in first["files"]}
    state_text = release.state.read_text(encoding="utf-8")
    assert "synthetic-deposit-write-token" not in state_text
    assert stat.S_IMODE(release.state.stat().st_mode) == 0o600

    second = run_deposit(release, monkeypatch, server)
    assert second["remote_file_count"] == 55
    assert server.upload_count == 55


def test_rejects_unexpected_remote_file_before_upload(
    synthetic_release: SyntheticRelease,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = clone_release(synthetic_release, tmp_path)
    server = FakeZenodoServer(
        files={
            "unreviewed-extra.txt": (
                1,
                hashlib.md5(b"x", usedforsecurity=False).hexdigest(),
            )
        }
    )
    with pytest.raises(deposit.DepositError, match="unreviewed extra"):
        run_deposit(release, monkeypatch, server)
    assert server.upload_count == 0
    assert server.delete_count == 0


def test_rejects_noneditable_draft_before_metadata_mutation(
    synthetic_release: SyntheticRelease,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = clone_release(synthetic_release, tmp_path)
    server = FakeZenodoServer(state="error")
    with pytest.raises(deposit.DepositError, match="not editable"):
        run_deposit(release, monkeypatch, server)
    assert ("POST", "create") in server.calls
    assert ("PUT", "metadata") not in server.calls
    assert server.upload_count == 0
    assert server.delete_count == 0


def test_mismatch_requires_opt_in_and_replacement_is_verified(
    synthetic_release: SyntheticRelease,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = clone_release(synthetic_release, tmp_path)
    validated = deposit.validate_package_directory(release.package_dir)
    target = validated.uploads[0]
    server = FakeZenodoServer(files={target.remote_name: (target.size_bytes, "0" * 32)})
    with pytest.raises(deposit.DepositError, match="replace-mismatched"):
        run_deposit(release, monkeypatch, server)
    assert server.delete_count == 0
    assert server.upload_count == 0

    result = run_deposit(
        release,
        monkeypatch,
        server,
        replace_mismatched=True,
    )
    assert result["remote_file_count"] == 55
    assert server.delete_count == 1
    assert server.upload_count == 55
    assert server.files[target.remote_name] == (target.size_bytes, target.md5)


def test_replacement_preflights_all_local_files_before_delete(
    synthetic_release: SyntheticRelease,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = clone_release(synthetic_release, tmp_path)
    validated = deposit.validate_package_directory(release.package_dir)
    target = validated.uploads[0]
    server = FakeZenodoServer(files={target.remote_name: (target.size_bytes, "0" * 32)})
    observed = 0
    real_verify = base.verify_local

    def fail_second(upload: base.UploadFile) -> None:
        nonlocal observed
        observed += 1
        if observed == 2:
            raise deposit.DepositError("synthetic later local failure")
        real_verify(upload)

    monkeypatch.setattr(base, "verify_local", fail_second)
    with pytest.raises(deposit.DepositError, match="later local failure"):
        run_deposit(
            release,
            monkeypatch,
            server,
            replace_mismatched=True,
        )
    assert server.delete_count == 0
    assert server.upload_count == 0


def test_private_token_and_state_modes_are_enforced(
    synthetic_release: SyntheticRelease,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = clone_release(synthetic_release, tmp_path)
    release.token.chmod(0o644)
    with pytest.raises(deposit.DepositError, match="exact mode 0600"):
        run_deposit(release, monkeypatch, FakeZenodoServer())

    release.token.chmod(0o600)
    server = FakeZenodoServer()
    run_deposit(release, monkeypatch, server, create_only=True)
    release.state.chmod(0o644)
    with pytest.raises(deposit.DepositError, match="exact mode 0600"):
        run_deposit(release, monkeypatch, server, create_only=True)


def test_state_fingerprint_rejects_metadata_change(
    synthetic_release: SyntheticRelease,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = clone_release(synthetic_release, tmp_path)
    server = FakeZenodoServer()
    run_deposit(release, monkeypatch, server, create_only=True)
    payload = json.loads(release.metadata.read_text(encoding="utf-8"))
    payload["metadata"]["title"] = "Changed after draft creation"
    release.metadata.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(deposit.DepositError, match="exact release"):
        run_deposit(release, monkeypatch, server, create_only=True)


def test_quota_requires_create_only_then_explicit_confirmation(
    synthetic_release: SyntheticRelease,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = clone_release(synthetic_release, tmp_path)
    monkeypatch.setattr(deposit, "ZENODO_DEFAULT_QUOTA_BYTES", 1)
    plan = deposit.deposit_breast_ihc(
        package_dir=release.package_dir,
        metadata_file=release.metadata,
        state_file=release.state,
        plan=True,
    )
    assert plan["requires_additional_quota"] is True
    server = FakeZenodoServer()
    with pytest.raises(deposit.DepositError, match="exceeds the default quota"):
        run_deposit(release, monkeypatch, server)

    created = run_deposit(
        release,
        monkeypatch,
        server,
        create_only=True,
    )
    assert created["create_only"] is True
    assert created["remote_file_count"] == 0
    assert server.upload_count == 0

    uploaded = run_deposit(
        release,
        monkeypatch,
        server,
        confirmed_quota_bytes=int(plan["total_size_bytes"]),
    )
    assert uploaded["remote_file_count"] == 55


def test_remote_file_id_provides_safe_legacy_delete_fallback() -> None:
    checksum = hashlib.md5(b"x", usedforsecurity=False).hexdigest()
    files = deposit.strict_remote_files(
        {
            "files": [
                {
                    "id": "12345678-abcd-1234-abcd-123456789abc",
                    "filename": "safe.zip",
                    "filesize": 1,
                    "checksum": f"md5:{checksum}",
                    "links": {},
                }
            ]
        },
        api_url="https://zenodo.org/api",
        deposition_id="42",
    )
    assert files["safe.zip"].delete_url == (
        "https://zenodo.org/api/deposit/depositions/42/files/"
        "12345678-abcd-1234-abcd-123456789abc"
    )


def test_parser_exposes_no_publish_or_extra_file_surface() -> None:
    parser = deposit.build_parser()
    options = {option for action in parser._actions for option in action.option_strings}
    assert "--publish" not in options
    assert "--authorization" not in options
    assert "--extra-file" not in options
    assert "--supplement" not in options


def test_local_metadata_is_canonicalized_before_fingerprinting(
    tmp_path: Path,
) -> None:
    path = tmp_path / "metadata.json"
    path.write_text(
        json.dumps(
            {
                "title": "Canonical fixture",
                "description": "Synthetic only",
                "upload_type": "DATASET",
                "access_right": "OPEN",
                "license": "CC-BY",
                "creators": [{"name": "Doe, Jane"}],
                "language": "ENG",
                "publication_date": "2026-08-04",
                "related_identifiers": [
                    {
                        "identifier": "https://doi.org/10.5281/zenodo.12345",
                        "relation": "issupplementto",
                        "scheme": "DOI",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    metadata = deposit.public_metadata_from_file(path)
    assert metadata["upload_type"] == "dataset"
    assert metadata["access_right"] == "open"
    assert metadata["license"] == "cc-by-4.0"
    assert metadata["language"] == "eng"
    assert metadata["related_identifiers"] == [
        {
            "identifier": "10.5281/zenodo.12345",
            "relation": "isSupplementTo",
            "scheme": "doi",
        }
    ]
    invalid = json.loads(path.read_text(encoding="utf-8"))
    invalid["publication_date"] = "2026-02-31"
    path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(deposit.DepositError, match="valid YYYY-MM-DD"):
        deposit.public_metadata_from_file(path)


def test_current_zenodo_metadata_normalization_is_accepted() -> None:
    expected = {
        "title": "H&E patches",
        "description": "H&E synthetic fixture",
        "upload_type": "dataset",
        "access_right": "open",
        "license": "cc0-1.0",
        "creators": [{"name": "Doe, Jane"}],
        "related_identifiers": [
            {
                "identifier": "10.5281/zenodo.12345",
                "relation": "isSupplementTo",
                "scheme": "doi",
            }
        ],
    }
    actual = dict(expected)
    actual["title"] = "H&amp;E patches"
    actual["description"] = "H&amp;E synthetic fixture"
    actual["license"] = "cc-zero"
    actual["creators"] = [{"name": "Doe, Jane", "affiliation": None}]
    actual["related_identifiers"] = [
        {
            "identifier": "https://doi.org/10.5281/zenodo.12345",
            "relation": "issupplementto",
            "scheme": "DOI",
            "server_default": "ignored",
        }
    ]
    deposit.validate_open_unpublished_draft(
        {
            "submitted": False,
            "state": "unsubmitted",
            "metadata": actual,
        },
        expected,
    )
