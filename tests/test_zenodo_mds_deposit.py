from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


BIN_DIR = Path(__file__).parents[1] / "bin"
sys.path.insert(0, str(BIN_DIR))
MODULE_PATH = BIN_DIR / "zenodo_mds_deposit.py"
SPEC = importlib.util.spec_from_file_location("zenodo_mds_deposit", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def manifests(tmp_path: Path) -> tuple[Path, Path, Path]:
    slide = tmp_path / "TumorQuantAI_LymphomaWSI_001.mds"
    payload = b"sanitized mds fixture"
    slide.write_bytes(payload)
    sha256 = hashlib.sha256(payload).hexdigest()
    md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
    public = tmp_path / module.DEFAULT_MANIFEST_NAME
    columns = (
        "schema_version",
        "alias",
        "zenodo_filename",
        "size_bytes",
        "sha256",
        "md5",
        "source_mpp",
        "level_count",
        "level_dimensions",
        "pixel_stream_count",
        "pixel_sample_sha256",
        "pixel_full_sha256",
        "sanitization_profile",
    )
    with public.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow(
            {
                "schema_version": "2",
                "alias": "TumorQuantAI_LymphomaWSI_001",
                "zenodo_filename": slide.name,
                "size_bytes": len(payload),
                "sha256": sha256,
                "md5": md5,
                "source_mpp": "0.26178",
                "level_count": "3",
                "level_dimensions": "[[100,100],[50,50],[25,25]]",
                "pixel_stream_count": "10",
                "pixel_sample_sha256": "a" * 64,
                "pixel_full_sha256": "b" * 64,
                "sanitization_profile": (
                    "pixel-preserving-nonpixel-redaction-v2"
                ),
            }
        )
    private = tmp_path / "private.csv"
    with private.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "alias",
                "staged_path",
                "sanitized_sha256",
                "sanitized_md5",
                "pixel_stream_count",
                "pixel_sample_sha256",
                "pixel_full_sha256",
                "source_markers_absent",
                "validation_status",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "alias": "TumorQuantAI_LymphomaWSI_001",
                "staged_path": slide,
                "sanitized_sha256": sha256,
                "sanitized_md5": md5,
                "pixel_stream_count": "10",
                "pixel_sample_sha256": "a" * 64,
                "pixel_full_sha256": "b" * 64,
                "source_markers_absent": "True",
                "validation_status": "validated-copy",
            }
        )
    os.chmod(private, 0o600)
    return public, private, slide


def allow_one_slide(monkeypatch: pytest.MonkeyPatch, slide: Path) -> None:
    monkeypatch.setattr(module, "EXPECTED_MDS_COUNT", 1)
    monkeypatch.setattr(module, "EXPECTED_MDS_BYTES", slide.stat().st_size)


