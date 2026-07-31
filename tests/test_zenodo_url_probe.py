from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_zenodo_wsi_urls.py"
SPEC = importlib.util.spec_from_file_location("check_zenodo_wsi_urls", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class FakeResponse:
    def __init__(
        self,
        *,
        filename: str,
        size: int,
        status: int = 206,
        headers: dict[str, str] | None = None,
        data: bytes = b"x",
        final_url: str | None = None,
    ) -> None:
        self.status = status
        self.headers = headers if headers is not None else {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Range": f"bytes 0-0/{size}",
            "Content-Length": "1",
        }
        self._data = data
        self._filename = filename
        self._final_url = final_url

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _size: int = -1) -> bytes:
        return self._data if _size < 0 else self._data[:_size]

    def geturl(self) -> str:
        return self._final_url or (
            f"https://zenodo.org/records/21466410/files/{self._filename}"
        )


def test_committed_manifest_has_21_public_slides() -> None:
    rows = CHECKER.load_manifest()
    assert len(rows) == 21
    assert rows[-1].zenodo_filename == "TumorQuantAI_LymphomaWSI_022.mds"


def test_manifest_rejects_duplicate_aliases_and_filenames(tmp_path: Path) -> None:
    lines = CHECKER.MANIFEST.read_text(encoding="utf-8").splitlines()
    duplicate = "\n".join([lines[0], *([lines[1]] * 21)]) + "\n"
    path = tmp_path / "duplicate.csv"
    path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(RuntimeError, match="duplicate"):
        CHECKER.load_manifest(path)


def test_manifest_rejects_unsafe_filename(tmp_path: Path) -> None:
    rows = CHECKER.load_manifest()
    original = CHECKER.MANIFEST.read_text(encoding="utf-8")
    unsafe = original.replace(rows[0].zenodo_filename, "../unsafe.mds", 1)
    path = tmp_path / "unsafe.csv"
    path.write_text(unsafe, encoding="utf-8")
    with pytest.raises(RuntimeError, match="Unsafe MDS filename"):
        CHECKER.load_manifest(path)


def test_record_validation_checks_filename_size_and_md5() -> None:
    rows = [CHECKER.load_manifest()[-1]]
    row = rows[0]
    record = {"files": [
        {
            "key": CHECKER.MANIFEST_FILENAME,
            "size": CHECKER.MANIFEST_SIZE,
            "checksum": f"md5:{CHECKER.MANIFEST_MD5}",
        },
        {
            "key": row.zenodo_filename,
            "size": row.size_bytes,
            "checksum": f"md5:{row.md5}",
        },
    ]}
    assert CHECKER.validate_record(rows, record) == []
    record["files"][1]["size"] = 1
    failures = CHECKER.validate_record(rows, record)
    assert any(row.zenodo_filename in failure and "size differs" in failure for failure in failures)


def test_direct_probe_reads_only_range_and_validates_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filename = "TumorQuantAI_LymphomaWSI_022.mds"
    captured = {}

    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(filename=filename, size=125350400)

    monkeypatch.setattr(CHECKER.urllib.request, "urlopen", fake_urlopen)
    CHECKER.probe_direct_url(filename, 125350400)
    assert captured["request"].get_header("Range") == "bytes=0-0"
    assert captured["timeout"] == 30


def test_direct_probe_rejects_reported_size_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filename = "TumorQuantAI_LymphomaWSI_022.mds"
    monkeypatch.setattr(
        CHECKER.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(filename=filename, size=1),
    )
    with pytest.raises(RuntimeError, match="wrong size"):
        CHECKER.probe_direct_url(filename, 125350400)


@pytest.mark.parametrize(
    "content_range",
    [None, "garbage", "bytes 1-1/125350400"],
)
def test_direct_probe_rejects_missing_or_malformed_range(
    monkeypatch: pytest.MonkeyPatch,
    content_range: str | None,
) -> None:
    filename = "TumorQuantAI_LymphomaWSI_022.mds"
    response = FakeResponse(filename=filename, size=125350400)
    if content_range is None:
        response.headers.pop("Content-Range")
    else:
        response.headers["Content-Range"] = content_range
    monkeypatch.setattr(
        CHECKER.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: response,
    )
    with pytest.raises(RuntimeError, match="missing or malformed"):
        CHECKER.probe_direct_url(filename, 125350400)


@pytest.mark.parametrize(
    ("content_length", "data", "message"),
    [
        ("2", b"x", "Content-Length 1"),
        ("1", b"xx", "exactly one byte"),
    ],
)
def test_direct_probe_rejects_wrong_range_length_or_body(
    monkeypatch: pytest.MonkeyPatch,
    content_length: str,
    data: bytes,
    message: str,
) -> None:
    filename = "TumorQuantAI_LymphomaWSI_022.mds"
    response = FakeResponse(filename=filename, size=125350400, data=data)
    response.headers["Content-Length"] = content_length
    monkeypatch.setattr(
        CHECKER.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: response,
    )
    with pytest.raises(RuntimeError, match=message):
        CHECKER.probe_direct_url(filename, 125350400)


def test_direct_probe_rejects_unapproved_redirect_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filename = "TumorQuantAI_LymphomaWSI_022.mds"
    response = FakeResponse(
        filename=filename,
        size=125350400,
        final_url=f"https://example.com/files/{filename}",
    )
    monkeypatch.setattr(
        CHECKER.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: response,
    )
    with pytest.raises(RuntimeError, match="approved Zenodo HTTPS hosts"):
        CHECKER.probe_direct_url(filename, 125350400)


def test_published_manifest_is_fully_read_and_matches_pins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = CHECKER.MANIFEST.read_bytes()
    captured = {}

    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(
            filename=CHECKER.MANIFEST_FILENAME,
            size=CHECKER.MANIFEST_SIZE,
            status=200,
            headers={
                "Content-Disposition": f'attachment; filename="{CHECKER.MANIFEST_FILENAME}"',
                "Content-Length": str(CHECKER.MANIFEST_SIZE),
            },
            data=payload,
        )

    monkeypatch.setattr(CHECKER.urllib.request, "urlopen", fake_urlopen)
    assert CHECKER.fetch_published_manifest() == payload
    assert captured["request"].get_header("Range") is None
    assert captured["timeout"] == 30


def test_published_manifest_rejects_digest_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = bytearray(CHECKER.MANIFEST.read_bytes())
    payload[-1] ^= 1
    response = FakeResponse(
        filename=CHECKER.MANIFEST_FILENAME,
        size=CHECKER.MANIFEST_SIZE,
        status=200,
        headers={
            "Content-Disposition": f'attachment; filename="{CHECKER.MANIFEST_FILENAME}"',
            "Content-Length": str(CHECKER.MANIFEST_SIZE),
        },
        data=bytes(payload),
    )
    monkeypatch.setattr(
        CHECKER.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: response,
    )
    with pytest.raises(RuntimeError, match="SHA-256"):
        CHECKER.fetch_published_manifest()


def test_direct_probe_rejects_full_body_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filename = "TumorQuantAI_LymphomaWSI_022.mds"
    monkeypatch.setattr(
        CHECKER.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(
            filename=filename, size=125350400, status=200
        ),
    )
    with pytest.raises(RuntimeError, match="HTTP 200"):
        CHECKER.probe_direct_url(filename, 125350400)
