from __future__ import annotations

import os
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tumorquantai"


@pytest.mark.parametrize(
    ("flag", "method"),
    [
        ("--docker", "docker"),
        ("--singularity", "singularity"),
        ("--poetry", "poetry"),
        ("--conda", "conda"),
    ],
)
def test_install_parser_and_dry_run(flag: str, method: str, tmp_path: Path) -> None:
    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_install_test")
    args = namespace["build_parser"]().parse_args([
        "install", flag, "--prefix", str(tmp_path / "prefix"), "--dry-run"
    ])
    assert args.install_method == method
    assert namespace["cmd_install"](args) == 0
    assert not (tmp_path / "prefix").exists()


def test_quickstart_has_a_no_edit_default() -> None:
    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_quickstart_default")
    args = namespace["build_parser"]().parse_args(["quickstart", "--dry-run"])
    assert args.output is None
    default = namespace["_default_quickstart_output"]()
    assert default.name == "tumorquantai-quickstart-one-wsi"
    assert ROOT not in default.parents


def test_installed_backend_can_be_selected_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_backend_config")
    monkeypatch.setenv("TUMORQUANTAI_BACKEND", "conda")
    assert namespace["_configured_backend"]() == "conda"
    args = namespace["build_parser"]().parse_args(["quickstart", "--dry-run"])
    assert args.backend == "conda"


def test_program_name_is_global_command() -> None:
    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_prog_test")
    parser = namespace["build_parser"]()
    assert parser.prog == "tumorquantai"
