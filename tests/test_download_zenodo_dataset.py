from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import requests


SCRIPT = Path(__file__).parents[1] / "bin" / "download_zenodo_dataset.py"
SPEC = importlib.util.spec_from_file_location("download_zenodo_dataset", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
download = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = download
SPEC.loader.exec_module(download)


def response(status: int, payload: bytes | dict[str, object], **headers: str) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.headers.update(headers)
    result.url = "https://zenodo.example/test"
    result._content = (
        json.dumps(payload).encode("utf-8") if isinstance(payload, dict) else payload
    )
    result._content_consumed = True
    return result


class QueueSession:
    def __init__(self, responses: list[requests.Response]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"Unexpected request: {method} {url}")
        return self.responses.pop(0)


class DownloadZenodoDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.payloads = {0: b"level zero pixels", 2: b"level two pixels"}
        self.manifest = self.root / "manifest.csv"
        self.write_manifest()

    def rows(self) -> list[dict[str, object]]:
        alias = "TumorQuantAI_LymphomaWSI_001"
        rows = []
        for level, payload in self.payloads.items():
            rows.append(
                {
                    "alias": alias,
                    "level": level,
                    "source_mpp": 0.261780,
                    "zenodo_filename": f"{alias}_L{level}_rgb.tif",
                    "dataset_path": f"slides/{alias}/1_L{level}_rgb.tif",
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "md5": hashlib.md5(payload, usedforsecurity=False).hexdigest(),
                }
            )
        return rows

    def write_manifest(self, rows: list[dict[str, object]] | None = None) -> None:
        values = rows if rows is not None else self.rows()
        with self.manifest.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=values[0].keys())
            writer.writeheader()
            writer.writerows(values)

    def record_payload(self) -> dict[str, object]:
        return {
            "files": [
                {
                    "key": row["zenodo_filename"],
                    "size": row["size_bytes"],
                    "checksum": f"md5:{row['md5']}",
                    "links": {
                        "self": f"https://zenodo.example/files/{row['zenodo_filename']}"
                    },
                }
                for row in self.rows()
            ]
        }

    def test_offline_dry_run_validates_without_writes(self) -> None:
        output = self.root / "dataset"
        result = download.download_dataset(
            manifest=self.manifest,
            record=None,
            output_dir=output,
            dry_run=True,
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["file_count"], 2)
        self.assertFalse(output.exists())

    def test_downloads_record_files_and_reconstructs_layout(self) -> None:
        session = QueueSession(
            [
                response(200, self.record_payload()),
                response(200, self.payloads[0]),
                response(200, self.payloads[2]),
            ]
        )
        output = self.root / "dataset"
        result = download.download_dataset(
            manifest=self.manifest,
            record="10.5281/zenodo.12345",
            output_dir=output,
            api_url="https://zenodo.example/api",
            retries=0,
            session=session,
        )
        self.assertEqual(result["statuses"], {"downloaded": 2})
        alias = "TumorQuantAI_LymphomaWSI_001"
        self.assertEqual(
            (output / "slides" / alias / "1_L0_rgb.tif").read_bytes(),
            self.payloads[0],
        )
        self.assertEqual(
            (output / "slides" / alias / "1_L2_rgb.tif").read_bytes(),
            self.payloads[2],
        )
        self.assertEqual(
            (output / download.DEFAULT_MANIFEST_NAME).read_bytes(),
            self.manifest.read_bytes(),
        )
        with (output / download.LOCAL_SAMPLES_NAME).open(
            newline="", encoding="utf-8"
        ) as handle:
            samples = list(csv.DictReader(handle))
        self.assertEqual(
            samples,
            [{
                "sample_id": alias,
                "slide_path": f"{alias}/1_L0_rgb.tif",
            }],
        )
        checksum_lines = (output / download.LOCAL_CHECKSUMS_NAME).read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(len(checksum_lines), 2)
        for row, line in zip(self.rows(), checksum_lines, strict=True):
            self.assertEqual(
                line, "{}  {}".format(row["sha256"], row["dataset_path"])
            )

        resumed = download.download_dataset(
            manifest=self.manifest,
            record="12345",
            output_dir=output,
            api_url="https://zenodo.example/api",
            retries=0,
            session=QueueSession([response(200, self.record_payload())]),
        )
        self.assertEqual(resumed["statuses"], {"verified-existing": 2})
        self.assertEqual(
            set(resumed["local_artifacts"].values()), {"verified-existing"}
        )

    def test_resumes_a_partial_file_with_range_request(self) -> None:
        output = self.root / "dataset"
        alias = "TumorQuantAI_LymphomaWSI_001"
        target = output / "slides" / alias / "1_L0_rgb.tif"
        target.parent.mkdir(parents=True)
        part = target.with_name(f".{target.name}.part")
        offset = 5
        part.write_bytes(self.payloads[0][:offset])
        session = QueueSession(
            [
                response(200, self.record_payload()),
                response(
                    206,
                    self.payloads[0][offset:],
                    **{"Content-Range": f"bytes {offset}-{len(self.payloads[0]) - 1}/{len(self.payloads[0])}"},
                ),
                response(200, self.payloads[2]),
            ]
        )
        download.download_dataset(
            manifest=self.manifest,
            record="12345",
            output_dir=output,
            api_url="https://zenodo.example/api",
            retries=0,
            session=session,
        )
        self.assertEqual(target.read_bytes(), self.payloads[0])
        self.assertEqual(session.calls[1][2]["headers"], {"Range": f"bytes={offset}-"})

    def test_complete_verified_partial_is_promoted_without_network_transfer(self) -> None:
        output = self.root / "dataset"
        alias = "TumorQuantAI_LymphomaWSI_001"
        target = output / "slides" / alias / "1_L0_rgb.tif"
        target.parent.mkdir(parents=True)
        target.with_name(f".{target.name}.part").write_bytes(self.payloads[0])
        session = QueueSession(
            [response(200, self.record_payload()), response(200, self.payloads[2])]
        )
        result = download.download_dataset(
            manifest=self.manifest,
            record="12345",
            output_dir=output,
            api_url="https://zenodo.example/api",
            retries=0,
            session=session,
        )
        self.assertEqual(result["statuses"], {"verified-partial": 1, "downloaded": 1})
        self.assertEqual(target.read_bytes(), self.payloads[0])

    def test_rejects_existing_symlink_even_when_it_points_inside_output(self) -> None:
        output = self.root / "dataset"
        alias = "TumorQuantAI_LymphomaWSI_001"
        target = output / "slides" / alias / "1_L0_rgb.tif"
        target.parent.mkdir(parents=True)
        decoy = output / "decoy.tif"
        decoy.write_bytes(b"decoy")
        target.symlink_to(decoy)
        with self.assertRaisesRegex(download.DownloadError, "Refusing symlink"):
            download.download_dataset(
                manifest=self.manifest,
                record=None,
                output_dir=output,
                dry_run=True,
            )

    def test_rejects_manifest_path_or_name_substitution(self) -> None:
        rows = self.rows()
        rows[0]["dataset_path"] = "../../private"
        self.write_manifest(rows)
        with self.assertRaisesRegex(download.DownloadError, "Unsafe or inconsistent"):
            download.download_dataset(
                manifest=self.manifest,
                record=None,
                output_dir=self.root / "dataset",
                dry_run=True,
            )

    def test_rejects_remote_checksum_mismatch_before_download(self) -> None:
        payload = self.record_payload()
        payload["files"][0]["checksum"] = "md5:" + ("0" * 32)
        session = QueueSession([response(200, payload)])
        with self.assertRaisesRegex(download.DownloadError, "Remote MD5 mismatch"):
            download.download_dataset(
                manifest=self.manifest,
                record="12345",
                output_dir=self.root / "dataset",
                api_url="https://zenodo.example/api",
                retries=0,
                session=session,
            )

    def test_rejects_nonfinite_or_inconsistent_source_mpp(self) -> None:
        variants = (
            (float("nan"), 0.261780),
            (float("inf"), 0.261780),
            (0.261780, 0.500000),
        )
        for first, second in variants:
            with self.subTest(first=first, second=second):
                rows = self.rows()
                rows[0]["source_mpp"] = first
                rows[1]["source_mpp"] = second
                self.write_manifest(rows)
                with self.assertRaises(download.DownloadError):
                    download.download_dataset(
                        manifest=self.manifest,
                        record=None,
                        output_dir=self.root / "dataset",
                        dry_run=True,
                    )

    def test_rejects_metadata_symlink_before_downloading_slides(self) -> None:
        output = self.root / "dataset"
        output.mkdir()
        decoy = self.root / "decoy.csv"
        decoy.write_text("keep me\n", encoding="utf-8")
        (output / download.LOCAL_SAMPLES_NAME).symlink_to(decoy)
        session = QueueSession([response(200, self.record_payload())])
        with self.assertRaisesRegex(download.DownloadError, "symlink"):
            download.download_dataset(
                manifest=self.manifest,
                record="12345",
                output_dir=output,
                api_url="https://zenodo.example/api",
                retries=0,
                session=session,
            )
        self.assertEqual(decoy.read_text(encoding="utf-8"), "keep me\n")
        self.assertFalse((output / "slides").exists())

    def test_rejects_remote_manifest_size_or_checksum_mismatch(self) -> None:
        manifest_payload = self.manifest.read_bytes()
        cases = (
            (len(manifest_payload) + 1, hashlib.md5(
                manifest_payload, usedforsecurity=False
            ).hexdigest(), "size"),
            (len(manifest_payload), "0" * 32, "MD5"),
        )
        for advertised_size, advertised_md5, message in cases:
            with self.subTest(message=message):
                record_payload = self.record_payload()
                record_payload["files"].append(
                    {
                        "key": download.DEFAULT_MANIFEST_NAME,
                        "size": advertised_size,
                        "checksum": f"md5:{advertised_md5}",
                        "links": {
                            "self": "https://zenodo.example/files/manifest.csv"
                        },
                    }
                )
                session = QueueSession(
                    [response(200, record_payload), response(200, manifest_payload)]
                )
                with self.assertRaisesRegex(download.DownloadError, message):
                    download.download_dataset(
                        manifest=None,
                        record="12345",
                        output_dir=self.root / "dataset",
                        api_url="https://zenodo.example/api",
                        dry_run=True,
                        retries=0,
                        session=session,
                    )

    def test_oversized_stream_is_rejected_without_unbounded_write(self) -> None:
        output = self.root / "dataset"
        oversized = self.payloads[0] + b"unexpected-extra-bytes"
        session = QueueSession(
            [
                response(200, self.record_payload()),
                response(200, oversized),
            ]
        )
        with self.assertRaisesRegex(download.DownloadError, "Could not complete"):
            download.download_dataset(
                manifest=self.manifest,
                record="12345",
                output_dir=output,
                api_url="https://zenodo.example/api",
                retries=0,
                session=session,
            )
        alias = "TumorQuantAI_LymphomaWSI_001"
        partial = output / "slides" / alias / ".1_L0_rgb.tif.part"
        self.assertLessEqual(partial.stat().st_size, len(self.payloads[0]))


if __name__ == "__main__":
    unittest.main()
