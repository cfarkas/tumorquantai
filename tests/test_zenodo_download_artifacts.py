from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).parents[1]
SCRIPT = REPOSITORY_ROOT / "scripts" / "generate_zenodo_download_files.py"
SPEC = importlib.util.spec_from_file_location("generate_zenodo_download_files", SCRIPT)
assert SPEC and SPEC.loader
generator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generator
SPEC.loader.exec_module(generator)


def test_committed_download_artifacts_are_current() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_subsets_match_authoritative_manifest() -> None:
    rows, _ = generator.load_manifest(generator.MANIFEST_PATH)
    by_alias = {row.alias: row for row in rows}
    artifacts = generator.generated_artifacts()

    expected_counts = {"one": 1, "first_four": 4, "all_21": 21}
    expected_aliases = {
        "one": list(generator.ONE_SAMPLE),
        "first_four": list(generator.FIRST_FOUR_SAMPLES),
        "all_21": sorted(by_alias),
    }
    for subset, count in expected_counts.items():
        url_path = generator.OUTPUT_DIRECTORY / f"zenodo_{subset}.urls.txt"
        checksum_path = generator.OUTPUT_DIRECTORY / f"checksums_{subset}.sha256"
        urls = artifacts[url_path].splitlines()
        checksums = artifacts[checksum_path].splitlines()

        assert len(urls) == count
        assert len(checksums) == count
        assert [
            line.removeprefix(
                f"https://zenodo.org/records/{generator.RECORD_ID}/files/"
            ).removesuffix("?download=1")
            for line in urls
        ] == [by_alias[alias].zenodo_filename for alias in expected_aliases[subset]]
        assert checksums == [
            f"{by_alias[alias].sha256}  {by_alias[alias].zenodo_filename}"
            for alias in expected_aliases[subset]
        ]


def test_check_mode_detects_generated_file_drift(tmp_path: Path) -> None:
    artifacts = generator.generated_artifacts(
        generator.MANIFEST_PATH,
        tmp_path,
    )
    for path, text in artifacts.items():
        path.write_text(text, encoding="utf-8")
    assert not generator.synchronize(
        check=True,
        manifest_path=generator.MANIFEST_PATH,
        output_directory=tmp_path,
    )

    changed = tmp_path / "zenodo_one.urls.txt"
    changed.write_text("changed\n", encoding="utf-8")
    assert generator.synchronize(
        check=True,
        manifest_path=generator.MANIFEST_PATH,
        output_directory=tmp_path,
    ) == [changed]


def test_cli_check_returns_nonzero_on_drift(monkeypatch, capsys) -> None:
    changed = (
        generator.REPOSITORY_ROOT
        / "examples"
        / "lymphoma"
        / "zenodo_one.urls.txt"
    )
    monkeypatch.setattr(
        generator, "synchronize", lambda **_kwargs: [changed]
    )
    assert generator.main(["--check"]) == 1
    captured = capsys.readouterr()
    assert "out of date: examples/lymphoma/zenodo_one.urls.txt" in captured.err
