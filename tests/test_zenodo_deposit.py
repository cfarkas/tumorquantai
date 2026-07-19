from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import unquote

import requests


SCRIPT = Path(__file__).parents[1] / "bin" / "zenodo_deposit.py"
SPEC = importlib.util.spec_from_file_location("zenodo_deposit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
deposit_tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = deposit_tool
SPEC.loader.exec_module(deposit_tool)


def response(status: int, payload: dict[str, object]) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = "https://zenodo.example/test"
    result._content = json.dumps(payload).encode("utf-8")
    result._content_consumed = True
    return result


class FakeZenodoSession:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.calls: list[tuple[str, str, dict[str, object]]] = []
        self.published = False
        self.metadata: dict[str, object] | None = None
        self.returned_metadata_override: dict[str, object] | None = None

    def draft(self) -> dict[str, object]:
        returned_metadata = (
            self.returned_metadata_override
            if self.returned_metadata_override is not None
            else self.metadata
        )
        return {
            "id": 42,
            "links": {"bucket": "https://zenodo.example/api/files/bucket"},
            "metadata": returned_metadata or {},
            "files": [
                {
                    "filename": name,
                    "filesize": len(payload),
                    "checksum": "md5:"
                    + hashlib.md5(payload, usedforsecurity=False).hexdigest(),
                    "links": {
                        "self": f"https://zenodo.example/api/deposit/depositions/42/files/{name}"
                    },
                }
                for name, payload in sorted(self.files.items())
            ],
        }

    def request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        self.calls.append((method, url, kwargs))
        authorization = str(kwargs.get("headers", {}).get("Authorization", ""))
        if authorization != "Bearer test-secret-token":
            raise AssertionError("Missing bearer authorization")
        if "test-secret-token" in url:
            raise AssertionError("Token leaked into URL")
        if method == "POST" and url.endswith("/deposit/depositions"):
            return response(201, self.draft())
        if method == "GET" and url.endswith("/deposit/depositions/42"):
            return response(200, self.draft())
        if method == "PUT" and url.endswith("/deposit/depositions/42"):
            self.metadata = kwargs["json"]["metadata"]
            return response(200, self.draft())
        if method == "PUT" and "/api/files/bucket/" in url:
            name = unquote(url.rsplit("/", 1)[-1])
            payload = kwargs["data"].read()
            self.files[name] = payload
            return response(
                201,
                {
                    "key": name,
                    "size": len(payload),
                    "checksum": "md5:"
                    + hashlib.md5(payload, usedforsecurity=False).hexdigest(),
                },
            )
        if method == "DELETE":
            name = unquote(url.rsplit("/", 1)[-1])
            self.files.pop(name, None)
            result = requests.Response()
            result.status_code = 204
            result._content = b""
            return result
        if method == "POST" and url.endswith("/actions/publish"):
            self.published = True
            return response(202, {"id": 100, "record_id": 100})
        raise AssertionError(f"Unexpected request: {method} {url}")


class ZenodoDepositTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.public_dir = self.root / "public"
        self.private_dir = self.root / "private"
        self.public_dir.mkdir()
        self.private_dir.mkdir()
        self.alias = "TumorQuantAI_LymphomaWSI_001"
        self.payloads = {0: b"level zero pixels", 2: b"level two pixels"}
        self.public_manifest = self.public_dir / "tumorquantai_lymphoma_manifest.csv"
        self.private_mapping = self.private_dir / "source_mapping.csv"
        self.write_manifests()
        self.metadata = self.root / "metadata.json"
        self.metadata.write_text(
            json.dumps(
                {
                    "metadata": {
                        "title": "TumorQuantAI lymphoma WSI dataset",
                        "description": "De-identified test dataset",
                        "upload_type": "dataset",
                        "access_right": "open",
                        "license": "cc-by-4.0",
                        "creators": [{"name": "Example, Researcher"}],
                    }
                }
            ),
            encoding="utf-8",
        )
        self.state = self.root / "state.json"

    def write_manifests(self) -> None:
        public_rows = []
        private_rows = []
        for level, payload in self.payloads.items():
            export = self.private_dir / f"source_L{level}.tif"
            export.write_bytes(payload)
            digest_sha = hashlib.sha256(payload).hexdigest()
            digest_md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
            remote = f"{self.alias}_L{level}_rgb.tif"
            public_rows.append(
                {
                    "alias": self.alias,
                    "level": level,
                    "source_mpp": 0.261780,
                    "zenodo_filename": remote,
                    "dataset_path": f"slides/{self.alias}/1_L{level}_rgb.tif",
                    "size_bytes": len(payload),
                    "sha256": digest_sha,
                    "md5": digest_md5,
                    "width": 16,
                    "height": 12,
                    "channels": 3,
                    "dtype": "uint8",
                    "photometric": "RGB",
                    "is_tiled": False,
                }
            )
            private_rows.append(
                {
                    "alias": self.alias,
                    "level": level,
                    "export_path": export,
                    "zenodo_filename": remote,
                    "sha256": digest_sha,
                    "md5": digest_md5,
                }
            )
        with self.public_manifest.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=public_rows[0].keys())
            writer.writeheader()
            writer.writerows(public_rows)
        with self.private_mapping.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=private_rows[0].keys())
            writer.writeheader()
            writer.writerows(private_rows)
        os.chmod(self.private_mapping, 0o600)

        with (self.public_dir / "samples.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(
                handle, fieldnames=("sample_id", "slide_path")
            )
            writer.writeheader()
            writer.writerow(
                {
                    "sample_id": self.alias,
                    "slide_path": public_rows[0]["dataset_path"].removeprefix("slides/"),
                }
            )
        (self.public_dir / "SHA256SUMS").write_text(
            "".join(
                f"{row['sha256']}  {row['zenodo_filename']}\n"
                for row in public_rows
            ),
            encoding="utf-8",
        )
        (self.public_dir / "MD5SUMS").write_text(
            "".join(
                f"{row['md5']}  {row['zenodo_filename']}\n"
                for row in public_rows
            ),
            encoding="utf-8",
        )
        report_files = [
            {
                "alias": row["alias"],
                "level": row["level"],
                "zenodo_filename": row["zenodo_filename"],
                "width": row["width"],
                "height": row["height"],
                "channels": row["channels"],
                "dtype": row["dtype"],
                "photometric": row["photometric"],
                "is_tiled": row["is_tiled"],
                "page_count": 1,
                "sensitive_tag_count": 0,
                "source_identifier_hit_count": 0,
                "status": "passed",
            }
            for row in public_rows
        ]
        (self.public_dir / "tiff_validation_report.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "passed",
                    "pair_count": 1,
                    "file_count": len(public_rows),
                    "total_size_bytes": sum(
                        int(row["size_bytes"]) for row in public_rows
                    ),
                    "source_mpp": 0.261780,
                    "files": report_files,
                }
            ),
            encoding="utf-8",
        )

    def kwargs(self) -> dict[str, object]:
        return {
            "public_manifest": self.public_manifest,
            "private_mapping": self.private_mapping,
            "public_dir": self.public_dir,
            "metadata_file": self.metadata,
            "state_file": self.state,
            "extra_files": [],
            "api_url": "https://zenodo.example/api",
            "retries": 0,
        }

    def authorization(self) -> Path:
        path = self.root / "authorization.json"
        payload = {
            key: True for key in deposit_tool.PUBLISH_CONFIRMATIONS
        }
        metadata = deposit_tool.metadata_from_file(self.metadata)
        uploads = deposit_tool.collect_uploads(
            self.public_manifest, self.private_mapping, self.public_dir, []
        )
        payload["release_fingerprint_sha256"] = deposit_tool.release_fingerprint(
            metadata, uploads
        )
        payload.update(
            {
                "authorized_by": "Data steward",
                "authorized_at": "2026-07-16T12:00:00-04:00",
                "license": "cc-by-4.0",
            }
        )
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_plan_is_local_only_and_does_not_require_token(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            result = deposit_tool.deposit(**self.kwargs(), plan=True)
        self.assertTrue(result["plan"])
        self.assertEqual(result["file_count"], 7)
        self.assertRegex(result["release_fingerprint_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            result["required_publish_confirmations"],
            list(deposit_tool.PUBLISH_CONFIRMATIONS),
        )
        self.assertFalse(self.state.exists())

    def test_plan_requires_all_five_generated_public_artifacts(self) -> None:
        for name in sorted(deposit_tool.GENERATED_PUBLIC_FILES):
            with self.subTest(name=name):
                artifact = self.public_dir / name
                original = artifact.read_bytes()
                artifact.unlink()
                try:
                    with self.assertRaisesRegex(
                        deposit_tool.DepositError,
                        "Missing required generated public artifact",
                    ):
                        deposit_tool.deposit(**self.kwargs(), plan=True)
                finally:
                    artifact.write_bytes(original)

    def test_plan_rejects_stale_samples(self) -> None:
        (self.public_dir / "samples.csv").write_text(
            "sample_id,slide_path\n"
            f"{self.alias},slides/{self.alias}/wrong.tif\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            deposit_tool.DepositError, "samples.csv does not exactly match"
        ):
            deposit_tool.deposit(**self.kwargs(), plan=True)

    def test_plan_rejects_stale_checksum_files(self) -> None:
        for name in ("SHA256SUMS", "MD5SUMS"):
            with self.subTest(name=name):
                artifact = self.public_dir / name
                original = artifact.read_text(encoding="utf-8")
                lines = original.splitlines()
                replacement = "0" if lines[0][0] != "0" else "1"
                lines[0] = replacement + lines[0][1:]
                artifact.write_text("\n".join(lines) + "\n", encoding="utf-8")
                try:
                    with self.assertRaisesRegex(
                        deposit_tool.DepositError,
                        rf"{name} does not exactly match",
                    ):
                        deposit_tool.deposit(**self.kwargs(), plan=True)
                finally:
                    artifact.write_text(original, encoding="utf-8")

    def test_plan_rejects_report_count_or_size_mismatch(self) -> None:
        report_path = self.public_dir / "tiff_validation_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["total_size_bytes"] += 1
        report_path.write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaisesRegex(
            deposit_tool.DepositError, "counts/sizes do not match"
        ):
            deposit_tool.deposit(**self.kwargs(), plan=True)

    def test_plan_rejects_report_source_mpp_mismatch(self) -> None:
        report_path = self.public_dir / "tiff_validation_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["source_mpp"] = 0.5
        report_path.write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaisesRegex(
            deposit_tool.DepositError, "source MPP does not match"
        ):
            deposit_tool.deposit(**self.kwargs(), plan=True)

    def test_plan_rejects_inconsistent_manifest_source_mpp(self) -> None:
        with self.public_manifest.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames
            rows = list(reader)
        assert fieldnames is not None
        rows[1]["source_mpp"] = "0.500000"
        with self.public_manifest.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        with self.assertRaisesRegex(
            deposit_tool.DepositError, "one finite, consistent source MPP"
        ):
            deposit_tool.deposit(**self.kwargs(), plan=True)

    def test_default_creates_verified_draft_and_resumes_without_reupload(self) -> None:
        session = FakeZenodoSession()
        with mock.patch.dict(os.environ, {"ZENODO_TOKEN": "test-secret-token"}):
            first = deposit_tool.deposit(**self.kwargs(), session=session)
        self.assertEqual(first["status"], "draft")
        self.assertFalse(session.published)
        upload_calls = [
            call for call in session.calls
            if call[0] == "PUT" and "/api/files/bucket/" in call[1]
        ]
        self.assertEqual(len(upload_calls), 7)
        state_text = self.state.read_text(encoding="utf-8")
        self.assertNotIn("test-secret-token", state_text)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o600)

        session.calls.clear()
        with mock.patch.dict(os.environ, {"ZENODO_TOKEN": "test-secret-token"}):
            second = deposit_tool.deposit(**self.kwargs(), session=session)
        self.assertEqual(second["status"], "draft")
        self.assertFalse(
            any(call[0] == "PUT" and "/api/files/bucket/" in call[1] for call in session.calls)
        )

    def test_publish_requires_all_authorization_confirmations(self) -> None:
        authorization = self.authorization()
        payload = json.loads(authorization.read_text(encoding="utf-8"))
        payload["dataset_rights_confirmed"] = False
        authorization.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(deposit_tool.DepositError, "dataset_rights_confirmed"):
            deposit_tool.deposit(
                **self.kwargs(),
                publish=True,
                authorization=authorization,
            )

    def test_publish_requires_pixel_content_privacy_confirmation(self) -> None:
        authorization = self.authorization()
        payload = json.loads(authorization.read_text(encoding="utf-8"))
        payload.pop("pixel_content_privacy_review_complete")
        authorization.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(
            deposit_tool.DepositError,
            "pixel_content_privacy_review_complete",
        ):
            deposit_tool.deposit(
                **self.kwargs(), publish=True, authorization=authorization
            )

    def test_plan_allows_placeholders_but_publish_rejects_metadata_placeholder(
        self,
    ) -> None:
        payload = json.loads(self.metadata.read_text(encoding="utf-8"))
        payload["metadata"]["title"] = "{{AUTHORIZED_DATASET_TITLE}}"
        self.metadata.write_text(json.dumps(payload), encoding="utf-8")
        plan = deposit_tool.deposit(**self.kwargs(), plan=True)
        self.assertTrue(plan["plan"])
        with self.assertRaisesRegex(
            deposit_tool.DepositError, "unresolved release placeholders.*metadata"
        ):
            deposit_tool.deposit(
                **self.kwargs(),
                publish=True,
                authorization=self.authorization(),
            )

    def test_publish_rejects_placeholder_in_extra_public_document(self) -> None:
        document = self.root / "README.md"
        document.write_text("DOI: {{ZENODO_DOI}}\n", encoding="utf-8")
        kwargs = self.kwargs()
        kwargs["extra_files"] = [f"{document}=README.md"]
        with self.assertRaisesRegex(
            deposit_tool.DepositError, "unresolved release placeholders.*README.md"
        ):
            deposit_tool.deposit(
                **kwargs,
                publish=True,
                authorization=self.authorization(),
            )

    def test_authorization_fingerprint_rejects_metadata_or_file_set_change(self) -> None:
        authorization = self.authorization()
        metadata_payload = json.loads(self.metadata.read_text(encoding="utf-8"))
        metadata_payload["metadata"]["description"] = "Changed after approval"
        self.metadata.write_text(json.dumps(metadata_payload), encoding="utf-8")
        with self.assertRaisesRegex(deposit_tool.DepositError, "not bound"):
            deposit_tool.deposit(
                **self.kwargs(),
                publish=True,
                authorization=authorization,
            )

    def test_explicit_authorization_can_publish_after_verification(self) -> None:
        session = FakeZenodoSession()
        with mock.patch.dict(os.environ, {"ZENODO_TOKEN": "test-secret-token"}):
            result = deposit_tool.deposit(
                **self.kwargs(),
                session=session,
                publish=True,
                authorization=self.authorization(),
            )
        self.assertEqual(result["status"], "published")
        self.assertTrue(session.published)
        self.assertEqual(json.loads(self.state.read_text())["status"], "published")

    def test_publish_rejects_draft_metadata_different_from_authorization(self) -> None:
        session = FakeZenodoSession()
        returned = deposit_tool.metadata_from_file(self.metadata)
        returned["license"] = "cc0-1.0"
        session.returned_metadata_override = returned
        with mock.patch.dict(os.environ, {"ZENODO_TOKEN": "test-secret-token"}):
            with self.assertRaisesRegex(
                deposit_tool.DepositError,
                "authorized metadata: license",
            ):
                deposit_tool.deposit(
                    **self.kwargs(),
                    session=session,
                    publish=True,
                    authorization=self.authorization(),
                )
        self.assertFalse(session.published)

    def test_rejects_unexpected_public_manifest_columns(self) -> None:
        with self.public_manifest.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            row["source_path"] = "private-identifier"
        with self.public_manifest.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        with self.assertRaisesRegex(deposit_tool.DepositError, "preparation-tool schema"):
            deposit_tool.deposit(**self.kwargs(), plan=True)

    def test_upload_retry_rewinds_the_file_stream(self) -> None:
        payload = b"retry-safe payload"
        source = self.root / "retry.bin"
        source.write_bytes(payload)
        upload = deposit_tool.make_small_upload(source, "retry.bin", "test")

        class RetrySession:
            def __init__(self) -> None:
                self.bodies = []

            def request(inner_self, method: str, url: str, **kwargs: object) -> requests.Response:
                inner_self.bodies.append(kwargs["data"].read())
                if len(inner_self.bodies) == 1:
                    return response(503, {})
                return response(
                    201,
                    {
                        "size": len(payload),
                        "checksum": "md5:"
                        + hashlib.md5(payload, usedforsecurity=False).hexdigest(),
                    },
                )

        session = RetrySession()
        client = deposit_tool.ZenodoClient(
            "test-secret-token",
            "https://zenodo.example/api",
            retries=1,
            session=session,
        )
        with mock.patch.object(deposit_tool.time, "sleep"):
            result = client.upload_file(
                "https://zenodo.example/api/files/bucket", upload
            )
        self.assertEqual(result["size"], len(payload))
        self.assertEqual(session.bodies, [payload, payload])

    def test_authenticated_client_refuses_cross_origin_url(self) -> None:
        session = FakeZenodoSession()
        client = deposit_tool.ZenodoClient(
            "test-secret-token", "https://zenodo.example/api", session=session
        )
        with self.assertRaisesRegex(deposit_tool.DepositError, "another origin"):
            client.request(
                "GET", "https://attacker.example/steal", expected=(200,)
            )
        self.assertEqual(session.calls, [])

    def test_publish_rejects_unreviewed_extra_draft_file(self) -> None:
        session = FakeZenodoSession()
        session.files["unreviewed-extra.tif"] = b"not approved"
        with mock.patch.dict(os.environ, {"ZENODO_TOKEN": "test-secret-token"}):
            with self.assertRaisesRegex(deposit_tool.DepositError, "unreviewed extra"):
                deposit_tool.deposit(
                    **self.kwargs(),
                    session=session,
                    publish=True,
                    authorization=self.authorization(),
                )
        self.assertFalse(session.published)

    def test_token_file_must_be_private(self) -> None:
        token_file = self.root / "token"
        token_file.write_text("test-secret-token\n", encoding="utf-8")
        os.chmod(token_file, 0o644)
        with self.assertRaisesRegex(deposit_tool.DepositError, "group/other"):
            deposit_tool.resolve_token("ZENODO_TOKEN", token_file)

    def test_changed_local_wsi_is_rejected_before_upload(self) -> None:
        source = self.private_dir / "source_L0.tif"
        source.write_bytes(b"changed but same len!")
        session = FakeZenodoSession()
        with mock.patch.dict(os.environ, {"ZENODO_TOKEN": "test-secret-token"}):
            with self.assertRaisesRegex(
                deposit_tool.DepositError, "size changed|changed since preparation"
            ):
                deposit_tool.deposit(**self.kwargs(), session=session)


if __name__ == "__main__":
    unittest.main()
