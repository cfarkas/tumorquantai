from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


REPOSITORY = Path(__file__).parents[1]
CLI = REPOSITORY / "tumorquantai"


@pytest.fixture(scope="module")
def cli_namespace() -> dict[str, Any]:
    return runpy.run_path(str(CLI), run_name="tumorquantai_parameter_test")


def resolved(
    namespace: dict[str, Any], arguments: list[str],
) -> Any:
    parsed = namespace["build_parser"]().parse_args(arguments)
    explicit = namespace["explicit_run_parameter_keys"](arguments)
    return namespace["resolve_run_parameters"](parsed, explicit)


def test_schema_visibility_and_cli_groups_cover_every_public_parameter(
    cli_namespace: dict[str, Any],
) -> None:
    schema_keys = set(cli_namespace["SCHEMA_PROPERTIES"])
    internal = set(cli_namespace["INTERNAL_SCHEMA_PARAMETERS"])
    public = set(cli_namespace["PUBLIC_PARAMETER_OPTIONS"])
    grouped = {
        parameter
        for parameters in cli_namespace["PARAMETER_GROUPS"].values()
        for parameter in parameters
    }

    assert len(schema_keys) == 57
    assert internal == {
        "worker_script", "docker_run_options", "histoplus_weight_sha256",
    }
    assert len(public) == 54
    assert public == schema_keys - internal
    assert grouped == public


