from __future__ import annotations

import csv
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import tifffile


REPOSITORY = Path(__file__).parents[1]
CLI = REPOSITORY / "tumorquantai"
sys.path.insert(0, str(REPOSITORY / "bin"))
import tumorquantai_core as core  # noqa: E402


def cli_environment(tmp_path: Path, **updates: str) -> dict[str, str]:
    environment = os.environ.copy()
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    environment.update({"HOME": str(home), "PYTHONUNBUFFERED": "1"})
    environment.pop("HF_TOKEN", None)
    environment.pop("HF_TOKEN_FILE", None)
    environment.pop("TUMORQUANTAI_HF_TOKEN_FILE", None)
    environment.pop("HISTOPLUS_WEIGHT_FILE", None)
    environment.update(updates)
    return environment


def invoke(tmp_path: Path, *arguments: str, environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI), *arguments], cwd=REPOSITORY, text=True, capture_output=True,
        env=environment or cli_environment(tmp_path), check=False,
    )


def fake_nextflow(tmp_path: Path, exit_code: int = 0) -> tuple[dict[str, str], Path]:
    executable_dir = tmp_path / "bin"
    executable_dir.mkdir()
    capture = tmp_path / "nextflow.args"
    executable = executable_dir / "nextflow"
    executable.write_text(
        "#!/bin/sh\n"
        "if [ -n \"${TQA_ENV_CAPTURE:-}\" ]; then env > \"$TQA_ENV_CAPTURE\"; fi\n"
        "printf '%s\\n' \"$@\" > \"$TQA_CAPTURE\"\n"
        "exit \"${TQA_NXF_EXIT:-0}\"\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    fake_findmnt = executable_dir / "findmnt"
    fake_findmnt.write_text(
        "#!/bin/sh\nprintf '/tmp/tumorquantai-test-mount ext4 /dev/test-mount\\n'\n",
        encoding="utf-8",
    )
    fake_findmnt.chmod(0o755)
    environment = cli_environment(
        tmp_path,
        PATH=f"{executable_dir}:{os.environ['PATH']}",
        TQA_CAPTURE=str(capture),
        TQA_NXF_EXIT=str(exit_code),
    )
    return environment, capture


def option_value(arguments: list[str], name: str) -> str:
    return arguments[arguments.index(name) + 1]


def write_patch_tiff(path: Path, *, mpp: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    options: dict[str, object] = {"photometric": "rgb"}
    if mpp is not None:
        options.update({
            "resolution": (10_000.0 / mpp, 10_000.0 / mpp),
            "resolutionunit": "CENTIMETER",
        })
    tifffile.imwrite(path, np.zeros((16, 16, 3), dtype=np.uint8), **options)


@pytest.mark.parametrize(
    "command", [None, "doctor", "demo", "inspect", "run", "status", "report", "quickstart"]
)
def test_every_help_command_is_available(tmp_path: Path, command: str | None) -> None:
    arguments = ["--help"] if command is None else [command, "--help"]
    result = invoke(tmp_path, *arguments)
    assert result.returncode == core.EXIT_OK, result.stderr
    assert "usage:" in result.stdout


@pytest.mark.parametrize("command", ("run", "quickstart"))
def test_execution_help_shows_cpu_and_gpu_aliases(
    tmp_path: Path, command: str,
) -> None:
    result = invoke(tmp_path, command, "--help")
    assert result.returncode == core.EXIT_OK
    assert "--cpu" in result.stdout
    assert "--gpu" in result.stdout
    assert "--profile" in result.stdout


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["run", "/input", "--output", "/output"], "auto"),
        (["run", "/input", "--output", "/output", "--cpu"], "cpu"),
        (["run", "/input", "--output", "/output", "--gpu"], "gpu"),
        (["quickstart", "--output", "/output"], "auto"),
        (["quickstart", "--output", "/output", "--cpu"], "cpu"),
        (["quickstart", "--output", "/output", "--gpu"], "gpu"),
        (["quickstart", "--output", "/output", "--profile", "local"], "local"),
    ],
)
def test_execution_aliases_map_to_existing_profile(
    arguments: list[str], expected: str,
) -> None:
    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_profile_test")
    parsed = namespace["build_parser"]().parse_args(arguments)
    assert parsed.profile == expected


def test_explicit_cpu_skips_gpu_auto_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_cpu_test")

    def unexpected_probe(*_args: object, **_kwargs: object) -> None:
        pytest.fail("explicit CPU selection must not probe NVIDIA or Docker")

    monkeypatch.setattr(namespace["subprocess"], "run", unexpected_probe)
    assert namespace["resolve_profile"]("cpu") == "cpu"


@pytest.mark.parametrize(
    "arguments",
    [
        ["run", "/input", "--output", "/output", "--cpu", "--gpu"],
        ["quickstart", "--output", "/output", "--cpu", "--gpu"],
        ["quickstart", "--output", "/output", "--profile", "cpu", "--gpu"],
    ],
)
def test_execution_aliases_are_mutually_exclusive(
    tmp_path: Path, arguments: list[str],
) -> None:
    result = invoke(tmp_path, *arguments)
    assert result.returncode == core.EXIT_USAGE
    assert "not allowed with argument" in result.stderr


def test_missing_command_uses_stable_usage_exit(tmp_path: Path) -> None:
    result = invoke(tmp_path)
    assert result.returncode == core.EXIT_USAGE
    assert "usage:" in result.stderr


def test_doctor_json_has_required_offline_checks_and_no_absolute_paths(tmp_path: Path) -> None:
    result = invoke(tmp_path, "doctor", "--json")
    assert result.returncode in {core.EXIT_OK, core.EXIT_PREFLIGHT}
    payload = json.loads(result.stdout)
    codes = {row["code"] for row in payload["checks"]}
    assert {
        "TQA-OS", "TQA-ARCH", "TQA-JAVA", "TQA-NEXTFLOW", "TQA-DOCKER-CLI",
        "TQA-DOCKER-DAEMON", "TQA-GPU", "TQA-CPU", "TQA-AUTH", "TQA-CACHE",
        "TQA-STORAGE",
    }.issubset(codes)
    assert str(tmp_path) not in result.stdout


def test_doctor_rejects_explicit_root_backed_output(tmp_path: Path) -> None:
    unsafe_output = tmp_path / "root-backed-output"
    unsafe_cache = core.associated_cache_directory(unsafe_output)
    result = invoke(tmp_path, "doctor", "--output", str(unsafe_output), "--json")
    assert result.returncode == core.EXIT_PREFLIGHT
    payload = json.loads(result.stdout)
    storage = next(row for row in payload["checks"] if row["code"] == "TQA-STORAGE")
    assert storage["status"] == "FAIL"
    assert "non-root mounted filesystem" in storage["detail"]
    assert "verified non-root mount" in storage["next_action"]
    assert not unsafe_output.exists()
    assert not unsafe_cache.exists()


def test_demo_exercises_success_failure_zero_status_and_report(tmp_path: Path) -> None:
    output = tmp_path / "demo"
    result = invoke(tmp_path, "demo", "--output", str(output))
    assert result.returncode == core.EXIT_OK, result.stderr
    assert "TumorQuantAI structural demo complete." in result.stdout
    assert "No HistoPLUS inference ran" in result.stdout

    status = invoke(tmp_path, "status", str(output), "--json")
    payload = json.loads(status.stdout)
    assert payload["counts"] == {
        "completed": 2,
        "failed": 1,
        "incomplete": 0,
        "excluded": 0,
        "pending": 0,
        "biological_zero": 1,
    }
    assert payload["samples"]["biological_zero"] == ["case_zero_1"]
    assert payload["first_log"] == "workflow_metadata/logs/case_fail_1.log"

    report = (output / "START_HERE.html").read_text(encoding="utf-8")
    assert "STRUCTURAL SOFTWARE DEMO" in report
    assert "never represented as biological zeroes" in report
    assert ">PASS<" in report and ">FAIL<" in report
    assert str(tmp_path) not in report
    assert (output / "aggregated_celltypes/sample_aggregation_audit.csv").is_file()
    assert (output / "tumorquantai_report.json").is_file()
    manifests = (
        (output / "workflow_metadata/slides.tsv").read_text(encoding="utf-8")
        + (output / "workflow_metadata/slides.json").read_text(encoding="utf-8")
    )
    assert "tumorquantai-demo-" not in manifests
    assert "/tmp/" not in manifests
    assert "synthetic_fixture/" in manifests


