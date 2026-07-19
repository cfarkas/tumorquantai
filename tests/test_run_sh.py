from __future__ import annotations

import os
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).parents[1]
RUNNER = REPOSITORY / "run.sh"
PINNED_REVISION = "cde2eee81af9e39b03802fc33d4f284733b5ee5e"


class RunShModeTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.input_dir = self.root / "input"
        self.output_dir = self.root / "output"
        self.input_dir.mkdir()
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.capture = self.root / "nextflow.args"
        fake_nextflow = self.bin_dir / "nextflow"
        fake_nextflow.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$@\" > \"${NXF_CAPTURE:?}\"\n",
            encoding="utf-8",
        )
        fake_nextflow.chmod(0o755)

    def invoke(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.bin_dir}:{environment['PATH']}",
                "HOME": str(self.root / "home"),
                "HF_TOKEN": "test-token",
                "NXF_CAPTURE": str(self.capture),
            }
        )
        command = [
            "bash",
            str(RUNNER),
            "--input-dir",
            str(self.input_dir),
            "--output-dir",
            str(self.output_dir),
            "--profile",
            "local",
            "--work-dir",
            str(self.root / "work"),
            "--no-resume",
            *arguments,
        ]
        return subprocess.run(command, text=True, capture_output=True, env=environment)

    def captured_value(self, option: str) -> str:
        arguments = self.capture.read_text(encoding="utf-8").splitlines()
        return arguments[arguments.index(option) + 1]

    def test_default_is_full_and_pinned_revision_is_forwarded(self) -> None:
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("mode:       full", result.stdout)
        self.assertEqual(self.captured_value("--percent_slide"), "100")
        self.assertEqual(self.captured_value("--histoplus_revision"), PINNED_REVISION)
        self.assertEqual(self.captured_value("--docker_shm_size"), "2g")

    def test_fast_defaults_to_ten_percent(self) -> None:
        result = self.invoke("--fast")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("mode:       fast", result.stdout)
        self.assertEqual(self.captured_value("--percent_slide"), "10")

    def test_fast_accepts_explicit_sub_hundred_percent(self) -> None:
        result = self.invoke("--mode", "fast", "--percent-slide", "2.5")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.captured_value("--percent_slide"), "2.5")

    def test_standalone_percent_remains_compatible_and_selects_fast(self) -> None:
        result = self.invoke("--percent-slide", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("mode:       fast", result.stdout)
        self.assertEqual(self.captured_value("--percent_slide"), "1")

    def test_full_rejects_partial_percent(self) -> None:
        result = self.invoke("--full", "--percent-slide", "10")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--mode full requires --percent-slide 100", result.stderr)

    def test_conflicting_mode_aliases_are_rejected(self) -> None:
        result = self.invoke("--full", "--fast")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Conflicting modes", result.stderr)

    def test_fast_rejects_hundred_percent(self) -> None:
        result = self.invoke("--fast", "--percent-slide", "100")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--mode fast requires --percent-slide below 100", result.stderr)

    def test_local_histoplus_weight_is_validated_and_forwarded(self) -> None:
        weight = self.root / "histoplus_cellvit_segmentor_20x.pt"
        weight.write_bytes(b"test-weight")
        result = self.invoke("--histoplus-weight-file", str(weight))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.captured_value("--histoplus_weight_file"), str(weight.resolve())
        )

        self.assertEqual(
            self.captured_value("--histoplus_weight_sha256"),
            hashlib.sha256(b"test-weight").hexdigest(),
        )

    def test_missing_local_histoplus_weight_is_rejected(self) -> None:
        result = self.invoke("--histoplus-weight-file", str(self.root / "missing.pt"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("HistoPLUS weight file does not exist", result.stderr)

    def test_source_slide_mpp_is_validated_and_forwarded(self) -> None:
        result = self.invoke("--slide-mpp", "0.261780")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.captured_value("--slide_mpp"), "0.261780")
        self.assertIn("source mpp: 0.261780", result.stdout)

    def test_invalid_source_slide_mpp_is_rejected(self) -> None:
        result = self.invoke("--slide-mpp", "0")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--slide-mpp must be numeric and > 0", result.stderr)

    def test_revision_must_be_an_immutable_commit(self) -> None:
        result = self.invoke("--histoplus-revision", "main")
        self.assertEqual(result.returncode, 2)
        self.assertIn("immutable full 40-hex commit SHA", result.stderr)

    def test_custom_docker_shm_size_is_validated_and_forwarded(self) -> None:
        result = self.invoke("--shm-size", "4g")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.captured_value("--docker_shm_size"), "4g")

    def test_invalid_docker_shm_size_is_rejected(self) -> None:
        result = self.invoke("--shm-size", "2g --privileged")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--shm-size must be", result.stderr)

    def test_protected_parameters_cannot_bypass_mode_after_separator(self) -> None:
        result = self.invoke("--full", "--", "--percent_slide", "10")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Pass protected workflow parameters", result.stderr)


if __name__ == "__main__":
    unittest.main()
