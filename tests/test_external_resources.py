from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_external_resources.py"
SPEC = importlib.util.spec_from_file_location("check_external_resources", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def test_accepts_current_zenodo_open_published_shape() -> None:
    assert CHECKER.zenodo_record_is_public({
        "status": "published", "metadata": {"access_right": "open"},
    })


def test_accepts_legacy_explicit_public_shape() -> None:
    assert CHECKER.zenodo_record_is_public({
        "status": "published", "access": {"record": "public"},
    })


def test_rejects_restricted_or_unpublished_shapes() -> None:
    assert not CHECKER.zenodo_record_is_public({
        "status": "published", "metadata": {"access_right": "restricted"},
    })
    assert not CHECKER.zenodo_record_is_public({
        "status": "draft", "metadata": {"access_right": "open"},
    })


def breast_record() -> dict[str, object]:
    files = [
        {
            "key": f"file-{index:02d}",
            "size": 1,
            "checksum": f"md5:{index:032x}",
        }
        for index in range(CHECKER.BREAST_FILE_COUNT - 1)
    ]
    files.append({
        "key": "final-file",
        "size": CHECKER.BREAST_TOTAL_BYTES - len(files),
        "checksum": "md5:ffffffffffffffffffffffffffffffff",
    })
    return {
        "id": int(CHECKER.BREAST_RECORD),
        "doi": CHECKER.BREAST_DOI,
        "status": "published",
        "metadata": {
            "access_right": "open",
            "license": {"id": "cc-by-4.0"},
            "resource_type": {"type": "dataset", "title": "Dataset"},
        },
        "files": files,
    }


def synthetic_roster_sha256(record: dict[str, object]) -> str:
    files = record["files"]
    assert isinstance(files, list)
    assert all(isinstance(item, dict) for item in files)
    return CHECKER.breast_roster_sha256(files)


def test_accepts_exact_breast_ihc_public_record_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = breast_record()
    monkeypatch.setattr(
        CHECKER, "BREAST_ROSTER_SHA256", synthetic_roster_sha256(record)
    )
    assert CHECKER.breast_record_failures(record) == []


def test_rejects_changed_breast_ihc_license_or_total_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = breast_record()
    monkeypatch.setattr(
        CHECKER, "BREAST_ROSTER_SHA256", synthetic_roster_sha256(record)
    )
    metadata = record["metadata"]
    assert isinstance(metadata, dict)
    metadata["license"] = {"id": "cc0-1.0"}
    files = record["files"]
    assert isinstance(files, list)
    final_file = files[-1]
    assert isinstance(final_file, dict)
    final_file["size"] = int(final_file["size"]) - 1

    failures = CHECKER.breast_record_failures(record)
    assert "breast-IHC Zenodo license is not CC BY 4.0" in failures
    assert "breast-IHC Zenodo total byte count changed" in failures
    assert "breast-IHC Zenodo filename/size/checksum roster changed" in failures


@pytest.mark.parametrize("field", ["key", "checksum"])
def test_rejects_changed_breast_ihc_filename_or_checksum(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    record = breast_record()
    monkeypatch.setattr(
        CHECKER, "BREAST_ROSTER_SHA256", synthetic_roster_sha256(record)
    )
    files = record["files"]
    assert isinstance(files, list)
    first_file = files[0]
    assert isinstance(first_file, dict)
    first_file[field] = (
        "renamed-file" if field == "key" else "md5:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    )

    failures = CHECKER.breast_record_failures(record)
    assert "breast-IHC Zenodo filename/size/checksum roster changed" in failures


def test_rejects_duplicate_breast_ihc_filename() -> None:
    record = breast_record()
    files = record["files"]
    assert isinstance(files, list)
    first_file = files[0]
    second_file = files[1]
    assert isinstance(first_file, dict) and isinstance(second_file, dict)
    second_file["key"] = first_file["key"]

    failures = CHECKER.breast_record_failures(record)
    assert "breast-IHC Zenodo file count/names changed" in failures
