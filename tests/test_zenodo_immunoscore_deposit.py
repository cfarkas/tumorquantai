from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


BIN_DIR = Path(__file__).parents[1] / "bin"
sys.path.insert(0, str(BIN_DIR))
MODULE_PATH = BIN_DIR / "zenodo_immunoscore_deposit.py"
SPEC = importlib.util.spec_from_file_location("zenodo_immunoscore_deposit", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_exact_colon_release_contract_and_no_publish_option() -> None:
    assert module.EXPECTED_MDS_COUNT == 30
    assert module.EXPECTED_MDS_BYTES == 40_580_793_856
    assert module.ALIAS_RE.fullmatch("TQA_CIS_" + "A" * 20)
    assert not module.ALIAS_RE.fullmatch("TumorQuantAI_LymphomaWSI_001")
    options = {action.dest for action in module.build_parser()._actions}
    assert "publish" not in options
    assert "public_dir" in options


def test_public_directory_accepts_checksums_and_rejects_private_names(
    tmp_path: Path,
) -> None:
    public = tmp_path / "public"
    public.mkdir()
    manifest = public / module.MANIFEST_NAME
    manifest.write_text("manifest", encoding="utf-8")
    (public / "README.md").write_text("reviewed", encoding="utf-8")
    (public / "SHA256SUMS").write_text("checksums", encoding="utf-8")
    values = module.public_directory_files(public, manifest, [])
    assert {Path(value).name for value in values} == {
        "README.md",
        "SHA256SUMS",
    }
    (public / "private_linkage.csv").write_text("unsafe", encoding="utf-8")
    with pytest.raises(module.base.DepositError, match="private-looking"):
        module.public_directory_files(public, manifest, [])


def test_wrapper_forwards_fixed_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_deposit(**arguments):
        captured.update(arguments)
        return {"status": "draft"}

    monkeypatch.setattr(module.mds, "deposit_mds", fake_deposit)
    result = module.deposit_immunoscore(public_manifest=Path("manifest"))
    assert result == {"status": "draft"}
    assert captured["alias_re"] is module.ALIAS_RE
    assert captured["expected_count"] == 30
    assert captured["expected_bytes"] == 40_580_793_856
    assert captured["dataset_format"] == module.DATASET_FORMAT
