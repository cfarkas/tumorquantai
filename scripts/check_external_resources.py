#!/usr/bin/env python3
"""Scheduled checks for public release, dataset, DOI, docs, and model metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


SOFTWARE_RELEASE = "v1.0.0"
RECORD = "21466410"
DOI = "10.5281/zenodo.21466410"
SAMPLE_FILE = "TumorQuantAI_LymphomaWSI_022.mds"
SAMPLE_SIZE = 125_350_400
SAMPLE_MD5 = "94bb5b08ccf1957f8c42a579e8b33cfb"
MODEL_REVISION = "cde2eee81af9e39b03802fc33d4f284733b5ee5e"
BREAST_RECORD = "21797920"
BREAST_DOI = "10.5281/zenodo.21797920"
BREAST_FILE_COUNT = 55
BREAST_TOTAL_BYTES = 74_958_557_152
BREAST_ROSTER_SHA256 = (
    "a16f5cf00acc5aa20463f8a942175f11db608e082f7d067da917c8b29dd842fc"
)


def request(url: str, *, expect_json: bool = False) -> tuple[int, Any]:
    headers = {"User-Agent": "TumorQuantAI-external-check/1.0.0"}
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if github_token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = "Bearer " + github_token
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
            payload = response.read(10 * 1024 * 1024 + 1)
            status = int(getattr(response, "status", 200))
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError(f"request failed for {url}: {exc}") from exc
    if len(payload) > 10 * 1024 * 1024:
        raise RuntimeError(f"refusing unexpectedly large metadata response from {url}")
    if expect_json:
        try:
            return status, json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid JSON metadata from {url}") from exc
    return status, payload


def zenodo_record_is_public(record: dict[str, Any]) -> bool:
    """Accept explicit public/open markers from supported Zenodo API shapes."""
    access = record.get("access")
    if isinstance(access, dict) and access.get("record") == "public":
        return record.get("status") in {None, "published"}
    metadata = record.get("metadata")
    return bool(
        isinstance(metadata, dict)
        and metadata.get("access_right") in {"open", "public"}
        and record.get("status") == "published"
    )


def breast_roster_sha256(files: list[dict[str, Any]]) -> str:
    """Hash the sorted public filename, byte-size, and Zenodo checksum roster."""
    rows = []
    for item in files:
        name = str(item.get("key") or item.get("filename") or "")
        size = item.get("size", item.get("filesize"))
        checksum = str(item.get("checksum") or "").lower()
        rows.append(f"{name}\t{size}\t{checksum}\n")
    return hashlib.sha256("".join(sorted(rows)).encode("utf-8")).hexdigest()


def breast_record_failures(record: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if str(record.get("id")) != BREAST_RECORD or record.get("doi") != BREAST_DOI:
        failures.append("breast-IHC Zenodo record ID/DOI changed")
    if not zenodo_record_is_public(record):
        failures.append("breast-IHC Zenodo record is not reported as public")
    metadata = record.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    license_value = metadata.get("license")
    license_id = (
        license_value.get("id")
        if isinstance(license_value, dict)
        else license_value
    )
    if str(license_id).casefold() != "cc-by-4.0":
        failures.append("breast-IHC Zenodo license is not CC BY 4.0")
    resource_type = metadata.get("resource_type")
    resource_id = (
        resource_type.get("type")
        if isinstance(resource_type, dict)
        else metadata.get("upload_type")
    )
    if str(resource_id).casefold() != "dataset":
        failures.append("breast-IHC Zenodo resource type is not dataset")
    files = record.get("files")
    if not isinstance(files, list) or not all(
        isinstance(item, dict) for item in files
    ):
        failures.append("breast-IHC Zenodo file roster is invalid")
        return failures
    names = [str(item.get("key") or item.get("filename") or "") for item in files]
    sizes = [item.get("size", item.get("filesize")) for item in files]
    checksums = [str(item.get("checksum") or "").lower() for item in files]
    if (
        len(files) != BREAST_FILE_COUNT
        or any(not name for name in names)
        or len(set(names)) != len(names)
    ):
        failures.append("breast-IHC Zenodo file count/names changed")
    if (
        any(not isinstance(size, int) or size <= 0 for size in sizes)
        or sum(size for size in sizes if isinstance(size, int))
        != BREAST_TOTAL_BYTES
    ):
        failures.append("breast-IHC Zenodo total byte count changed")
    if any(
        len(checksum) != 36
        or not checksum.startswith("md5:")
        or any(character not in "0123456789abcdef" for character in checksum[4:])
        for checksum in checksums
    ):
        failures.append("breast-IHC Zenodo checksum metadata is invalid")
    elif breast_roster_sha256(files) != BREAST_ROSTER_SHA256:
        failures.append(
            "breast-IHC Zenodo filename/size/checksum roster changed"
        )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pre-release",
        action="store_true",
        help=(
            "check public dependencies and datasets before the new GitHub "
            "software release exists"
        ),
    )
    args = parser.parse_args(argv)
    failures: list[str] = []
    checks: list[str] = []
    if not args.pre_release:
        try:
            _status, release = request(
                "https://api.github.com/repos/cfarkas/tumorquantai/releases/tags/"
                f"{SOFTWARE_RELEASE}",
                expect_json=True,
            )
            if (
                release.get("tag_name") != SOFTWARE_RELEASE
                or release.get("draft")
                or release.get("prerelease")
            ):
                failures.append(
                    f"GitHub release {SOFTWARE_RELEASE} identity/state changed"
                )
            checks.append("GitHub release")
        except RuntimeError as exc:
            failures.append(str(exc))

    try:
        _status, breast_record = request(
            f"https://zenodo.org/api/records/{BREAST_RECORD}",
            expect_json=True,
        )
        failures.extend(breast_record_failures(breast_record))
        checks.append("breast-IHC Zenodo record")
    except RuntimeError as exc:
        failures.append(str(exc))

    try:
        _status, record = request(f"https://zenodo.org/api/records/{RECORD}", expect_json=True)
        if str(record.get("id")) != RECORD or record.get("doi") != DOI:
            failures.append("Zenodo record ID/DOI changed")
        if not zenodo_record_is_public(record):
            failures.append("Zenodo record is no longer reported as public")
        files = {item.get("key"): item for item in record.get("files", []) if isinstance(item, dict)}
        sample = files.get(SAMPLE_FILE, {})
        checksum = str(sample.get("checksum", "")).removeprefix("md5:")
        if sample.get("size") != SAMPLE_SIZE or checksum.lower() != SAMPLE_MD5:
            failures.append("Zenodo sample-022 size or MD5 changed")
        checks.append("Zenodo record and sample 022")
    except RuntimeError as exc:
        failures.append(str(exc))

    for label, url, expect_json in (
        ("lymphoma dataset DOI", f"https://doi.org/{DOI}", False),
        ("breast-IHC dataset DOI", f"https://doi.org/{BREAST_DOI}", False),
        ("GitHub Pages", "https://cfarkas.github.io/tumorquantai/", False),
        ("pinned HistoPLUS revision", f"https://huggingface.co/api/models/Owkin-Bioptimus/histoplus/revision/{MODEL_REVISION}", True),
    ):
        try:
            status, payload = request(url, expect_json=expect_json)
            if not 200 <= status < 400:
                failures.append(f"{label} returned HTTP {status}")
            if label == "pinned HistoPLUS revision" and isinstance(payload, dict):
                sha = str(payload.get("sha", ""))
                if sha and sha.lower() != MODEL_REVISION:
                    failures.append("HistoPLUS revision metadata resolved to a different SHA")
            checks.append(label)
        except RuntimeError as exc:
            failures.append(str(exc))

    if failures:
        print("External resource checks failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    digest = hashlib.sha256("\n".join(checks).encode("utf-8")).hexdigest()[:12]
    print(f"External resource checks passed: {', '.join(checks)} (check-set {digest}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
