#!/usr/bin/env python3
"""Prepare de-identified manifests for a lymphoma WSI Zenodo deposit.

This command never copies slide pixels.  It validates complete L0/L2 export
pairs, assigns deterministic public aliases, scans TIFF metadata for source
identifiers, and emits small public artifacts plus a separate private mapping.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import tifffile


PUBLIC_MANIFEST = "tumorquantai_lymphoma_manifest.csv"
PUBLIC_SAMPLES = "samples.csv"
VALIDATION_REPORT = "tiff_validation_report.json"
SHA256SUMS = "SHA256SUMS"
MD5SUMS = "MD5SUMS"
GENERATED_PUBLIC_FILES = frozenset(
    {PUBLIC_MANIFEST, PUBLIC_SAMPLES, VALIDATION_REPORT, SHA256SUMS, MD5SUMS}
)
ALIAS_RE = re.compile(r"^TumorQuantAI_LymphomaWSI_[0-9]{3}$")
SENSITIVE_TIFF_TAGS = {
    "artist",
    "copyright",
    "documentname",
    "datetime",
    "hostname",
    "hostcomputer",
    "ownername",
    "pagename",
}
PUBLIC_COLUMNS = (
    "alias",
    "level",
    "source_mpp",
    "zenodo_filename",
    "dataset_path",
    "size_bytes",
    "sha256",
    "md5",
    "width",
    "height",
    "channels",
    "dtype",
    "photometric",
    "is_tiled",
)
PRIVATE_COLUMNS = (
    "alias",
    "level",
    "slide_id",
    "source_path",
    "relative_parent",
    "export_path",
    "zenodo_filename",
    "sha256",
    "md5",
)


class PreparationError(RuntimeError):
    """Raised when a source cannot safely be prepared for publication."""


@dataclass(frozen=True)
class Export:
    slide_id: str
    source_path: str
    relative_parent: str
    level: int
    output_path: Path


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def require_private_location(public_dir: Path, private_mapping: Path) -> None:
    public = public_dir.expanduser().resolve()
    private_candidate = private_mapping.expanduser().absolute()
    if private_candidate.exists() and private_candidate.is_symlink():
        raise PreparationError(f"Refusing a symlink private mapping: {private_candidate}")
    private = private_candidate.resolve()
    if private == public or is_within(private, public):
        raise PreparationError(
            "--private-mapping must be outside --public-output; source identifiers "
            "must never be placed in the public artifact tree"
        )


def validate_replaceable_public_output(path: Path) -> None:
    """Allow --overwrite only for a complete directory created by this tool."""
    if path.is_symlink() or not path.is_dir():
        raise PreparationError(f"Refusing to replace unsafe output: {path}")
    entries = list(path.iterdir())
    names = {entry.name for entry in entries}
    unsafe = [
        entry.name for entry in entries if entry.is_symlink() or not entry.is_file()
    ]
    if unsafe or names != GENERATED_PUBLIC_FILES:
        details = []
        if unsafe:
            details.append("non-regular entries: " + ", ".join(sorted(unsafe)))
        missing = GENERATED_PUBLIC_FILES - names
        extra = names - GENERATED_PUBLIC_FILES
        if missing:
            details.append("missing generated files: " + ", ".join(sorted(missing)))
        if extra:
            details.append("unexpected files: " + ", ".join(sorted(extra)))
        raise PreparationError(
            "Refusing --overwrite because the existing public directory is not "
            f"an intact output from this tool ({'; '.join(details)})"
        )


def remove_generated_public_output(path: Path) -> None:
    validate_replaceable_public_output(path)
    for name in sorted(GENERATED_PUBLIC_FILES):
        (path / name).unlink()
    path.rmdir()


def load_complete_exports(manifest: Path, expected_pairs: int | None) -> list[list[Export]]:
    manifest = manifest.expanduser().resolve()
    if not manifest.is_file():
        raise PreparationError(f"Export manifest does not exist: {manifest}")
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "slide_id",
            "source_path",
            "relative_parent",
            "level",
            "output_path",
            "status",
        }
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise PreparationError(
                "Export manifest is missing required columns: "
                + ", ".join(sorted(required - set(reader.fieldnames or [])))
            )
        grouped: dict[str, dict[int, Export]] = {}
        successful_ids: set[str] = set()
        for line_number, row in enumerate(reader, start=2):
            if str(row.get("status", "")).strip().casefold() != "exported":
                continue
            slide_id = str(row.get("slide_id", "")).strip()
            if not slide_id:
                raise PreparationError(f"Empty slide_id at {manifest}:{line_number}")
            try:
                level = int(str(row.get("level", "")).strip())
            except ValueError as exc:
                raise PreparationError(
                    f"Invalid level at {manifest}:{line_number}"
                ) from exc
            if level not in {0, 2}:
                continue
            successful_ids.add(slide_id)
            output_candidate = Path(
                str(row.get("output_path", "")).strip()
            ).expanduser().absolute()
            if output_candidate.is_symlink():
                raise PreparationError(
                    f"Refusing symlink exported TIFF at {manifest}:{line_number}"
                )
            output = output_candidate.resolve()
            export = Export(
                slide_id=slide_id,
                source_path=str(row.get("source_path", "")).strip(),
                relative_parent=str(row.get("relative_parent", "")).strip(),
                level=level,
                output_path=output,
            )
            levels = grouped.setdefault(slide_id, {})
            if level in levels:
                raise PreparationError(
                    f"Duplicate exported L{level} row for source slide {slide_id!r}"
                )
            levels[level] = export

    incomplete = sorted(
        (slide_id for slide_id in successful_ids if set(grouped[slide_id]) != {0, 2}),
        key=lambda value: value.casefold(),
    )
    if incomplete:
        raise PreparationError(
            f"Exported slides without exactly one L0 and one L2 companion: {len(incomplete)}"
        )
    pairs = [
        [grouped[slide_id][0], grouped[slide_id][2]]
        for slide_id in sorted(grouped, key=lambda value: value.casefold())
        if set(grouped[slide_id]) == {0, 2}
    ]
    if not pairs:
        raise PreparationError("No complete exported L0/L2 pairs were found")
    if expected_pairs is not None and len(pairs) != expected_pairs:
        raise PreparationError(
            f"Expected {expected_pairs} complete L0/L2 pairs, found {len(pairs)}"
        )
    missing = [export.output_path for pair in pairs for export in pair if not export.output_path.is_file()]
    if missing:
        raise PreparationError(f"{len(missing)} exported TIFF file(s) are missing")
    return pairs


def iter_text_values(value: object) -> Iterable[str]:
    if isinstance(value, bytes):
        yield value.decode("utf-8", errors="replace")
    elif isinstance(value, str):
        yield value
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from iter_text_values(item)


def source_markers(export: Export) -> set[str]:
    markers = {
        export.slide_id,
        export.relative_parent,
        export.source_path,
        str(Path(export.source_path).parent),
    }
    # Short generic values such as "1.mds" create false positives.
    return {item.casefold() for item in markers if len(item.strip()) >= 6}


def validate_tiff(path: Path, export: Export) -> dict[str, object]:
    """Read technical TIFF metadata and fail on embedded source identifiers."""
    try:
        with tifffile.TiffFile(path) as tif:
            if not tif.pages:
                raise PreparationError(f"TIFF contains no image pages: {path}")
            page = tif.pages[0]
            height = int(page.imagelength)
            width = int(page.imagewidth)
            channels = int(page.samplesperpixel)
            if height <= 0 or width <= 0 or channels not in {1, 3, 4}:
                raise PreparationError(f"TIFF has invalid dimensions/channels: {path}")
            markers = source_markers(export)
            sensitive_names: list[str] = []
            identifier_hits: list[str] = []
            for page_number, candidate_page in enumerate(tif.pages):
                for tag in candidate_page.tags.values():
                    name = str(tag.name)
                    qualified_name = f"page[{page_number}].{name}"
                    try:
                        values = list(iter_text_values(tag.value))
                    except (ValueError, TypeError, UnicodeError):
                        values = []
                    nonempty = [value for value in values if value.strip()]
                    if name.casefold() in SENSITIVE_TIFF_TAGS and nonempty:
                        sensitive_names.append(qualified_name)
                    for text in nonempty:
                        folded = text.casefold()
                        if any(marker in folded for marker in markers):
                            identifier_hits.append(qualified_name)
            if sensitive_names or identifier_hits:
                details = []
                if sensitive_names:
                    details.append("sensitive tags: " + ", ".join(sorted(set(sensitive_names))))
                if identifier_hits:
                    details.append(
                        "source identifier present in tags: "
                        + ", ".join(sorted(set(identifier_hits)))
                    )
                raise PreparationError(
                    "TIFF metadata privacy validation failed for "
                    f"{path.name} ({'; '.join(details)})"
                )
            photometric = getattr(page.photometric, "name", str(page.photometric))
            return {
                "width": width,
                "height": height,
                "channels": channels,
                "dtype": str(page.dtype),
                "photometric": photometric,
                "is_tiled": bool(page.is_tiled),
                "page_count": len(tif.pages),
                "sensitive_tag_count": 0,
                "source_identifier_hit_count": 0,
            }
    except PreparationError:
        raise
    except (OSError, ValueError, tifffile.TiffFileError) as exc:
        raise PreparationError(f"Cannot validate TIFF {path}: {exc}") from exc


def checksums(path: Path, chunk_size: int = 8 * 1024 * 1024) -> tuple[str, str, os.stat_result]:
    before = path.stat()
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            sha256.update(chunk)
            md5.update(chunk)
    after = path.stat()
    identity = lambda item: (
        item.st_dev,
        item.st_ino,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
    )
    if identity(before) != identity(after):
        raise PreparationError(f"File changed while checksums were computed: {path}")
    return sha256.hexdigest(), md5.hexdigest(), after


def write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_private_mapping(path: Path, rows: list[dict[str, object]], overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise PreparationError(f"Private mapping already exists: {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=PRIVATE_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def prepare(
    export_manifest: Path,
    public_output: Path,
    private_mapping: Path,
    source_mpp: float,
    expected_pairs: int | None = None,
    overwrite: bool = False,
) -> dict[str, object]:
    if not math.isfinite(float(source_mpp)) or float(source_mpp) <= 0:
        raise PreparationError("--source-mpp must be a finite value > 0")
    source_mpp = float(source_mpp)
    require_private_location(public_output, private_mapping)
    public_candidate = public_output.expanduser().absolute()
    if public_candidate.is_symlink():
        raise PreparationError(f"Refusing a symlink public output: {public_candidate}")
    public_output = public_output.expanduser().resolve()
    private_mapping = private_mapping.expanduser().resolve()
    if public_output.exists() and not overwrite:
        raise PreparationError(f"Public output already exists: {public_output}")
    if public_output.exists():
        validate_replaceable_public_output(public_output)
    if private_mapping.exists() and not overwrite:
        raise PreparationError(f"Private mapping already exists: {private_mapping}")
    pairs = load_complete_exports(export_manifest, expected_pairs)
    public_rows: list[dict[str, object]] = []
    private_rows: list[dict[str, object]] = []
    validation_rows: list[dict[str, object]] = []

    for index, pair in enumerate(pairs, start=1):
        alias = f"TumorQuantAI_LymphomaWSI_{index:03d}"
        if not ALIAS_RE.fullmatch(alias):  # defensive invariant
            raise PreparationError(f"Invalid generated public alias: {alias}")
        for export in pair:
            metadata = validate_tiff(export.output_path, export)
            sha256, md5, file_stat = checksums(export.output_path)
            zenodo_filename = f"{alias}_L{export.level}_rgb.tif"
            dataset_path = f"slides/{alias}/1_L{export.level}_rgb.tif"
            public_row = {
                "alias": alias,
                "level": export.level,
                "source_mpp": f"{source_mpp:.6f}",
                "zenodo_filename": zenodo_filename,
                "dataset_path": dataset_path,
                "size_bytes": file_stat.st_size,
                "sha256": sha256,
                "md5": md5,
                **{key: metadata[key] for key in (
                    "width",
                    "height",
                    "channels",
                    "dtype",
                    "photometric",
                    "is_tiled",
                )},
            }
            public_rows.append(public_row)
            private_rows.append(
                {
                    "alias": alias,
                    "level": export.level,
                    "slide_id": export.slide_id,
                    "source_path": export.source_path,
                    "relative_parent": export.relative_parent,
                    "export_path": str(export.output_path),
                    "zenodo_filename": zenodo_filename,
                    "sha256": sha256,
                    "md5": md5,
                }
            )
            validation_rows.append(
                {
                    "alias": alias,
                    "level": export.level,
                    "zenodo_filename": zenodo_filename,
                    **metadata,
                    "status": "passed",
                }
            )

    public_output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{public_output.name}.", dir=public_output.parent))
    os.chmod(temporary, 0o755)
    try:
        write_csv(temporary / PUBLIC_MANIFEST, PUBLIC_COLUMNS, public_rows)
        sample_rows = [
            {
                "sample_id": row["alias"],
                "slide_path": str(row["dataset_path"]).removeprefix("slides/"),
            }
            for row in public_rows
            if row["level"] == 0
        ]
        write_csv(temporary / PUBLIC_SAMPLES, ("sample_id", "slide_path"), sample_rows)
        (temporary / SHA256SUMS).write_text(
            "".join(f"{row['sha256']}  {row['zenodo_filename']}\n" for row in public_rows),
            encoding="utf-8",
        )
        (temporary / MD5SUMS).write_text(
            "".join(f"{row['md5']}  {row['zenodo_filename']}\n" for row in public_rows),
            encoding="utf-8",
        )
        report = {
            "schema_version": 1,
            "status": "passed",
            "pair_count": len(pairs),
            "file_count": len(public_rows),
            "total_size_bytes": sum(int(row["size_bytes"]) for row in public_rows),
            "source_mpp": source_mpp,
            "source_mpp_provenance": (
                "operator-supplied --source-mpp; see release documentation for "
                "verification evidence"
            ),
            "privacy_scope": (
                "TIFF metadata was checked for configured sensitive tags and exact "
                "source identifiers. This is a technical screen, not a substitute "
                "for institutional de-identification and rights review."
            ),
            "files": validation_rows,
        }
        (temporary / VALIDATION_REPORT).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        write_private_mapping(private_mapping.expanduser().resolve(), private_rows, overwrite)
        if public_output.exists():
            remove_generated_public_output(public_output)
        os.replace(temporary, public_output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)

    return {
        "public_output": str(public_output),
        "private_mapping": str(private_mapping.expanduser().resolve()),
        "pair_count": len(pairs),
        "file_count": len(public_rows),
        "total_size_bytes": sum(int(row["size_bytes"]) for row in public_rows),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-manifest", required=True, type=Path)
    parser.add_argument("--public-output", required=True, type=Path)
    parser.add_argument(
        "--private-mapping",
        required=True,
        type=Path,
        help="CSV path outside the public output tree; written with mode 0600",
    )
    parser.add_argument("--source-mpp", required=True, type=float)
    parser.add_argument("--expected-pairs", type=int)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing generated public artifacts and private mapping",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = prepare(
            args.export_manifest,
            args.public_output,
            args.private_mapping,
            args.source_mpp,
            args.expected_pairs,
            args.overwrite,
        )
    except (PreparationError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
