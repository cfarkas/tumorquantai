#!/usr/bin/env python3
"""Scheduled checks for public release, dataset, DOI, docs, and model metadata."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


RECORD = "21466410"
DOI = "10.5281/zenodo.21466410"
SAMPLE_FILE = "TumorQuantAI_LymphomaWSI_022.mds"
SAMPLE_SIZE = 125_350_400
SAMPLE_MD5 = "94bb5b08ccf1957f8c42a579e8b33cfb"
MODEL_REVISION = "cde2eee81af9e39b03802fc33d4f284733b5ee5e"


def request(url: str, *, expect_json: bool = False) -> tuple[int, Any]:
    headers = {"User-Agent": "TumorQuantAI-external-check/0.4.0"}
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


def main() -> int:
    failures: list[str] = []
    checks: list[str] = []
    try:
        _status, release = request(
            "https://api.github.com/repos/cfarkas/tumorquantai/releases/tags/v0.4.0",
            expect_json=True,
        )
        if release.get("tag_name") != "v0.4.0" or release.get("draft") or release.get("prerelease"):
            failures.append("GitHub release v0.4.0 identity/state changed")
        checks.append("GitHub release")
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
        ("dataset DOI", f"https://doi.org/{DOI}", False),
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