def test_inspect_is_model_free_and_writes_reviewable_manifest(tmp_path: Path) -> None:
    output = tmp_path / "inspection"
    result = invoke(
        tmp_path, "inspect", str(REPOSITORY / "tests/fixtures"),
        "--output", str(output), "--source-mpp", "0.261780",
    )
    assert result.returncode == core.EXIT_OK, result.stderr
    assert "No inference ran" in result.stdout
    rows = list(csv.DictReader((output / "inspection_manifest.csv").open(encoding="utf-8")))
    assert [row["sample_id"] for row in rows] == ["case_a_1", "case_fail_1"]
    assert all(row["physical_scale_ready"] == "True" for row in rows)
    assert all(row["l2_exists"] == "True" for row in rows)
    assert (output / "inspection.json").is_file()
    assert (output / "INSPECTION.html").is_file()


def test_inspect_with_no_primary_slides_has_stable_input_exit(tmp_path: Path) -> None:
    empty = tmp_path / "empty-input"
    empty.mkdir()
    result = invoke(tmp_path, "inspect", str(empty), "--output", str(tmp_path / "inspection"))
    assert result.returncode == core.EXIT_INPUT
    assert "No primary slides matched" in result.stderr
    assert "ERROR: ERROR:" not in result.stderr


def test_inspect_refuses_equal_or_nested_output(tmp_path: Path) -> None:
    input_root = tmp_path / "slides"
    shutil.copytree(REPOSITORY / "tests/fixtures", input_root)
    for output in (input_root, input_root / "generated-inspection"):
        result = invoke(
            tmp_path, "inspect", str(input_root), "--output", str(output),
            "--source-mpp", "0.261780",
        )
        assert result.returncode == core.EXIT_PREFLIGHT
        assert "nested inside" in result.stderr


def test_filesystem_type_errors_use_stable_preflight_exit(tmp_path: Path) -> None:
    output = tmp_path / "not-a-directory"
    output.write_text("fixture", encoding="utf-8")
    result = invoke(tmp_path, "demo", "--output", str(output))
    assert result.returncode == core.EXIT_PREFLIGHT
    assert "Traceback" not in result.stderr


def test_implausible_generic_tiff_resolution_does_not_establish_mpp(tmp_path: Path) -> None:
    input_root = tmp_path / "slides" / "case"
    input_root.mkdir(parents=True)
    tifffile.imwrite(
        input_root / "1_L0_rgb.tif",
        np.zeros((8, 8, 3), dtype=np.uint8),
        photometric="rgb", resolution=(72, 72), resolutionunit="INCH",
    )
    inferred = core.inspect_inputs(tmp_path / "slides", tmp_path / "inferred")
    assert inferred["summary"]["missing_source_mpp"] == 1
    assert inferred["slides"][0]["source_mpp"] is None
    assert "implausible" in inferred["slides"][0]["metadata_reader"]
    supplied = core.inspect_inputs(
        tmp_path / "slides", tmp_path / "supplied", source_mpp=0.261780,
    )
    assert supplied["summary"]["missing_source_mpp"] == 0


def test_embedded_tiff_mpp_accepts_matching_resolution_axes(tmp_path: Path) -> None:
    input_root = tmp_path / "matching-axes" / "case"
    input_root.mkdir(parents=True)
    tifffile.imwrite(
        input_root / "1_L0_rgb.tif",
        np.zeros((8, 8, 3), dtype=np.uint8),
        photometric="rgb", resolution=(40_000, 40_000),
        resolutionunit="CENTIMETER",
    )

    inspected = core.inspect_inputs(
        tmp_path / "matching-axes", tmp_path / "matching-inspection",
    )

    assert inspected["summary"]["missing_source_mpp"] == 0
    assert inspected["slides"][0]["source_mpp"] == pytest.approx(0.25)
    assert inspected["slides"][0]["source_mpp_provenance"] == "embedded TIFF metadata"