def metadata_file(tmp_path: Path) -> Path:
    path = tmp_path / "metadata.json"
    path.write_text(
        json.dumps(
            {
                "metadata": {
                    "title": "Tutorial fixture",
                    "description": "Test only",
                    "upload_type": "dataset",
                    "access_right": "restricted",
                    "access_conditions": "Access after review.",
                    "license": "CC-BY-4.0",
                    "creators": [{"name": "Doe, Jane"}],
                    "keywords": ["digital pathology", "lymphoma"],
                    "related_identifiers": [
                        {
                            "identifier": "https://github.com/example/tutorial",
                            "relation": "isSupplementTo",
                            "scheme": "url",
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_collect_mds_uploads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public, private, slide = manifests(tmp_path)
    allow_one_slide(monkeypatch, slide)
    uploads = module.collect_mds_uploads(public, private)
    assert len(uploads) == 2
    by_kind = {upload.kind: upload for upload in uploads}
    assert by_kind["sanitized-mds"].local_path == slide.resolve()
    assert by_kind["public-manifest"].local_path == public.resolve()


def test_collect_rejects_incomplete_privacy_review(tmp_path: Path) -> None:
    public, private, _ = manifests(tmp_path)
    text = private.read_text(encoding="utf-8").replace(",True,", ",False,")
    private.write_text(text, encoding="utf-8")
    os.chmod(private, 0o600)
    with pytest.raises(module.base.DepositError, match="privacy validation"):
        module.collect_mds_uploads(public, private)


def test_collect_rejects_full_pixel_fingerprint_mismatch(
    tmp_path: Path,
) -> None:
    public, private, _ = manifests(tmp_path)
    text = private.read_text(encoding="utf-8").replace("b" * 64, "c" * 64)
    private.write_text(text, encoding="utf-8")
    os.chmod(private, 0o600)
    with pytest.raises(module.base.DepositError, match="full pixel fingerprint"):
        module.collect_mds_uploads(public, private)


def test_private_mapping_must_not_be_group_readable(tmp_path: Path) -> None:
    public, private, _ = manifests(tmp_path)
    os.chmod(private, 0o644)
    with pytest.raises(module.base.DepositError, match="group/other"):
        module.collect_mds_uploads(public, private)


def test_depositor_accepts_only_official_zenodo_origins() -> None:
    assert module.validated_api_url("https://zenodo.org/api/") == (
        "https://zenodo.org/api"
    )
    with pytest.raises(module.base.DepositError, match="api-url"):
        module.validated_api_url("https://example.org/api")


def test_parser_has_no_publish_option() -> None:
    options = {action.dest for action in module.build_parser()._actions}
    assert "publish" not in options
    assert "authorization" not in options


def test_progress_reader_preserves_bytes(tmp_path: Path) -> None:
    path = tmp_path / "payload"
    path.write_bytes(b"123456")
    with path.open("rb") as handle:
        reader = module.ProgressReader(handle, "safe.mds", 6)
        assert len(reader) == 6
        assert reader.read(2) == b"12"
        assert reader.read() == b"3456"


def test_restricted_metadata_allows_blank_license(tmp_path: Path) -> None:
    path = metadata_file(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metadata"]["license"] = ""
    path.write_text(json.dumps(payload), encoding="utf-8")
    metadata = module.restricted_metadata_from_file(path)
    assert "license" not in metadata
    assert metadata["access_right"] == "restricted"


class FakeZenodoClient:
    files: list[dict[str, object]] = []
    metadata: dict[str, object] = {}

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    @classmethod
    def payload(cls) -> dict[str, object]:
        return {
            "id": 123,
            "submitted": False,
            "state": "inprogress",
            "metadata": cls.metadata,
            "files": list(cls.files),
            "links": {
                "bucket": "https://zenodo.org/api/files/test",
                "html": "https://zenodo.org/uploads/123",
            },
        }

    def create_draft(self) -> dict[str, object]:
        type(self).files = []
        type(self).metadata = {}
        return self.payload()

    def get_draft(self, _deposition_id: str) -> dict[str, object]:
        return self.payload()

    def update_metadata(
        self, _deposition_id: str, metadata: dict[str, object]
    ) -> dict[str, object]:
        type(self).metadata = dict(metadata)
        return self.payload()

    def upload_file(
        self, _bucket_url: str, upload: module.base.UploadFile
    ) -> dict[str, object]:
        item = {
            "filename": upload.remote_name,
            "filesize": upload.size_bytes,
            "checksum": f"md5:{upload.md5}",
            "links": {
                "self": (
                    "https://zenodo.org/api/deposit/depositions/123/files/"
                    f"{upload.remote_name}"
                )
            },
        }
        type(self).files.append(item)
        return item

    def delete_file(self, _url: str) -> None:
        raise AssertionError("No file should be deleted in this test")


def test_deposit_draft_chain_is_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public, private, slide = manifests(tmp_path)
    allow_one_slide(monkeypatch, slide)
    monkeypatch.setattr(module, "ProgressZenodoClient", FakeZenodoClient)
    token = tmp_path / "token"
    token.write_text("secret", encoding="utf-8")
    os.chmod(token, 0o600)
    state = tmp_path / "state.json"
    result = module.deposit_mds(
        public_manifest=public,
        private_mapping=private,
        metadata_file=metadata_file(tmp_path),
        state_file=state,
        token_file=token,
    )
    assert result["status"] == "restricted-unpublished-draft"
    assert result["mds_file_count"] == 1
    assert result["file_count"] == 2
    stored = json.loads(state.read_text(encoding="utf-8"))
    assert stored["status"] == "draft"
    assert stored["release_fingerprint_sha256"]
    assert len(stored["uploaded"]) == 2


def test_draft_metadata_requires_restricted_conditions() -> None:
    payload = {
        "submitted": False,
        "state": "inprogress",
        "metadata": {
            "title": "x",
            "access_right": "restricted",
            "access_conditions": "",
        },
    }
    with pytest.raises(module.base.DepositError, match="access conditions"):
        module.validate_draft_metadata(payload, payload["metadata"])

@pytest.mark.parametrize(
    "field,replacement",
    [
        ("description", "Altered description"),
        ("keywords", ["altered"]),
        (
            "related_identifiers",
            [
                {
                    "identifier": "https://example.org/altered",
                    "relation": "isSupplementTo",
                    "scheme": "url",
                }
            ],
        ),
    ],
)
def test_draft_metadata_rejects_remote_descriptive_metadata_mismatch(
    tmp_path: Path, field: str, replacement: object
) -> None:
    expected = module.restricted_metadata_from_file(metadata_file(tmp_path))
    actual = dict(expected)
    actual[field] = replacement
    payload = {
        "submitted": False,
        "state": "inprogress",
        "metadata": actual,
    }
    with pytest.raises(module.base.DepositError, match=field):
        module.validate_draft_metadata(payload, expected)


def test_draft_metadata_accepts_unsubmitted_state(tmp_path: Path) -> None:
    expected = module.restricted_metadata_from_file(metadata_file(tmp_path))
    payload = {
        "submitted": False,
        "state": "unsubmitted",
        "metadata": dict(expected),
    }
    module.validate_draft_metadata(payload, expected)


def test_draft_metadata_accepts_current_zenodo_normalization(
    tmp_path: Path,
) -> None:
    expected = module.restricted_metadata_from_file(metadata_file(tmp_path))
    expected["description"] = "H&E tutorial dataset"
    actual = dict(expected)
    actual["description"] = "H&amp;E tutorial dataset"
    actual["creators"] = [
        {"name": "Doe, Jane", "affiliation": None}
    ]
    actual["access_conditions"] = None
    payload = {
        "submitted": False,
        "state": "unsubmitted",
        "metadata": actual,
    }
    module.validate_draft_metadata(payload, expected)


def test_draft_metadata_rejects_missing_conditions_for_legacy_state(
    tmp_path: Path,
) -> None:
    expected = module.restricted_metadata_from_file(metadata_file(tmp_path))
    actual = dict(expected)
    actual["access_conditions"] = None
    payload = {
        "submitted": False,
        "state": "inprogress",
        "metadata": actual,
    }
    with pytest.raises(module.base.DepositError, match="access conditions"):
        module.validate_draft_metadata(payload, expected)


def test_draft_metadata_rejects_creator_change_after_normalization(
    tmp_path: Path,
) -> None:
    expected = module.restricted_metadata_from_file(metadata_file(tmp_path))
    actual = dict(expected)
    actual["creators"] = [
        {"name": "Other, Person", "affiliation": None}
    ]
    payload = {
        "submitted": False,
        "state": "unsubmitted",
        "metadata": actual,
    }
    with pytest.raises(module.base.DepositError, match="creators"):
        module.validate_draft_metadata(payload, expected)


def test_draft_metadata_rejects_changed_access_conditions(
    tmp_path: Path,
) -> None:
    expected = module.restricted_metadata_from_file(metadata_file(tmp_path))
    actual = dict(expected)
    actual["access_conditions"] = "Different conditions"
    payload = {
        "submitted": False,
        "state": "unsubmitted",
        "metadata": actual,
    }
    with pytest.raises(module.base.DepositError, match="access_conditions"):
        module.validate_draft_metadata(payload, expected)
