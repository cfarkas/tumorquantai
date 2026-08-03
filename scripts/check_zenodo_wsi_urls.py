#!/usr/bin/env python3
"""Probe every public Zenodo WSI URL without downloading the collection."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BIN_DIRECTORY = ROOT / "bin"
sys.path.insert(0, str(BIN_DIRECTORY))

from mds_manifest import (  # noqa: E402
    MdsManifestError,
    MdsManifestRow,
    load_manifest as load_mds_manifest,
)


MANIFEST = ROOT / "examples/lymphoma/tumorquantai_lymphoma_mds_manifest.csv"
RECORD = "21466410"
API_URL = f"https://zenodo.org/api/records/{RECORD}"
FILE_URL = f"https://zenodo.org/records/{RECORD}/files/{{filename}}?download=1"
USER_AGENT = "TumorQuantAI-Zenodo-URL-check/0.4.0"
MANIFEST_FILENAME = "tumorquantai_lymphoma_mds_manifest.csv"
MANIFEST_SIZE = 10_108
MANIFEST_MD5 = "ad9a9472e8beb302f8b9ba2b3359bacc"
MANIFEST_SHA256 = "48ca87237c867bf34fe0214f229fd04633ae8bd83555275932f698057231ad20"
ALLOWED_HTTPS_HOSTS = frozenset({"zenodo.org", "www.zenodo.org"})


def load_manifest(path: Path = MANIFEST) -> list[MdsManifestRow]:
    try:
        rows, _text = load_mds_manifest(path)
    except MdsManifestError as exc:
        raise RuntimeError(str(exc)) from exc
    if len(rows) != 21:
        raise RuntimeError(f"public manifest must contain 21 slides; found {len(rows)}")
    aliases = {row.alias for row in rows}
    filenames = {row.zenodo_filename for row in rows}
    if len(aliases) != 21 or len(filenames) != 21:
        raise RuntimeError("public manifest must contain 21 unique aliases and filenames")
    return rows


def direct_url(filename: str) -> str:
    return FILE_URL.format(filename=urllib.parse.quote(filename, safe=""))


def fetch_record() -> dict[str, Any]:
    request = urllib.request.Request(API_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read(10 * 1024 * 1024 + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError(f"Zenodo record request failed: {exc}") from exc
    if len(payload) > 10 * 1024 * 1024:
        raise RuntimeError("Zenodo record metadata exceeded 10 MiB")
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Zenodo record returned invalid JSON") from exc


def record_file_map(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("key")): item
        for item in record.get("files", [])
        if isinstance(item, dict) and item.get("key")
    }


def disposition_filename(value: str) -> str | None:
    encoded = re.search(r"filename\*=UTF-8''([^;]+)", value, re.IGNORECASE)
    if encoded:
        return urllib.parse.unquote(encoded.group(1)).strip()
    plain = re.search(r'filename="?([^";]+)"?', value, re.IGNORECASE)
    return plain.group(1).strip() if plain else None


def validate_final_url(filename: str, final_url: str) -> None:
    parsed = urllib.parse.urlsplit(final_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError(f"{filename}: final URL has an invalid port") from exc
    hostname = (parsed.hostname or "").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or hostname not in ALLOWED_HTTPS_HOSTS
        or port not in {None, 443}
    ):
        raise RuntimeError(f"{filename}: final URL left approved Zenodo HTTPS hosts")


def validate_response_identity(
    filename: str, headers: Any, final_url: str
) -> None:
    validate_final_url(filename, final_url)
    reported_name = disposition_filename(headers.get("Content-Disposition", ""))
    final_name = Path(
        urllib.parse.unquote(urllib.parse.urlsplit(final_url).path)
    ).name
    if reported_name and reported_name != filename:
        raise RuntimeError(f"{filename}: Content-Disposition reports {reported_name!r}")
    if not reported_name and final_name != filename:
        raise RuntimeError(f"{filename}: final URL reports {final_name!r}")


def probe_direct_url(filename: str, expected_size: int) -> None:
    if expected_size <= 0:
        raise RuntimeError(f"{filename}: expected size must be positive")
    url = direct_url(filename)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Range": "bytes=0-0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = getattr(response, "status", None)
            if status != 206:
                raise RuntimeError(f"{filename}: direct URL returned HTTP {status}")
            data = response.read(2)
            headers = response.headers
            final_url = response.geturl()
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError(f"{filename}: direct URL failed: {exc}") from exc

    validate_response_identity(filename, headers, final_url)
    if len(data) != 1:
        raise RuntimeError(f"{filename}: range response did not return exactly one byte")

    content_range = headers.get("Content-Range", "")
    range_match = re.fullmatch(
        r"bytes 0-0/([1-9][0-9]*)",
        content_range.strip(),
        re.IGNORECASE,
    )
    if range_match is None:
        raise RuntimeError(f"{filename}: range response is missing or malformed")
    if int(range_match.group(1)) != expected_size:
        raise RuntimeError(f"{filename}: range response reports wrong size")
    if headers.get("Content-Length", "").strip() != "1":
        raise RuntimeError(f"{filename}: range response must report Content-Length 1")


def validate_record(rows: list[MdsManifestRow], record: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    files = record_file_map(record)
    expectations: list[tuple[str, int, str]] = [
        (MANIFEST_FILENAME, MANIFEST_SIZE, MANIFEST_MD5),
    ]
    expectations.extend(
        (row.zenodo_filename, row.size_bytes, row.md5) for row in rows
    )
    for filename, expected_size, expected_md5 in expectations:
        item = files.get(filename)
        if item is None:
            failures.append(f"{filename}: absent from Zenodo record metadata")
            continue
        try:
            actual_size = int(item.get("size", -1))
        except (TypeError, ValueError):
            failures.append(f"{filename}: Zenodo record size is malformed")
        else:
            if actual_size != expected_size:
                failures.append(f"{filename}: Zenodo record size differs from manifest")
        checksum = str(item.get("checksum", "")).removeprefix("md5:").lower()
        if checksum != expected_md5:
            failures.append(f"{filename}: Zenodo record MD5 differs from manifest")
    return failures


def fetch_published_manifest() -> bytes:
    request = urllib.request.Request(
        direct_url(MANIFEST_FILENAME),
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = getattr(response, "status", None)
            payload = response.read(MANIFEST_SIZE + 1)
            headers = response.headers
            final_url = response.geturl()
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError(f"published manifest request failed: {exc}") from exc

    if status != 200:
        raise RuntimeError(f"published manifest returned HTTP {status}")
    validate_response_identity(MANIFEST_FILENAME, headers, final_url)
    reported_length = headers.get("Content-Length", "")
    if reported_length and reported_length.strip() != str(MANIFEST_SIZE):
        raise RuntimeError("published manifest reports the wrong Content-Length")
    if len(payload) != MANIFEST_SIZE:
        raise RuntimeError("published manifest has the wrong byte size")
    sha256 = hashlib.sha256(payload).hexdigest()
    md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
    if sha256 != MANIFEST_SHA256:
        raise RuntimeError("published manifest SHA-256 differs from the pinned digest")
    if md5 != MANIFEST_MD5:
        raise RuntimeError("published manifest MD5 differs from the pinned digest")
    try:
        local_payload = MANIFEST.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"cannot read the committed public manifest: {exc}") from exc
    if local_payload != payload:
        raise RuntimeError("published manifest differs byte-for-byte from the repository copy")
    return payload


def main() -> int:
    try:
        rows = load_manifest()
        record = fetch_record()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Zenodo WSI URL checks failed:\n- {exc}", file=sys.stderr)
        return 1

    failures = validate_record(rows, record)
    probe_targets: list[tuple[str, int]] = [
        (MANIFEST_FILENAME, MANIFEST_SIZE),
    ]
    probe_targets.extend(
        (row.zenodo_filename, row.size_bytes) for row in rows
    )
    for filename, expected_size in probe_targets:
        try:
            probe_direct_url(filename, expected_size)
        except RuntimeError as exc:
            failures.append(str(exc))
    try:
        fetch_published_manifest()
    except RuntimeError as exc:
        failures.append(str(exc))
    if failures:
        print("Zenodo WSI URL checks failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(
        "Zenodo WSI URL checks passed for 21 slides plus the pinned 10,108-byte "
        "manifest; slide bodies were not downloaded."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
