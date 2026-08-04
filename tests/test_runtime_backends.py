from __future__ import annotations

import runpy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tumorquantai"


@pytest.mark.parametrize(
    ("flag", "backend"),
    [
        ("--docker", "docker"),
        ("--singularity", "singularity"),
        ("--apptainer", "singularity"),
        ("--conda", "conda"),
    ],
)
def test_runtime_aliases_select_one_backend(flag: str, backend: str) -> None:
    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_backend_test")
    parser = namespace["build_parser"]()
    run = parser.parse_args([
        "run", "/input", "--output", "/output", flag, "--cpu"
    ])
    quickstart = parser.parse_args([
        "quickstart", "--output", "/output", flag, "--cpu"
    ])
    assert run.backend == backend
    assert quickstart.backend == backend
    assert run.profile == quickstart.profile == "cpu"


@pytest.mark.parametrize(
    "arguments",
    [
        ["run", "/input", "--output", "/output", "--docker", "--conda"],
        ["quickstart", "--output", "/output", "--docker", "--singularity"],
    ],
)
def test_runtime_aliases_are_mutually_exclusive(arguments: list[str]) -> None:
    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_backend_exclusion")
    with pytest.raises(SystemExit):
        namespace["build_parser"]().parse_args(arguments)


def test_versioned_conda_environment_contains_scientific_stack() -> None:
    environment = yaml.safe_load((ROOT / "environment.yml").read_text(encoding="utf-8"))
    dependencies = environment["dependencies"]
    rendered = "\n".join(map(str, dependencies))
    assert "pytorch=2.6.0" in rendered
    assert "openslide" in rendered
    assert "libvips" in rendered
    pip_section = next(item["pip"] for item in dependencies if isinstance(item, dict))
    assert "lazyslide==0.10.1" in pip_section
    assert any("lazyslide-models.git@0127beb" in item for item in pip_section)


def test_nextflow_config_exposes_all_runtime_profiles() -> None:
    config = (ROOT / "nextflow.config").read_text(encoding="utf-8")
    for profile in (
        "docker_cpu", "docker_gpu", "singularity_cpu", "singularity_gpu",
        "apptainer_cpu", "apptainer_gpu", "conda_cpu", "local",
    ):
        assert f"{profile} {{" in config
    assert "conda = params.conda_environment" in config
    assert "conda_environment" in config
    assert "withName: /DISCOVER_SLIDES|PROCESS_SLIDE|AGGREGATE_COUNTS/" in config


def test_singularity_route_binds_every_required_host_path() -> None:
    launcher = (ROOT / "run.sh").read_text(encoding="utf-8")
    config = (ROOT / "nextflow.config").read_text(encoding="utf-8")

    assert 'SINGULARITY_RUN_OPTIONS="--bind ${COMBINED_BINDPATH}"' in launcher
    assert 'NF_ARGS+=("--singularity_run_options=${SINGULARITY_RUN_OPTIONS}")' in launcher
    assert 'export APPTAINER_BINDPATH=' not in launcher
    assert 'export SINGULARITY_BINDPATH=' not in launcher
    for variable in (
        "SCRIPT_DIR", "INPUT_DIR", "OUTPUT_DIR", "WORK_DIR",
        "HF_CACHE", "HISTOPLUS_CACHE",
    ):
        assert f'${{{variable}}}:${{{variable}}}' in launcher
    assert "SAMPLE_SHEET_DIR" in launcher
    assert "HISTOPLUS_WEIGHT_DIR" in launcher

    assert "singularity_run_options = ''" in config
    assert config.count("runOptions = params.singularity_run_options") == 2
    assert config.count(
        'runOptions = \"--nv ${params.singularity_run_options'
    ) == 2


def test_empty_exclude_is_not_forwarded_as_a_nextflow_boolean() -> None:
    launcher = (ROOT / "run.sh").read_text(encoding="utf-8")
    base_block = launcher.split("NF_ARGS=(", 1)[1].split(")\n\n", 1)[0]
    assert '--exclude "${EXCLUDE}"' not in base_block
    assert '[[ -n "${EXCLUDE}" ]] && NF_ARGS+=(--exclude "${EXCLUDE}")' in launcher


def test_resume_command_uses_the_installed_command_name() -> None:
    cli = CLI.read_text(encoding="utf-8")
    assert '"tumorquantai", "run", str(input_root)' in cli
    assert '"./tumorquantai", "run", str(input_root)' not in cli