def test_embedded_tiff_mpp_rejects_conflicting_axes_but_explicit_override_wins(
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "conflicting-axes" / "case"
    input_root.mkdir(parents=True)
    tifffile.imwrite(
        input_root / "1_L0_rgb.tif",
        np.zeros((8, 8, 3), dtype=np.uint8),
        photometric="rgb", resolution=(40_000, 20_000),
        resolutionunit="CENTIMETER",
    )

    inferred = core.inspect_inputs(
        tmp_path / "conflicting-axes", tmp_path / "conflicting-inspection",
    )
    assert inferred["summary"]["missing_source_mpp"] == 1
    assert inferred["slides"][0]["source_mpp"] is None
    assert "anisotropic" in inferred["slides"][0]["metadata_reader"]

    supplied = core.inspect_inputs(
        tmp_path / "conflicting-axes", tmp_path / "supplied-inspection",
        source_mpp=0.4,
    )
    assert supplied["summary"]["missing_source_mpp"] == 0
    assert supplied["slides"][0]["source_mpp"] == pytest.approx(0.4)
    assert supplied["slides"][0]["source_mpp_provenance"] == "supplied"


@pytest.mark.parametrize("value", ["inf", "-inf", "nan"])
def test_nonfinite_explicit_mpp_is_rejected_with_usage_exit(
    tmp_path: Path, value: str,
) -> None:
    result = invoke(
        tmp_path, "inspect", str(REPOSITORY / "tests/fixtures"),
        "--output", str(tmp_path / "inspection"), f"--source-mpp={value}",
    )
    assert result.returncode == core.EXIT_USAGE
    assert "finite number" in result.stderr
    assert not (tmp_path / "inspection").exists()


@pytest.mark.parametrize(
    ("preset", "percent", "continue_on_error", "expected_include"),
    [
        ("smoke", "1", "false", "case_a_1"),
        ("fast", "10", "true", None),
        ("full", "100", "true", None),
    ],
)
def test_presets_map_to_legacy_run_sh_and_safe_work_dir(
    tmp_path: Path, preset: str, percent: str,
    continue_on_error: str, expected_include: str | None,
) -> None:
    environment, capture = fake_nextflow(tmp_path)
    output = tmp_path / f"result-{preset}"
    result = invoke(
        tmp_path, "run", str(REPOSITORY / "tests/fixtures"),
        "--output", str(output), "--preset", preset,
        "--source-mpp", "0.261780", "--profile", "local", "--dry-run",
        environment=environment,
    )
    assert result.returncode == core.EXIT_OK, result.stderr
    arguments = capture.read_text(encoding="utf-8").splitlines()
    assert option_value(arguments, "--percent_slide") == percent
    assert option_value(arguments, "--continue_on_error") == continue_on_error
    assert option_value(arguments, "-work-dir") == str(output / ".tumorquantai-work")
    assert int(option_value(arguments, "--cpus")) <= 4
    assert option_value(arguments, "--max_parallel_slides") == "1"
    assert "-resume" in arguments
    if expected_include:
        assert option_value(arguments, "--include") == expected_include
    manifest = json.loads((output / core.RUN_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["preset"] == preset
    assert manifest["work_directory"] == ".tumorquantai-work"


def test_run_fails_closed_without_source_mpp(tmp_path: Path) -> None:
    environment, _capture = fake_nextflow(tmp_path)
    result = invoke(
        tmp_path, "run", str(REPOSITORY / "tests/fixtures"),
        "--output", str(tmp_path / "result"), "--profile", "local", "--dry-run",
        environment=environment,
    )
    assert result.returncode == core.EXIT_PREFLIGHT
    assert "Source MPP" in result.stderr


def test_patch_compatibility_reuses_full_cpu_run_and_records_resume_contract(
    tmp_path: Path,
) -> None:
    environment, capture = fake_nextflow(tmp_path)
    patches = tmp_path / "raw-patches"
    write_patch_tiff(patches / "case-a.tif")
    write_patch_tiff(patches / "nested" / "case-b.ome.tiff")
    output = tmp_path / "patch-results"

    result = invoke(
        tmp_path,
        "--patches", str(patches), "--paper-figures", "--output", str(output),
        "--source-mpp", "0.5", "--backend", "local", "--dry-run",
        environment=environment,
    )

    assert result.returncode == core.EXIT_OK, result.stderr
    arguments = capture.read_text(encoding="utf-8").splitlines()
    assert option_value(arguments, "--percent_slide") == "100"
    assert option_value(arguments, "--max_sampled_patches") == "0"
    assert option_value(arguments, "--convert_to_pyramidal") == "false"
    assert option_value(arguments, "--qc_patch_count") == "1"
    manifest = core.load_run_manifest(output)
    assert manifest["input_mode"] == "patches"
    assert manifest["preset"] == "full"
    assert manifest["sampling_percent"] == 100
    assert manifest["execution_profile"] == "cpu"
    assert len(manifest["selected_samples"]) == 2
    assert manifest["selected_samples"] == manifest["discovered_samples"]
    resume = manifest["resume_command"]
    assert resume.startswith(
        f"tumorquantai --patches {patches} --paper-figures --output {output}"
    )
    for expected in (
        "--preset full", "--percent-slide 100", "--max-sampled-patches 0",
        "--qc-patch-count 1", "--no-convert-to-pyramidal", "--profile cpu",
    ):
        assert expected in resume
    assert "--pattern" not in resume


def test_patch_compatibility_single_file_selects_only_that_file(
    tmp_path: Path,
) -> None:
    environment, _capture = fake_nextflow(tmp_path)
    patch_root = tmp_path / "file-mode"
    selected = patch_root / "chosen.ome.tif"
    write_patch_tiff(selected, mpp=0.5)
    write_patch_tiff(patch_root / "nested" / selected.name, mpp=0.5)
    output = patch_root / "results"

    result = invoke(
        tmp_path,
        "--patches", str(selected), "--paper-figures", "--output", str(output),
        "--backend", "local", "--dry-run", environment=environment,
    )

    assert result.returncode == core.EXIT_OK, result.stderr
    manifest = core.load_run_manifest(output)
    assert manifest["source_mpp_provenance"] == "per-input embedded TIFF metadata"
    assert manifest["selected_samples"] == [selected.name]
    assert manifest["discovered_samples"] == [selected.name]
    assert f"--patches {selected}" in manifest["resume_command"]
    assert "--include" not in manifest["resume_command"]


def test_patch_compatibility_uses_per_input_embedded_mpp_for_mixed_scales(
    tmp_path: Path,
) -> None:
    environment, capture = fake_nextflow(tmp_path)
    patches = tmp_path / "mixed-scale-patches"
    write_patch_tiff(patches / "field-40x.tif", mpp=0.25)
    write_patch_tiff(patches / "nested" / "field-4x.tiff", mpp=2.5)
    output = tmp_path / "mixed-scale-results"

    result = invoke(
        tmp_path,
        "--patches", str(patches), "--paper-figures", "--output", str(output),
        "--backend", "local", "--dry-run", environment=environment,
    )

    assert result.returncode == core.EXIT_OK, result.stderr
    arguments = capture.read_text(encoding="utf-8").splitlines()
    assert "--slide_mpp" not in arguments
    manifest = core.load_run_manifest(output)
    assert manifest["source_mpp"] is None
    assert manifest["source_mpp_values"] == [0.25, 2.5]
    assert manifest["source_mpp_provenance"] == "per-input embedded TIFF metadata"
    assert "--source-mpp" not in manifest["resume_command"]

    changed_scale = invoke(
        tmp_path,
        "--patches", str(patches), "--paper-figures", "--output", str(output),
        "--source-mpp", "0.5", "--backend", "local", "--dry-run",
        environment=environment,
    )
    assert changed_scale.returncode == core.EXIT_PREFLIGHT
    assert "incompatible source MPP" in changed_scale.stderr


def test_ordinary_slide_run_still_rejects_mixed_embedded_mpp(tmp_path: Path) -> None:
    environment, _capture = fake_nextflow(tmp_path)
    slides = tmp_path / "mixed-scale-slides"
    write_patch_tiff(slides / "first_L0_rgb.tif", mpp=0.25)
    write_patch_tiff(slides / "second_L0_rgb.tif", mpp=2.5)

    result = invoke(
        tmp_path,
        "run", str(slides), "--output", str(tmp_path / "ordinary-results"),
        "--preset", "full", "--backend", "local", "--profile", "cpu",
        "--dry-run", environment=environment,
    )

    assert result.returncode == core.EXIT_PREFLIGHT
    assert "inconsistent source MPP" in result.stderr


def test_patch_compatibility_preserves_physical_scale_fail_closed(
    tmp_path: Path,
) -> None:
    environment, _capture = fake_nextflow(tmp_path)
    patch = tmp_path / "missing-scale.tif"
    write_patch_tiff(patch)

    result = invoke(
        tmp_path,
        "--patches", str(patch), "--paper-figures", "--output",
        str(tmp_path / "missing-scale-results"), "--backend", "local", "--dry-run",
        environment=environment,
    )

    assert result.returncode == core.EXIT_PREFLIGHT
    assert "Source MPP is missing or unreadable" in result.stderr


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (("--preset", "smoke"), "preset full"),
        (("--preset", "fast"), "preset full"),
        (("--percent-slide", "99"), "must be 100"),
        (("--max-sampled-patches", "1"), "must be 0"),
        (("--qc-patch-count", "0"), "at least 1"),
        (("--convert-to-pyramidal",), "processed directly"),
        (("--pattern", "*.tif"), "incompatible with --patches"),
    ],
)
def test_patch_compatibility_rejects_incomplete_or_sampled_modes(
    tmp_path: Path, extra: tuple[str, ...], message: str,
) -> None:
    result = invoke(
        tmp_path,
        "--patches", str(tmp_path / "patches"), "--paper-figures", "--output",
        str(tmp_path / "result"), *extra,
    )
    assert result.returncode == core.EXIT_USAGE
    assert message in result.stderr
    assert not (tmp_path / "result").exists()


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (("--patches", "/patches", "--output", "/result"), "--paper-figures"),
        (("--paper-figures", "--output", "/result"), "--patches PATH"),
        (("--patches", "/patches", "--paper-figures"), "--output DIR"),
        (("run", "--patches", "/patches", "--paper-figures", "--output", "/result"), "top-level"),
    ],
)
def test_patch_compatibility_requires_exact_top_level_contract(
    tmp_path: Path, arguments: tuple[str, ...], message: str,
) -> None:
    result = invoke(tmp_path, *arguments)
    assert result.returncode == core.EXIT_USAGE
    assert message in result.stderr


def test_patch_input_mode_cannot_resume_as_an_ordinary_slide_run(
    tmp_path: Path,
) -> None:
    environment, _capture = fake_nextflow(tmp_path)
    patches = tmp_path / "mode-patches"
    write_patch_tiff(patches / "case.tif")
    output = tmp_path / "mode-results"
    patch_result = invoke(
        tmp_path,
        "--patches", str(patches), "--paper-figures", "--output", str(output),
        "--source-mpp", "0.5", "--backend", "local", "--dry-run",
        environment=environment,
    )
    assert patch_result.returncode == core.EXIT_OK, patch_result.stderr

    ordinary_result = invoke(
        tmp_path,
        "run", str(patches), "--output", str(output), "--pattern", "*.tif",
        "--preset", "full", "--source-mpp", "0.5", "--profile", "cpu",
        "--backend", "local", "--dry-run", environment=environment,
    )
    assert ordinary_result.returncode == core.EXIT_PREFLIGHT
    assert "input_mode" in ordinary_result.stderr


def test_incompatible_presets_cannot_mix_in_one_output(tmp_path: Path) -> None:
    environment, _capture = fake_nextflow(tmp_path)
    output = tmp_path / "result"
    common = [
        "run", str(REPOSITORY / "tests/fixtures"), "--output", str(output),
        "--source-mpp", "0.261780", "--profile", "local", "--dry-run",
    ]
    first = invoke(tmp_path, *common, "--preset", "smoke", environment=environment)
    assert first.returncode == core.EXIT_OK
    second = invoke(tmp_path, *common, "--preset", "fast", environment=environment)
    assert second.returncode == core.EXIT_PREFLIGHT
    assert "Refusing to mix incompatible runs" in second.stderr


