from __future__ import annotations

import csv
import importlib.util
import io
import sys
from pathlib import Path

import pytest
from PIL import Image


BIN_DIR = Path(__file__).parents[1] / "bin"
sys.path.insert(0, str(BIN_DIR))
MODULE_PATH = BIN_DIR / "prepare_zenodo_mds.py"
SPEC = importlib.util.spec_from_file_location("prepare_zenodo_mds", MODULE_PATH)
assert SPEC and SPEC.loader
prepare = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = prepare
SPEC.loader.exec_module(prepare)


def test_neutral_bytes_preserves_exact_size() -> None:
    payload = prepare.neutral_bytes(128, "Property")
    assert len(payload) == 128
    assert payload.startswith(b"TumorQuantAI de-identified")


def test_neutral_jpeg_preserves_stream_size_and_is_readable() -> None:
    source = Image.effect_noise((588, 476), 80).convert("RGB")
    encoded = io.BytesIO()
    source.save(encoded, format="JPEG", quality=95)
    original = encoded.getvalue()
    replacement = prepare.neutral_jpeg(original, "Label")
    assert len(replacement) == len(original)
    with Image.open(io.BytesIO(replacement)) as image:
        assert image.size == (588, 476)
        image.verify()


def test_load_selection_excludes_alias_and_requires_unique_rows(tmp_path: Path) -> None:
    first = tmp_path / "first.mds"
    second = tmp_path / "second.mds"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    mapping = tmp_path / "mapping.csv"
    with mapping.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["alias", "source_path"])
        writer.writeheader()
        writer.writerow(
            {
                "alias": "TumorQuantAI_LymphomaWSI_001",
                "source_path": first,
            }
        )
        writer.writerow(
            {
                "alias": "TumorQuantAI_LymphomaWSI_002",
                "source_path": second,
            }
        )
    rows = prepare.load_selection(
        mapping, {"TumorQuantAI_LymphomaWSI_002"}, expected_count=1
    )
    assert [row.alias for row in rows] == ["TumorQuantAI_LymphomaWSI_001"]
    assert rows[0].source_path == first.resolve()


def test_clone_or_copy_never_links_source_inode(tmp_path: Path) -> None:
    source = tmp_path / "source.mds"
    destination = tmp_path / "destination.mds"
    source.write_bytes(b"pixel data")
    method = prepare.clone_or_copy(source, destination)
    assert method in {"reflink", "copy"}
    assert destination.read_bytes() == source.read_bytes()
    assert destination.stat().st_ino != source.stat().st_ino


def test_validate_mpp_rejects_nonpositive() -> None:
    assert prepare.validate_mpp(0.26178) == pytest.approx(0.26178)
    with pytest.raises(prepare.MdsPreparationError):
        prepare.validate_mpp(float("nan"))


class FakeOle:
    def __init__(self, streams: dict[tuple[str, ...], bytes]) -> None:
        self.streams = streams

    def listdir(
        self, *, streams: bool, storages: bool
    ) -> list[list[str]]:
        assert streams is True
        assert storages is False
        return [list(path) for path in self.streams]

    def openstream(self, path: list[str]) -> io.BytesIO:
        return io.BytesIO(self.streams[tuple(path)])


def test_pixel_full_digest_covers_unsampled_dsi0_streams() -> None:
    streams = {
        ("DSI0", "1", "0_0"): b"sampled-first",
        ("DSI0", "1", "0_1"): b"unsampled",
        ("DSI0", "1", "0_2"): b"sampled-middle",
        ("DSI0", "1", "0_3"): b"sampled-last",
    }
    original = prepare.ole_pixel_signature(FakeOle(streams))
    changed_streams = dict(streams)
    changed_streams[("DSI0", "1", "0_1")] = b"changed-but-unsampled"
    changed = prepare.ole_pixel_signature(FakeOle(changed_streams))

    assert original.stream_count == 4
    assert original.sample_sha256 == changed.sample_sha256
    assert original.full_sha256 != changed.full_sha256
