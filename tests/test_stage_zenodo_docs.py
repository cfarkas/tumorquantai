from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "stage_zenodo_docs.py"
SPEC = importlib.util.spec_from_file_location("stage_zenodo_docs", SCRIPT)
assert SPEC and SPEC.loader
stage_docs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage_docs)


class StageZenodoDocsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "docs"
        self.source.mkdir()
        for source_name in stage_docs.DOCUMENTS:
            links = " ".join(
                f"[{name}]({name})" for name in stage_docs.DOCUMENTS
            )
            (self.source / source_name).write_text(
                f"# {source_name}\n\n{links}\n", encoding="utf-8"
            )
        self.output = self.root / "release-docs"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_stages_four_documents_and_rewrites_links(self) -> None:
        paths = stage_docs.stage(self.source, self.output)
        self.assertEqual(
            {path.name for path in paths}, set(stage_docs.DOCUMENTS.values())
        )
        self.assertEqual(
            {path.name for path in self.output.iterdir()},
            set(stage_docs.DOCUMENTS.values()),
        )
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for source_name in stage_docs.DOCUMENTS:
                self.assertNotIn(f"]({source_name})", text)
            for remote_name in stage_docs.DOCUMENTS.values():
                self.assertIn(f"]({remote_name})", text)

    def test_missing_source_is_rejected(self) -> None:
        (self.source / "VALIDATION_LYMPHOMA.md").unlink()
        with self.assertRaisesRegex(stage_docs.StagingError, "source is missing"):
            stage_docs.stage(self.source, self.output)

    def test_existing_output_requires_overwrite(self) -> None:
        self.output.mkdir()
        with self.assertRaisesRegex(stage_docs.StagingError, "pass --overwrite"):
            stage_docs.stage(self.source, self.output)

    def test_overwrite_refuses_unknown_content(self) -> None:
        self.output.mkdir()
        marker = self.output / "keep.txt"
        marker.write_text("caller-owned\n", encoding="utf-8")
        with self.assertRaisesRegex(stage_docs.StagingError, "Refusing --overwrite"):
            stage_docs.stage(self.source, self.output, overwrite=True)
        self.assertEqual(marker.read_text(encoding="utf-8"), "caller-owned\n")

    def test_overwrite_replaces_only_intact_staged_output(self) -> None:
        stage_docs.stage(self.source, self.output)
        for path in self.output.iterdir():
            path.write_text("old\n", encoding="utf-8")
        paths = stage_docs.stage(self.source, self.output, overwrite=True)
        self.assertTrue(all(path.read_text(encoding="utf-8").startswith("# ") for path in paths))

    def test_broken_staged_markdown_link_is_rejected(self) -> None:
        source = self.source / "DATASET_LYMPHOMA_ZENODO.md"
        source.write_text("[missing](ABSENT.md)\n", encoding="utf-8")
        with self.assertRaisesRegex(stage_docs.StagingError, "links to absent"):
            stage_docs.stage(self.source, self.output)


if __name__ == "__main__":
    unittest.main()