def test_include_is_forwarded_and_resume_command_is_complete_and_private_in_json(tmp_path: Path) -> None:
    environment, capture = fake_nextflow(tmp_path)
    output = tmp_path / "result-fast"
    work = tmp_path / "selected-work"
    result = invoke(
        tmp_path, "run", str(REPOSITORY / "tests/fixtures"),
        "--output", str(output), "--preset", "fast", "--include", "case_a*",
        "--exclude", "does-not-match", "--pattern", "*_L0_rgb.tif",
        "--source-mpp", "0.261780", "--profile", "local", "--work-dir", str(work),
        "--dry-run", environment=environment,
    )
    assert result.returncode == core.EXIT_OK, result.stderr
    arguments = capture.read_text(encoding="utf-8").splitlines()
    assert option_value(arguments, "--include") == "case_a*"
    assert option_value(arguments, "--exclude") == "does-not-match"
    assert option_value(arguments, "--container_image") == core.CPU_CONTAINER
    assert option_value(arguments, "--histoplus_revision") == core.MODEL_REVISION
    assert option_value(arguments, "--histoplus_cache_dir").startswith(str(tmp_path))
    manifest = core.load_run_manifest(output)
    resume = manifest["resume_command"]
    for value in (str(REPOSITORY / "tests/fixtures"), str(output), str(work), "case_a*", "does-not-match", "*_L0_rgb.tif", "--profile local"):
        assert value in resume
    human = invoke(tmp_path, "status", str(output))
    assert str(output) in human.stdout
    shareable = json.loads(invoke(tmp_path, "status", str(output), "--json").stdout)
    assert str(output) not in shareable["resume_command"]
    assert "<absolute-path>" in shareable["resume_command"]


def test_resume_command_preserves_explicit_public_overrides_without_weight_path(
    tmp_path: Path,
) -> None:
    environment, _capture = fake_nextflow(tmp_path)
    output = tmp_path / "resume-public-overrides"
    private_weight = tmp_path / "private" / "weight.pt"
    result = invoke(
        tmp_path, "run", str(REPOSITORY / "tests/fixtures"),
        "--output", str(output), "--source-mpp", "0.261780",
        "--profile", "local", "--dry-run",
        "--overlap", "0.6", "--pyramidal-jpeg-q", "77",
        "--save-json", "--no-convert-to-pyramidal",
        "--local-weight", str(private_weight),
        environment=environment,
    )
    assert result.returncode == core.EXIT_OK, result.stderr

    resume = core.load_run_manifest(output)["resume_command"]
    for expected in (
        "--overlap 0.6",
        "--pyramidal-jpeg-q 77",
        "--save-json",
        "--no-convert-to-pyramidal",
    ):
        assert expected in resume
    assert resume.count("--overlap") == 1
    assert resume.count("--source-mpp") == 1
    assert "--local-weight" not in resume
    assert str(private_weight) not in resume


def test_protected_expert_override_is_rejected_before_output_creation(tmp_path: Path) -> None:
    environment, _capture = fake_nextflow(tmp_path)
    output = tmp_path / "protected"
    result = invoke(
        tmp_path, "run", str(REPOSITORY / "tests/fixtures"),
        "--output", str(output), "--source-mpp", "0.261780", "--profile", "local",
        "--dry-run", "--", "--output_dir", str(tmp_path / "escape"),
        environment=environment,
    )
    assert result.returncode == core.EXIT_USAGE
    assert "protected option" in result.stderr
    assert not output.exists()


@pytest.mark.parametrize(
    "expert",
    [
        "-c", "--with-docker", "--executor", "-process.executor=local",
        "-process.container=untrusted:latest", "--api-key=hf_do_not_echo_123456",
    ],
)
def test_config_and_secret_expert_options_are_rejected_without_output(
    tmp_path: Path, expert: str,
) -> None:
    environment, _capture = fake_nextflow(tmp_path)
    output = tmp_path / "protected"
    result = invoke(
        tmp_path, "run", str(REPOSITORY / "tests/fixtures"),
        "--output", str(output), "--source-mpp", "0.261780",
        "--profile", "local", "--dry-run", "--", expert,
        environment=environment,
    )
    assert result.returncode == core.EXIT_USAGE
    assert "do_not_echo" not in result.stdout + result.stderr
    assert not output.exists()


def test_expert_arguments_are_part_of_resume_compatibility(tmp_path: Path) -> None:
    environment, _capture = fake_nextflow(tmp_path)
    output = tmp_path / "expert-fingerprint"
    common = [
        "run", str(REPOSITORY / "tests/fixtures"), "--output", str(output),
        "--source-mpp", "0.261780", "--profile", "local", "--dry-run", "--",
    ]
    first = invoke(tmp_path, *common, "--tile_px=700", environment=environment)
    assert first.returncode == core.EXIT_OK, first.stderr
    before = (output / "workflow_metadata/preflight-inspection/inspection.json").read_bytes()
    second = invoke(tmp_path, *common, "--tile_px=840", environment=environment)
    assert second.returncode == core.EXIT_PREFLIGHT
    assert "expert_args_fingerprint" in second.stderr
    assert (output / "workflow_metadata/preflight-inspection/inspection.json").read_bytes() == before


def test_nonempty_unidentified_output_is_refused(tmp_path: Path) -> None:
    environment, _capture = fake_nextflow(tmp_path)
    output = tmp_path / "unrelated"
    output.mkdir()
    (output / "keep.txt").write_text("user file", encoding="utf-8")
    result = invoke(
        tmp_path, "run", str(REPOSITORY / "tests/fixtures"),
        "--output", str(output), "--source-mpp", "0.261780",
        "--profile", "local", "--dry-run", environment=environment,
    )
    assert result.returncode == core.EXIT_PREFLIGHT
    assert (output / "keep.txt").read_text(encoding="utf-8") == "user file"


def test_discovery_only_run_does_not_read_or_forward_credentials(tmp_path: Path) -> None:
    environment, capture = fake_nextflow(tmp_path)
    environment_capture = tmp_path / "nextflow.env"
    missing_token = tmp_path / "private" / "missing-token"
    missing_weight = tmp_path / "private" / "missing-weight.pt"
    secret_value = "hf_discovery_must_not_forward_123456"
    environment.update({
        "TQA_ENV_CAPTURE": str(environment_capture),
        "TUMORQUANTAI_HF_TOKEN_FILE": str(missing_token),
        "HISTOPLUS_WEIGHT_FILE": str(missing_weight),
        "HF_TOKEN": secret_value,
    })
    output = tmp_path / "dry-result"
    result = invoke(
        tmp_path, "run", str(REPOSITORY / "tests/fixtures"),
        "--output", str(output), "--source-mpp", "0.261780",
        "--profile", "local", "--dry-run", environment=environment,
    )
    assert result.returncode == core.EXIT_OK, result.stderr
    combined = result.stdout + result.stderr + capture.read_text(encoding="utf-8")
    inherited = environment_capture.read_text(encoding="utf-8")
    manifest = (output / core.RUN_MANIFEST).read_text(encoding="utf-8")
    assert secret_value not in combined + inherited + manifest
    assert str(missing_token) not in combined + inherited + manifest
    assert str(missing_weight) not in combined + inherited + manifest
    assert "not checked for discovery-only dry run" in manifest


def test_direct_run_without_model_access_has_stable_exit_code(tmp_path: Path) -> None:
    environment, _capture = fake_nextflow(tmp_path)
    result = invoke(
        tmp_path, "run", str(REPOSITORY / "tests/fixtures"),
        "--output", str(tmp_path / "result"), "--source-mpp", "0.261780",
        "--profile", "local", environment=environment,
    )
    assert result.returncode == core.EXIT_MODEL
    assert "Authorized HistoPLUS access" in result.stderr


