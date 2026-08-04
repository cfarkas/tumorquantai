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