def test_run_help_is_grouped_complete_and_has_no_internal_parameters(
    cli_namespace: dict[str, Any],
) -> None:
    result = subprocess.run(
        [sys.executable, str(CLI), "run", "--help"],
        cwd=REPOSITORY,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for group in cli_namespace["PARAMETER_GROUPS"]:
        assert f"{group}:" in result.stdout
    for parameter, options in cli_namespace["PUBLIC_PARAMETER_OPTIONS"].items():
        visible = [option for option in options if option.startswith("--")]
        if visible:
            assert any(option in result.stdout for option in visible), parameter
        else:
            assert "  INPUT " in result.stdout
    for parameter in cli_namespace["INTERNAL_SCHEMA_PARAMETERS"]:
        assert parameter not in result.stdout
        assert parameter.replace("_", "-") not in result.stdout


def test_yaml_precedence_is_schema_then_preset_then_file_then_cli(
    tmp_path: Path, cli_namespace: dict[str, Any],
) -> None:
    parameter_file = tmp_path / "parameters.yaml"
    parameter_file.write_text(
        "preset: full\n"
        "input_dir: /ignored/input\n"
        "output_dir: /ignored/output\n"
        "percent_slide: 25\n"
        "cpus: 6\n"
        "overlap: 0.4\n"
        "profile: cpu\n"
        "resume: false\n",
        encoding="utf-8",
    )
    arguments = [
        "run", "/explicit/input", "--output", "/explicit/output",
        "--params-file", str(parameter_file), "--preset", "fast", "--cpus", "3",
    ]
    args = resolved(cli_namespace, arguments)

    assert args.input == Path("/explicit/input")
    assert args.output == Path("/explicit/output")
    assert args.tile_px == 840  # schema default
    assert args.preset == "fast"  # explicit launcher value
    assert args.percent_slide == 25  # file overrides selected fast preset's 10
    assert args.overlap == 0.4
    assert args.cpus == 3  # explicit CLI overrides file
    assert args.profile == "cpu"
    assert args.resume is False


def test_json_params_wrapper_and_explicit_value_override(
    tmp_path: Path, cli_namespace: dict[str, Any],
) -> None:
    parameter_file = tmp_path / "parameters.json"
    parameter_file.write_text(
        json.dumps({
            "params": {
                "input_dir": "/file/input",
                "output_dir": "/file/output",
                "percent_slide": 40,
                "device": "cuda:2",
                "save_json": True,
                "slide_patterns": ["*.tif", "*.tiff"],
            }
        }),
        encoding="utf-8",
    )
    arguments = [
        "run", "--params-file", str(parameter_file), "--percent-slide", "7",
    ]
    args = resolved(cli_namespace, arguments)

    assert args.input == Path("/file/input")
    assert args.output == Path("/file/output")
    assert args._parameter_sources["input_dir"] == "parameter file"
    assert args._parameter_sources["output_dir"] == "parameter file"
    assert args.percent_slide == 7
    assert args.device == "cuda:2"
    assert args.save_json is True
    assert args.pattern == ["*.tif", "*.tiff"]


def test_omitted_run_input_remains_suppressed(
    cli_namespace: dict[str, Any],
) -> None:
    parsed = cli_namespace["build_parser"]().parse_args([
        "run", "--params-file", "/parameters.json",
    ])

    assert not hasattr(parsed, "input")


@pytest.mark.parametrize(
    ("contents", "suffix", "message"),
    [
        ("unknown_option: 1\n", ".yaml", "Unknown parameter-file key"),
        ("worker_script: /tmp/worker.py\n", ".yaml", "Internal parameters"),
        ("cpus: 0\n", ".yaml", "Invalid value for parameter 'cpus'"),
        ("device: cuda:x\n", ".yaml", "Invalid value for parameter 'device'"),
        ("profile: cpu\ndevice: cuda:1\n", ".yaml", "profile 'cpu' is incompatible"),
        ('{"cpus": 2, "cpus": 3}', ".json", "duplicate parameter key"),
        ('{"resume": "yes"}', ".json", "Parameter 'resume' must be a boolean"),
    ],
)
def test_parameter_file_rejects_unknown_internal_duplicate_and_invalid_values(
    tmp_path: Path, contents: str, suffix: str, message: str,
) -> None:
    parameter_file = tmp_path / f"invalid{suffix}"
    parameter_file.write_text(contents, encoding="utf-8")
    output = tmp_path / "must-not-exist"
    result = subprocess.run(
        [
            sys.executable, str(CLI), "run", "/input", "--output", str(output),
            "--params-file", str(parameter_file),
        ],
        cwd=REPOSITORY,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert message in result.stderr
    assert not output.exists()


def test_invalid_explicit_cli_value_is_rejected_before_filesystem_work(
    tmp_path: Path,
) -> None:
    output = tmp_path / "must-not-exist"
    result = subprocess.run(
        [
            sys.executable, str(CLI), "run", "/input", "--output", str(output),
            "--overlap", "1.1",
        ],
        cwd=REPOSITORY,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "Invalid value for parameter 'overlap'" in result.stderr
    assert not output.exists()


@pytest.mark.parametrize(
    ("profile_arguments", "expected_device"),
    [
        (["--profile", "cpu"], "cpu"),
        (["--cpu"], "cpu"),
        (["--profile", "gpu"], "cuda"),
        (["--gpu"], "cuda"),
    ],
)
def test_profile_selects_a_compatible_schema_default_device(
    cli_namespace: dict[str, Any],
    profile_arguments: list[str],
    expected_device: str,
) -> None:
    args = resolved(cli_namespace, [
        "run", "/input", "--output", "/output", *profile_arguments,
    ])
    assert args.device == expected_device


@pytest.mark.parametrize(
    ("profile", "device"),
    [
        ("cpu", "cuda"),
        ("cpu", "gpu"),
        ("cpu", "cuda:2"),
        ("gpu", "cpu"),
    ],
)
def test_incompatible_profile_and_device_fail_before_filesystem_work(
    tmp_path: Path, profile: str, device: str,
) -> None:
    output = tmp_path / "must-not-exist"
    result = subprocess.run(
        [
            sys.executable, str(CLI), "run", "/input", "--output", str(output),
            "--profile", profile, "--device", device,
        ],
        cwd=REPOSITORY,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert f"Execution profile '{profile}' is incompatible" in result.stderr
    assert device in result.stderr
    assert not output.exists()


@pytest.mark.parametrize(
    ("effective_profile", "device"),
    [
        ("gpu", "cpu"),
        ("cpu", "cuda"),
    ],
)
def test_auto_profile_rechecks_device_before_creating_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cli_namespace: dict[str, Any],
    effective_profile: str,
    device: str,
) -> None:
    output = tmp_path / f"{effective_profile}-{device}"
    args = resolved(cli_namespace, [
        "run", "/input", "--output", str(output),
        "--profile", "auto", "--device", device, "--dry-run",
    ])
    args.expert_args = []
    prepare_globals = cli_namespace["_prepare_run"].__globals__
    monkeypatch.setitem(
        prepare_globals, "resolve_profile", lambda _requested: effective_profile,
    )

    def unexpected_storage(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("incompatible effective profile reached creating storage preflight")

    monkeypatch.setattr(
        cli_namespace["core"], "storage_preflight", unexpected_storage,
    )
    with pytest.raises(
        cli_namespace["core"].TumorQuantAIError,
        match=rf"profile '{effective_profile}' is incompatible",
    ):
        cli_namespace["_prepare_run"](args)
    assert not output.exists()


def test_non_run_sh_public_values_are_forwarded_to_nextflow(
    tmp_path: Path, cli_namespace: dict[str, Any],
) -> None:
    parameter_file = tmp_path / "parameters.yaml"
    parameter_file.write_text(
        "overlap: 0.6\n"
        "save_json: true\n"
        "pyramidal_jpeg_q: 77\n"
        "histoplus_cache_dir: /task/cache\n",
        encoding="utf-8",
    )
    args = resolved(cli_namespace, [
        "run", "/input", "--output", "/output", "--params-file", str(parameter_file),
    ])
    forwarded = cli_namespace["_nextflow_public_arguments"](args)
    pairs = dict(zip(forwarded[::2], forwarded[1::2], strict=True))

    assert pairs["--overlap"] == "0.6"
    assert pairs["--save_json"] == "true"
    assert pairs["--pyramidal_jpeg_q"] == "77"
    assert pairs["--histoplus_cache_dir"] == "/task/cache"
    assert "--cpus" not in pairs
