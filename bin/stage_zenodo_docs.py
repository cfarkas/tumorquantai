#!/usr/bin/env python3
"""Stage self-contained Markdown documentation for the flat Zenodo record."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path


DOCUMENTS = {
    "DATASET_LYMPHOMA_ZENODO.md": "README.md",
    "TUTORIAL_LYMPHOMA_ZENODO.md": "TUTORIAL.md",
    "VALIDATION_LYMPHOMA.md": "VALIDATION.md",
    "ZENODO_PUBLISHING.md": "PUBLISHING.md",
}
MARKDOWN_LINK_RE = re.compile(r"\]\(([^)#?]+[.]md)(?:#[^)]+)?\)")


class StagingError(RuntimeError):
    """Raised when release documentation cannot be staged safely."""


def validate_existing_output(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise StagingError(f"Refusing unsafe existing output directory: {path}")
    entries = list(path.iterdir())
    names = {entry.name for entry in entries}
    expected = set(DOCUMENTS.values())
    unsafe = [
        entry.name for entry in entries if entry.is_symlink() or not entry.is_file()
    ]
    if unsafe or names != expected:
        raise StagingError(
            "Refusing --overwrite because the output is not an intact staged "
            "documentation directory"
        )


def rewrite_links(text: str) -> str:
    for source_name, remote_name in DOCUMENTS.items():
        text = text.replace(source_name, remote_name)
    return text


def validate_staged_links(documents: dict[str, str]) -> None:
    names = set(documents)
    for remote_name, text in documents.items():
        for match in MARKDOWN_LINK_RE.finditer(text):
            target = Path(match.group(1)).name
            if target not in names:
                raise StagingError(
                    f"{remote_name} links to absent staged document {target}"
                )


def stage(source_root: Path, output_dir: Path, overwrite: bool = False) -> list[Path]:
    source_root = source_root.expanduser().resolve()
    output_candidate = output_dir.expanduser().absolute()
    if not source_root.is_dir():
        raise StagingError(f"Documentation source directory does not exist: {source_root}")
    if output_candidate.exists():
        if not overwrite:
            raise StagingError(
                f"Output already exists; pass --overwrite after review: {output_candidate}"
            )
        validate_existing_output(output_candidate)

    documents: dict[str, str] = {}
    for source_name, remote_name in DOCUMENTS.items():
        source = source_root / source_name
        if source.is_symlink() or not source.is_file():
            raise StagingError(f"Required documentation source is missing: {source}")
        documents[remote_name] = rewrite_links(source.read_text(encoding="utf-8"))
    validate_staged_links(documents)

    output_parent = output_candidate.parent
    output_parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_candidate.name}.", dir=output_parent)
    )
    try:
        for remote_name, text in documents.items():
            path = temporary / remote_name
            path.write_text(text, encoding="utf-8")
            os.chmod(path, 0o644)
        if output_candidate.exists():
            validate_existing_output(output_candidate)
            for remote_name in sorted(DOCUMENTS.values()):
                (output_candidate / remote_name).unlink()
            output_candidate.rmdir()
        os.replace(temporary, output_candidate)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return [output_candidate / name for name in DOCUMENTS.values()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Stage the lymphoma dataset, tutorial, validation, and publishing "
            "documents under flat Zenodo names with validated relative links."
        )
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs",
        help="Repository docs directory (default: <repository>/docs)",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        paths = stage(args.source_root, args.output_dir, args.overwrite)
    except (OSError, UnicodeError, StagingError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