def test_real_run_refuses_root_filesystem_output_before_model_access(tmp_path: Path) -> None:
    output = tmp_path / "unsafe-real-output"
    result = invoke(
        tmp_path, "run", str(REPOSITORY / "tests/fixtures"),
        "--output", str(output), "--source-mpp", "0.261780", "--profile", "local",
        environment=cli_environment(tmp_path),
    )
    assert result.returncode == core.EXIT_PREFLIGHT
    assert "non-root mounted filesystem" in result.stderr
    assert not output.exists()


def test_real_run_refuses_work_directory_inside_repository(tmp_path: Path) -> None:
    environment, _capture = fake_nextflow(tmp_path)
    output = tmp_path / "simulated-mounted-output"
    result = invoke(
        tmp_path, "run", str(REPOSITORY / "tests/fixtures"),
        "--output", str(output), "--work-dir", str(REPOSITORY / "unsafe-test-work"),
        "--source-mpp", "0.261780", "--profile", "local",
        environment=environment,
    )
    assert result.returncode == core.EXIT_PREFLIGHT
    assert "inside the repository" in result.stderr
    assert not (REPOSITORY / "unsafe-test-work").exists()


def test_zero_completed_samples_returns_workflow_exit_even_when_nextflow_returns_zero(tmp_path: Path) -> None:
    environment, _capture = fake_nextflow(tmp_path)
    environment["HF_TOKEN"] = "hf_fixture_only_not_printed_123456"
    result = invoke(
        tmp_path, "run", str(REPOSITORY / "tests/fixtures"),
        "--output", str(tmp_path / "empty-result"), "--source-mpp", "0.261780",
        "--profile", "local", environment=environment,
    )
    assert result.returncode == core.EXIT_WORKFLOW
    assert "no sample completed" in result.stderr
    assert "fixture_only" not in result.stdout + result.stderr


def test_workflow_failure_has_stable_exit_code_and_never_prints_token(tmp_path: Path) -> None:
    environment, _capture = fake_nextflow(tmp_path, exit_code=1)
    token_value = "hf_this_must_never_appear_123456789"
    token = tmp_path / "private" / "hf_token"
    token.parent.mkdir()
    token.write_text(token_value, encoding="utf-8")
    token.chmod(0o600)
    environment["TUMORQUANTAI_HF_TOKEN_FILE"] = str(token)
    result = invoke(
        tmp_path, "run", str(REPOSITORY / "tests/fixtures"),
        "--output", str(tmp_path / "result"), "--source-mpp", "0.261780",
        "--profile", "local", environment=environment,
    )
    assert result.returncode == core.EXIT_WORKFLOW
    combined = result.stdout + result.stderr
    assert token_value not in combined
    assert str(token) not in combined


def test_local_weight_scrubs_unrelated_tokens_from_worker_environment(tmp_path: Path) -> None:
    environment, _capture = fake_nextflow(tmp_path)
    environment_capture = tmp_path / "nextflow.env"
    token = tmp_path / "private-token"
    token.write_text("hf_unrelated_secret_123456", encoding="utf-8")
    token.chmod(0o600)
    weight = tmp_path / "authorized-weight.pt"
    weight.write_bytes(b"authorized fixture")
    environment.update({
        "TQA_ENV_CAPTURE": str(environment_capture),
        "HF_TOKEN": "hf_unrelated_environment_123456",
        "TUMORQUANTAI_HF_TOKEN_FILE": str(token),
        "HF_TOKEN_FILE": str(token),
        "HISTOPLUS_WEIGHT_FILE": str(tmp_path / "unrelated-weight-path.pt"),
    })
    result = invoke(
        tmp_path, "run", str(REPOSITORY / "tests/fixtures"),
        "--output", str(tmp_path / "weighted"), "--source-mpp", "0.261780",
        "--profile", "local", "--local-weight", str(weight),
        environment=environment,
    )
    assert result.returncode == core.EXIT_WORKFLOW
    inherited = environment_capture.read_text(encoding="utf-8")
    assert "hf_unrelated" not in inherited
    assert "TUMORQUANTAI_HF_TOKEN_FILE=" not in inherited
    assert "HF_TOKEN_FILE=" not in inherited
    assert "HISTOPLUS_WEIGHT_FILE=" not in inherited


