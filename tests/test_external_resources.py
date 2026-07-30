from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_external_resources.py"
SPEC = importlib.util.spec_from_file_location("check_external_resources", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def test_accepts_current_zenodo_open_published_shape() -> None:
    assert CHECKER.zenodo_record_is_public({
        "status": "published", "metadata": {"access_right": "open"},
    })


def test_accepts_legacy_explicit_public_shape() -> None:
    assert CHECKER.zenodo_record_is_public({
        "status": "published", "access": {"record": "public"},
    })


def test_rejects_restricted_or_unpublished_shapes() -> None:
    assert not CHECKER.zenodo_record_is_public({
        "status": "published", "metadata": {"access_right": "restricted"},
    })
    assert not CHECKER.zenodo_record_is_public({
        "status": "draft", "metadata": {"access_right": "open"},
    })