def test_direct_run_sh_uses_canonical_credential_precedence(tmp_path: Path) -> None:
    environment, _capture = fake_nextflow(tmp_path)
    environment_capture = tmp_path / "direct.env"
    preferred = tmp_path / "preferred-token"
    explicit = tmp_path / "explicit-token"
    preferred.write_text("hf_preferred_file_123456", encoding="utf-8")
    explicit.write_text("hf_explicit_file_123456", encoding="utf-8")
    preferred.chmod(0o600); explicit.chmod(0o600)
    environment.update({
        "TQA_ENV_CAPTURE": str(environment_capture),
        "TUMORQUANTAI_HF_TOKEN_FILE": str(preferred),
        "HF_TOKEN": "hf_legacy_environment_123456",
    })
    result = subprocess.run(
        [
            str(REPOSITORY / "run.sh"), "--input-dir", str(REPOSITORY / "tests/fixtures"),
            "--output-dir", str(tmp_path / "direct-output"),
            "--work-dir", str(tmp_path / "direct-work"), "--profile", "local",
            "--slide-mpp", "0.261780", "--hf-token-file", str(explicit),
        ],
        cwd=REPOSITORY, env=environment, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    inherited = environment_capture.read_text(encoding="utf-8")
    assert "HF_TOKEN=hf_preferred_file_123456" in inherited
    assert "hf_explicit_file" not in inherited
    assert "hf_legacy_environment" not in inherited


def write_status_fixture(root: Path) -> None:
    metadata = root / "workflow_metadata"
    aggregate = root / "aggregated_celltypes"
    logs = metadata / "logs"
    logs.mkdir(parents=True)
    aggregate.mkdir(parents=True)
    samples = ["complete", "zero", "failed", "incomplete", "excluded", "pending"]
    with (metadata / "slides.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["sample_id"], delimiter="\t")
        writer.writeheader(); writer.writerows({"sample_id": sample} for sample in samples)
    rows = [
        {"slide_id": "complete", "included": True, "status": "included", "manifest_completed": True, "manifest_selected": True, "returncode": 0, "reason": "", "log_file": ""},
        {"slide_id": "zero", "included": True, "status": "included", "manifest_completed": True, "manifest_selected": True, "returncode": 0, "reason": "", "log_file": ""},
        {"slide_id": "failed", "included": False, "status": "excluded_incomplete", "manifest_completed": False, "manifest_selected": True, "returncode": 1, "reason": "returncode=1 HF_TOKEN=hf_status_secret_123456", "log_file": "workflow_metadata/logs/failed.log"},
        {"slide_id": "incomplete", "included": False, "status": "excluded_incomplete", "manifest_completed": False, "manifest_selected": True, "returncode": "", "reason": "missing completion summary", "log_file": ""},
        {"slide_id": "excluded", "included": False, "status": "excluded_unselected", "manifest_completed": False, "manifest_selected": False, "returncode": "", "reason": "selected=False", "log_file": ""},
    ]
    with (aggregate / "sample_aggregation_audit.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    (logs / "failed.log").write_text("fixture failure\n", encoding="utf-8")
    for sample, n_cells in (("complete", 4), ("zero", 0)):
        summary = root / sample / "summary/summary.json"
        summary.parent.mkdir(parents=True)
        summary.write_text(json.dumps({"slide_id": sample, "n_cells": n_cells, "zero_detections": n_cells == 0}), encoding="utf-8")
        counts = root / sample / "cell_types/class_counts.csv"
        counts.parent.mkdir(parents=True)
        counts.write_text(
            "class_id,class_name,count\n" + ("1,fixture,4\n" if n_cells else ""),
            encoding="utf-8",
        )
    core.write_run_manifest(root, {"resume_command": "./tumorquantai run INPUT --output OUTPUT"})


def test_status_distinguishes_all_sample_states_and_zero(tmp_path: Path) -> None:
    output = tmp_path / "status"
    write_status_fixture(output)
    result = invoke(tmp_path, "status", str(output), "--json")
    assert result.returncode == core.EXIT_OK
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "WARN"
    assert payload["counts"] == {
        "completed": 2, "failed": 1, "incomplete": 1,
        "excluded": 1, "pending": 1, "biological_zero": 1,
    }
    assert payload["samples"]["biological_zero"] == ["zero"]
    assert payload["first_log"] == "workflow_metadata/logs/failed.log"
    assert "status_secret" not in json.dumps(payload)


def test_completed_quickstart_root_delegates_status_to_smoke_results(tmp_path: Path) -> None:
    root = tmp_path / "tutorial"
    child = root / "smoke-results"
    write_status_fixture(child)
    core.write_run_manifest(root, {
        "completion_status": "one_slide_smoke_complete",
        "dataset_record": core.DATASET_RECORD,
        "seed": 99,
        "resume_command": "./tumorquantai quickstart --output tutorial --seed 99",
    })
    payload = core.collect_status(root)
    assert payload["counts"]["completed"] == 2
    assert payload["counts"]["failed"] == 1
    assert payload["run"]["dataset_record"] == core.DATASET_RECORD
    assert payload["run"]["seed"] == 99
    assert payload["first_log"] == "smoke-results/workflow_metadata/logs/failed.log"
    assert payload["output_name"] == "redacted-output"

    overlay = child / "complete/overlays/celltypes_overview_and_zoom.png"
    overlay.parent.mkdir(parents=True)
    overlay.write_bytes(b"fixture")
    _report, report_payload = core.generate_report(root)
    paths = {item["path"] for item in report_payload["links"]}
    assert "smoke-results/complete/summary/summary.json" in paths
    assert "smoke-results/complete/overlays/celltypes_overview_and_zoom.png" in paths
    failed_root = core.load_run_manifest(root)
    failed_root["completion_status"] = "inference_failed"
    core.write_run_manifest(root, failed_root)
    _report, failed_payload = core.generate_report(root)
    failed_paths = {item["path"] for item in failed_payload["links"]}
    assert "smoke-results/complete/summary/summary.json" in failed_paths


def test_status_and_report_preserve_mixed_per_input_mpp_provenance(
    tmp_path: Path,
) -> None:
    output = tmp_path / "mixed-mpp-status"
    output.mkdir()
    core.write_run_manifest(output, {
        "source_mpp": None,
        "source_mpp_values": [0.25, 2.5],
        "source_mpp_provenance": "per-input embedded TIFF metadata",
        "resume_command": "tumorquantai --patches patches --paper-figures --output results",
    })

    status = core.collect_status(output)
    assert status["run"]["source_mpp"] is None
    assert status["run"]["source_mpp_values"] == [0.25, 2.5]
    assert (
        status["run"]["source_mpp_provenance"]
        == "per-input embedded TIFF metadata"
    )
    human = core.format_status(status)
    assert "Source MPP values (µm/pixel): 0.25, 2.5" in human
    assert "Source MPP provenance: per-input embedded TIFF metadata" in human

    _report, payload = core.generate_report(output)
    assert payload["run"]["source_mpp_values"] == [0.25, 2.5]
    document = (output / "START_HERE.html").read_text(encoding="utf-8")
    assert "Source MPP values (µm/pixel)" in document
    assert "0.25, 2.5" in document
    assert "per-input embedded TIFF metadata" in document
    text_summary = (output / core.RUN_SUMMARY).read_text(encoding="utf-8")
    assert "Source MPP values (µm/pixel): 0.25, 2.5" in text_summary


def test_status_and_report_keep_legacy_single_source_mpp_readable(
    tmp_path: Path,
) -> None:
    output = tmp_path / "single-mpp-status"
    output.mkdir()
    core.write_run_manifest(output, {
        "source_mpp": 0.26178,
        "source_mpp_provenance": "explicit --source-mpp",
        "resume_command": "tumorquantai run slides --output results --source-mpp 0.26178",
    })

    status = core.collect_status(output)
    assert status["run"]["source_mpp"] == pytest.approx(0.26178)
    assert "source_mpp_values" not in status["run"]
    human = core.format_status(status)
    assert "Source MPP (µm/pixel): 0.26178" in human
    assert "Source MPP values" not in human

    core.generate_report(output)
    document = (output / "START_HERE.html").read_text(encoding="utf-8")
    assert "Source MPP (µm/pixel)" in document
    assert "Source MPP values" not in document
    assert "explicit --source-mpp" in document


def test_trace_promotes_incomplete_sample_to_failed_but_not_successful_retry(tmp_path: Path) -> None:
    output = tmp_path / "trace-status"
    aggregate = output / "aggregated_celltypes"
    metadata = output / "workflow_metadata"
    aggregate.mkdir(parents=True)
    metadata.mkdir(parents=True)
    (aggregate / "sample_aggregation_audit.csv").write_text(
        "slide_id,included,status,manifest_completed,manifest_selected,returncode,reason,log_file\n"
        "failed,False,excluded_incomplete,False,True,,,\n"
        "recovered,True,included,True,True,0,,\n",
        encoding="utf-8",
    )
    recovered_summary = output / "recovered/summary/summary.json"
    recovered_summary.parent.mkdir(parents=True)
    recovered_summary.write_text(json.dumps({"n_cells": 2, "zero_detections": False}), encoding="utf-8")
    recovered_counts = output / "recovered/cell_types/class_counts.csv"
    recovered_counts.parent.mkdir(parents=True)
    recovered_counts.write_text("class_id,class_name,count\n1,fixture,2\n", encoding="utf-8")
    (metadata / "nextflow_trace_fixture.tsv").write_text(
        "name\tstatus\texit\n"
        "tumorquantai:PROCESS_SLIDE (failed)\tFAILED\t1\n"
        "tumorquantai:PROCESS_SLIDE (recovered)\tFAILED\t1\n"
        "tumorquantai:PROCESS_SLIDE (recovered)\tCOMPLETED\t0\n",
        encoding="utf-8",
    )
    payload = core.collect_status(output)
    assert payload["samples"]["failed"] == ["failed"]
    assert payload["samples"]["completed"] == ["recovered"]
    assert payload["reasons"]["failed"] == "Nextflow PROCESS_SLIDE status=FAILED, exit=1"


def test_biological_zero_requires_explicit_summary_and_empty_counts_agreement(tmp_path: Path) -> None:
    output = tmp_path / "zero-contract"
    summary = output / "case/summary/summary.json"
    counts = output / "case/cell_types/class_counts.csv"
    summary.parent.mkdir(parents=True)
    counts.parent.mkdir(parents=True)
    summary.write_text(json.dumps({"n_cells": 0, "zero_detections": False}), encoding="utf-8")
    counts.write_text("class_id,class_name,count\n", encoding="utf-8")
    assert core.collect_status(output)["counts"]["biological_zero"] == 0
    summary.write_text(json.dumps({"n_cells": 0, "zero_detections": True}), encoding="utf-8")
    counts.write_text("class_id,class_name,count\n1,fixture,1\n", encoding="utf-8")
    assert core.collect_status(output)["counts"]["biological_zero"] == 0
    counts.write_text("class_id,class_name,count\n", encoding="utf-8")
    assert core.collect_status(output)["counts"]["biological_zero"] == 1


def test_included_audit_row_without_required_artifacts_is_incomplete(tmp_path: Path) -> None:
    output = tmp_path / "missing-artifacts"
    aggregate = output / "aggregated_celltypes"
    aggregate.mkdir(parents=True)
    (aggregate / "sample_aggregation_audit.csv").write_text(
        "slide_id,included,status,manifest_completed,manifest_selected,returncode,reason,log_file\n"
        "case_a,True,included,True,True,0,,\n",
        encoding="utf-8",
    )
    payload = core.collect_status(output)
    assert payload["samples"]["completed"] == []
    assert payload["samples"]["incomplete"] == ["case_a"]
    assert "missing summary.json" in payload["reasons"]["case_a"]


def test_all_failed_status_is_reported_not_zero(tmp_path: Path) -> None:
    output = tmp_path / "failed"
    aggregate = output / "aggregated_celltypes"
    aggregate.mkdir(parents=True)
    (aggregate / "sample_aggregation_audit.csv").write_text(
        "slide_id,included,status,manifest_completed,manifest_selected,returncode,reason,log_file\n"
        "case_a,False,excluded_incomplete,False,True,1,returncode=1,\n",
        encoding="utf-8",
    )
    payload = json.loads(invoke(tmp_path, "status", str(output), "--json").stdout)
    assert payload["overall_status"] == "FAIL"
    assert payload["counts"]["failed"] == 1
    assert payload["counts"]["biological_zero"] == 0


def test_report_escapes_user_text_uses_relative_links_and_json_is_pure(tmp_path: Path) -> None:
    output = tmp_path / "report"
    output.mkdir()
    core.write_run_manifest(output, {
        "software_version": core.VERSION,
        "container_identity": "<script>alert('x')</script>",
        "resume_command": "./tumorquantai run '<unsafe&input>' --output report",
    })
    result = invoke(tmp_path, "report", str(output), "--json")
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "tumorquantai_status_v1"
    document = (output / "START_HERE.html").read_text(encoding="utf-8")
    assert "<script>alert" not in document
    assert "&lt;script&gt;" in document
    assert str(tmp_path) not in document
    assert (output / core.REPORT_JSON).is_file()


def test_report_handles_an_empty_existing_directory(tmp_path: Path) -> None:
    output = tmp_path / "empty"
    output.mkdir()
    result = invoke(tmp_path, "report", str(output))
    assert result.returncode == core.EXIT_OK
    assert (output / "START_HERE.html").is_file()
    assert (output / core.REPORT_JSON).is_file()
    document = (output / "START_HERE.html").read_text(encoding="utf-8")
    assert "Completed status WARN" in document
    assert "Failed status PASS" in document


def test_missing_status_directory_has_stable_input_exit(tmp_path: Path) -> None:
    result = invoke(tmp_path, "status", str(tmp_path / "missing"))
    assert result.returncode == core.EXIT_INPUT


def test_quickstart_dry_run_is_bounded_and_creates_nothing(tmp_path: Path) -> None:
    output = tmp_path / "tutorial"
    result = invoke(tmp_path, "quickstart", "--output", str(output), "--dry-run")
    assert result.returncode == core.EXIT_OK, result.stderr
    assert core.TUTORIAL_FILE in result.stdout
    assert "125350400 bytes" in result.stdout
    assert "L0 and L2" in result.stdout
    assert "no network request" in result.stdout
    assert not output.exists()


def test_quickstart_missing_convert_input_has_data_exit_code(tmp_path: Path) -> None:
    result = invoke(tmp_path, "quickstart", "--output", str(tmp_path / "tutorial"), "--convert-only")
    assert result.returncode == core.EXIT_PREFLIGHT
    assert "mounted filesystem" in result.stderr


def test_quickstart_refuses_repository_and_preserves_completed_state(tmp_path: Path) -> None:
    with pytest.raises(core.TumorQuantAIError) as caught:
        core.validate_large_data_root(REPOSITORY / "tutorial-one-slide")
    assert caught.value.exit_code == core.EXIT_PREFLIGHT

    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_state_test")
    root = tmp_path / "state-only"
    namespace["_write_quickstart_manifest"](
        root, "one_slide_smoke_complete", seed=17, profile="cpu",
        inference_manifest={"container_identity": "pinned-container", "execution_profile": "cpu"},
    )
    namespace["_write_quickstart_manifest"](
        root, "download_verified", {"sha256": "a" * 64},
        seed=core.DEFAULT_SEED, profile="gpu",
    )
    manifest = core.load_run_manifest(root)
    assert manifest["completion_status"] == "one_slide_smoke_complete"
    assert manifest["container_identity"] == "pinned-container"
    assert manifest["seed"] == 17
    assert manifest["execution_profile"] == "cpu"
    assert "--profile cpu --seed 17" in manifest["resume_command"]
    assert manifest["source_checksums"]["sha256"] == "a" * 64
    assert "last_data_verification_at_utc" in manifest


def test_quickstart_disk_requirement_is_stage_aware() -> None:
    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_estimate_test")
    estimates = namespace["_quickstart_estimates"](True)
    download = namespace["_quickstart_required_bytes"](
        type("Args", (), {"download_only": True, "convert_only": False, "no_inference": False})(),
        estimates,
    )
    convert = namespace["_quickstart_required_bytes"](
        type("Args", (), {"download_only": False, "convert_only": True, "no_inference": False})(),
        estimates,
    )
    assert download == estimates["download"]
    assert estimates["download"] not in {convert, convert - estimates["conversion"]}


def _mock_quickstart_runtime(
    monkeypatch: pytest.MonkeyPatch, namespace: dict[str, object], calls: list[list[str]],
) -> None:
    monkeypatch.setattr(core, "validate_large_data_root", lambda _path: {"target": "/mounted"})
    monkeypatch.setattr(core, "storage_preflight", lambda *_args, **_kwargs: {
        "ok": True, "mount": {"target": "/mounted", "filesystem": "ext4"},
        "free_bytes": 100 * 1024**3, "same_filesystem": True,
    })
    monkeypatch.setattr(core, "verify_tutorial_download", lambda _path: {
        "file": f"raw/{core.TUTORIAL_SAMPLE}/1.mds", "size_bytes": core.TUTORIAL_SIZE,
        "sha256": core.TUTORIAL_SHA256, "md5": core.TUTORIAL_MD5,
        "source_mpp": core.TUTORIAL_SOURCE_MPP,
    })
    monkeypatch.setattr(core, "inspect_inputs", lambda *_args, **_kwargs: {
        "slides": [{"sample_id": core.TUTORIAL_SAMPLE}],
        "summary": {"sample_count": 1},
    })
    monkeypatch.setattr(core, "doctor_checks", lambda **_kwargs: [])
    function_globals = namespace["cmd_quickstart"].__globals__
    monkeypatch.setitem(function_globals, "_check_quickstart_dependencies", lambda _args: None)

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append([str(item) for item in command])
        return SimpleNamespace(returncode=0)

    monkeypatch.setitem(function_globals, "subprocess", SimpleNamespace(run=fake_run))


def _quickstart_args(tmp_path: Path, **updates: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "output": tmp_path / "mounted-tutorial", "dry_run": False,
        "download_only": False, "convert_only": False, "no_inference": False,
        "profile": "cpu", "seed": core.DEFAULT_SEED,
        "token_file": None, "local_weight": None,
    }
    values.update(updates)
    return SimpleNamespace(**values)


def test_quickstart_download_only_is_public_and_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_download_test")
    calls: list[list[str]] = []
    _mock_quickstart_runtime(monkeypatch, namespace, calls)
    code = namespace["cmd_quickstart"](
        _quickstart_args(tmp_path, download_only=True)
    )
    assert code == core.EXIT_OK
    assert len(calls) == 1
    command = calls[0]
    assert command[command.index("--record") + 1] == core.DATASET_RECORD
    assert command[command.index("--sample-id") + 1] == core.TUTORIAL_SAMPLE
    assert command[command.index("--expected-count") + 1] == "1"
    assert not any("token" in item.lower() for item in command)
    assert core.load_run_manifest(tmp_path / "mounted-tutorial")["completion_status"] == "download_verified"


def test_quickstart_no_auth_prepares_l0_l2_and_reports_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_noauth_test")
    calls: list[list[str]] = []
    _mock_quickstart_runtime(monkeypatch, namespace, calls)
    monkeypatch.setattr(core, "resolve_token_file", lambda _path: (None, "not configured", None))
    monkeypatch.setattr(core, "model_access", lambda *_args: {
        "ready": False, "method": "not configured", "weight": None, "token": None,
    })
    code = namespace["cmd_quickstart"](_quickstart_args(tmp_path))
    assert code == core.EXIT_OK
    assert len(calls) == 2
    converter = calls[1]
    assert converter[converter.index("--levels") + 1 : converter.index("--levels") + 3] == ["0", "2"]
    assert converter[converter.index("--sample-id") + 1] == core.TUTORIAL_SAMPLE
    assert "--resume" in converter
    manifest = core.load_run_manifest(tmp_path / "mounted-tutorial")
    assert manifest["completion_status"] == "ready_for_authorized_inference"
    assert (tmp_path / "mounted-tutorial/START_HERE.html").is_file()


def test_quickstart_authorized_path_reaches_exact_one_sample_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_success_test")
    calls: list[list[str]] = []
    _mock_quickstart_runtime(monkeypatch, namespace, calls)
    monkeypatch.setattr(core, "resolve_token_file", lambda _path: (tmp_path / "token", "fixture", None))
    monkeypatch.setattr(core, "model_access", lambda *_args: {
        "ready": True, "method": "token_file", "weight": None, "token": tmp_path / "token",
    })

    def fake_analysis(args: SimpleNamespace) -> int:
        aggregate = args.output / "aggregated_celltypes"
        aggregate.mkdir(parents=True)
        (aggregate / "sample_aggregation_audit.csv").write_text(
            "slide_id,included,status\n" + core.TUTORIAL_SAMPLE + ",True,included\n",
            encoding="utf-8",
        )
        summary = args.output / core.TUTORIAL_SAMPLE / "summary/summary.json"
        summary.parent.mkdir(parents=True)
        summary.write_text(json.dumps({"n_cells": 1, "zero_detections": False}), encoding="utf-8")
        counts = args.output / core.TUTORIAL_SAMPLE / "cell_types/class_counts.csv"
        counts.parent.mkdir(parents=True)
        counts.write_text("class_id,class_name,count\n1,fixture,1\n", encoding="utf-8")
        core.write_run_manifest(args.output, {
            "completion_status": "complete", "execution_profile": "cpu",
            "container_identity": core.CPU_CONTAINER, "model_revision": core.MODEL_REVISION,
            "selected_samples": [core.TUTORIAL_SAMPLE], "credential_method": "token_file",
        })
        return core.EXIT_OK

    monkeypatch.setitem(namespace["cmd_quickstart"].__globals__, "run_analysis", fake_analysis)
    code = namespace["cmd_quickstart"](_quickstart_args(tmp_path))
    assert code == core.EXIT_OK
    manifest = core.load_run_manifest(tmp_path / "mounted-tutorial")
    assert manifest["completion_status"] == "one_slide_smoke_complete"
    assert manifest["selected_samples"] == [core.TUTORIAL_SAMPLE]
    assert (tmp_path / "mounted-tutorial/START_HERE.html").is_file()


def test_quickstart_child_failure_is_visible_at_tutorial_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_failure_test")
    calls: list[list[str]] = []
    _mock_quickstart_runtime(monkeypatch, namespace, calls)
    monkeypatch.setattr(core, "resolve_token_file", lambda _path: (tmp_path / "token", "fixture", None))
    monkeypatch.setattr(core, "model_access", lambda *_args: {
        "ready": True, "method": "token_file", "weight": None, "token": tmp_path / "token",
    })

    def failed_analysis(args: SimpleNamespace) -> int:
        core.write_run_manifest(args.output, {
            "completion_status": "failed", "execution_profile": "cpu",
            "container_identity": core.CPU_CONTAINER,
        })
        return core.EXIT_WORKFLOW

    monkeypatch.setitem(
        namespace["cmd_quickstart"].__globals__, "run_analysis", failed_analysis
    )
    code = namespace["cmd_quickstart"](_quickstart_args(tmp_path))
    assert code == core.EXIT_WORKFLOW
    manifest = core.load_run_manifest(tmp_path / "mounted-tutorial")
    assert manifest["completion_status"] == "inference_failed"
    assert (tmp_path / "mounted-tutorial/START_HERE.html").is_file()


def test_credential_resolution_precedence_and_secret_redaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = tmp_path / "configured-token"
    explicit = tmp_path / "explicit-token"
    monkeypatch.setenv("TUMORQUANTAI_HF_TOKEN_FILE", str(configured))
    path, source, warning = core.resolve_token_file(explicit)
    assert path == configured
    assert source == "TUMORQUANTAI_HF_TOKEN_FILE"
    assert warning is None
    secret = "HF_TOKEN=hf_supersecret0123456789"
    assert "supersecret" not in core.redact_text(secret)

    monkeypatch.delenv("TUMORQUANTAI_HF_TOKEN_FILE")
    monkeypatch.setenv("HF_TOKEN_FILE", str(configured))
    path, source, warning = core.resolve_token_file()
    assert path == configured
    assert source == "legacy HF_TOKEN_FILE environment"
    assert warning and "prefer TUMORQUANTAI_HF_TOKEN_FILE" in warning

    canonical = tmp_path / "canonical-token"
    canonical.write_text("hf_canonical_fixture_123456", encoding="utf-8")
    canonical.chmod(0o600)
    monkeypatch.setattr(core, "CANONICAL_TOKEN", canonical)
    path, source, warning = core.resolve_token_file()
    assert path == canonical
    assert source == "canonical file"
    assert warning is None


def test_relative_credential_and_weight_paths_are_resolved_before_changing_run_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = tmp_path / "relative-token"
    token.write_text("hf_fixture_relative_123456", encoding="utf-8")
    token.chmod(0o600)
    weight = tmp_path / "relative-weight.pt"
    weight.write_bytes(b"fixture")
    monkeypatch.chdir(tmp_path)
    resolved_token, _source, _warning = core.resolve_token_file(Path("relative-token"))
    access = core.model_access(Path("relative-weight.pt"), resolved_token)
    assert resolved_token == token.resolve()
    assert access["weight"] == weight.resolve()


def test_path_redaction_removes_arbitrary_absolute_locations() -> None:
    value = (
        "./tumorquantai run ../relative/input /data/patient-123/result "
        "and '/secure/study one/file' but keep https://example.org/x"
    )
    redacted = core.redact_text(value, paths=True)
    assert "/data/patient" not in redacted
    assert "/secure/study" not in redacted
    assert "./tumorquantai" in redacted
    assert "../relative/input" in redacted
    assert "https://example.org/x" in redacted


def test_path_redaction_hides_home_suffixes() -> None:
    value = str(Path.home() / "patient-441" / "study-secret" / "result")
    redacted = core.redact_text(value, paths=True)
    assert "patient-441" not in redacted
    assert "study-secret" not in redacted
    assert "~/<redacted-path>" in redacted


def test_single_sample_audit_rejects_the_wrong_alias(tmp_path: Path) -> None:
    aggregate = tmp_path / "aggregated_celltypes"
    aggregate.mkdir()
    (aggregate / "sample_aggregation_audit.csv").write_text(
        "slide_id,included,status\nTumorQuantAI_LymphomaWSI_021,True,included\n",
        encoding="utf-8",
    )
    with pytest.raises(core.TumorQuantAIError):
        core.validate_single_sample_audit(tmp_path)


def test_publishable_weight_identity_keeps_sha_but_removes_private_path() -> None:
    private = {
        "source": "local_file", "filename": "histoplus_cellvit_segmentor_20x.pt",
        "file": {"path": "/private/models/weight.pt", "size_bytes": 123, "mtime_ns": 4, "sha256": "a" * 64},
        "resolved_file": {"path": "/cache/weight.pt", "size_bytes": 123, "inode": 8, "device": 9, "sha256": "a" * 64},
    }
    import lazyslide_histoplus_wsi_celltype as worker

    result = worker.publishable_histoplus_weight_identity(private)
    encoded = json.dumps(result)
    assert "/private" not in encoded and "/cache" not in encoded
    assert "inode" not in encoded and "device" not in encoded and "mtime_ns" not in encoded
    assert result["resolved_file"]["sha256"] == "a" * 64
    assert result["resolved_file"]["size_bytes"] == 123


def test_fixed_public_tutorial_identity() -> None:
    assert core.DATASET_RECORD == "21466410"
    assert core.DATASET_DOI == "10.5281/zenodo.21466410"
    assert core.DATASET_RELEASE == "v0.4.0"
    assert core.TUTORIAL_SAMPLE == "TumorQuantAI_LymphomaWSI_022"
    assert core.TUTORIAL_SIZE == 125_350_400
    assert core.TUTORIAL_SOURCE_MPP == pytest.approx(0.261780)
