#!/usr/bin/env python3
"""Discover collision-safe primary whole-slide images for the workflow."""

from __future__ import annotations

import argparse
import csv
import fnmatch
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable


DEFAULT_PATTERNS = ("*_L0_rgb.tif", "*_L0_rgb.tiff")
MANIFEST_COLUMNS = (
    "sample_id",
    "slide_path",
    "relative_path",
    "size_bytes",
    "mtime_ns",
    "ctime_ns",
    "device",
    "inode",
    "fingerprint",
    "l2_path",
    "l2_exists",
    "l2_size_bytes",
    "l2_mtime_ns",
    "l2_content_sha256",
    "l2_fingerprint",
)
RESERVED_SAMPLE_IDS = {
    "aggregated_celltypes",
    "workflow_metadata",
    "class_id",
    "cell_type",
    "slides.tsv",
    "slides.json",
    "workflow_aggregation_manifest.csv",
    "build_workflow_manifest.py",
    "aggregate_histoplus_celltypes.py",
    "workflow_bin",
}


class DiscoveryError(RuntimeError):
    pass


def natural_key(value: str) -> list[tuple[int, object]]:
    return [
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", str(value))
    ]


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    if not slug:
        raise DiscoveryError(f"Could not derive a sample ID from {value!r}")
    return slug


def inferred_sample_id(relative_path: Path) -> str:
    name = relative_path.name
    stem = re.sub(r"(?i)_L0_rgb\.tiff?$", "", name)
    components = [*relative_path.parent.parts, stem]
    components = [part for part in components if part not in {"", "."}]
    return slugify("_".join(components))


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def fingerprint(path: Path, stat_result) -> str:
    payload = (
        f"{path.resolve()}\0{stat_result.st_size}\0{stat_result.st_mtime_ns}"
        f"\0{stat_result.st_ctime_ns}\0{stat_result.st_dev}\0{stat_result.st_ino}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def l2_companion_path(l0_path: Path) -> Path:
    return l0_path.with_name(l0_path.name.replace("_L0_", "_L2_"))


def content_sha256(path: Path) -> tuple[str, os.stat_result]:
    """Stream-hash a companion and fail if it changes during discovery."""
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if before_identity != after_identity:
        raise DiscoveryError(f"Companion L2 changed while it was fingerprinted: {path}")
    return digest.hexdigest(), after


def l2_manifest_fields(l0_path: Path, policy: str) -> dict[str, str | int | bool]:
    if policy == "ignore":
        return {
            "l2_path": "",
            "l2_exists": False,
            "l2_size_bytes": "",
            "l2_mtime_ns": "",
            "l2_content_sha256": "",
            "l2_fingerprint": "not_used",
        }

    companion = l2_companion_path(l0_path).resolve()
    if not companion.is_file():
        if policy == "required":
            raise DiscoveryError(
                f"Sampled/fast processing requires the companion L2 export: {companion}"
            )
        return {
            "l2_path": str(companion),
            "l2_exists": False,
            "l2_size_bytes": "",
            "l2_mtime_ns": "",
            "l2_content_sha256": "",
            "l2_fingerprint": "missing",
        }

    try:
        digest, stat_result = content_sha256(companion)
    except OSError as exc:
        raise DiscoveryError(f"Could not fingerprint companion L2 {companion}: {exc}") from exc
    return {
        "l2_path": str(companion),
        "l2_exists": True,
        "l2_size_bytes": stat_result.st_size,
        "l2_mtime_ns": stat_result.st_mtime_ns,
        "l2_content_sha256": digest,
        "l2_fingerprint": f"sha256:{digest}",
    }


def row_for_path(
    input_root: Path,
    path: Path,
    sample_id: str | None = None,
    l2_policy: str = "ignore",
) -> dict[str, str | int | bool]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise DiscoveryError(f"Slide does not exist or is not a file: {resolved}")
    try:
        relative = resolved.relative_to(input_root)
    except ValueError as exc:
        raise DiscoveryError(f"Slide is outside --input-root: {resolved}") from exc
    stat_result = resolved.stat()
    row: dict[str, str | int | bool] = {
        "sample_id": slugify(sample_id) if sample_id else inferred_sample_id(relative),
        "slide_path": str(resolved),
        "relative_path": relative.as_posix(),
        "size_bytes": stat_result.st_size,
        "mtime_ns": stat_result.st_mtime_ns,
        "ctime_ns": stat_result.st_ctime_ns,
        "device": stat_result.st_dev,
        "inode": stat_result.st_ino,
        "fingerprint": fingerprint(resolved, stat_result),
    }
    row.update(l2_manifest_fields(resolved, l2_policy))
    return row


def load_sample_sheet(
    input_root: Path,
    path: Path,
    l2_policy: str = "ignore",
) -> list[dict[str, str | int | bool]]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise DiscoveryError(f"Sample sheet does not exist: {path}")
    delimiter = "\t" if path.suffix.lower() in {".tsv", ".txt"} else ","
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        if reader.fieldnames is None or not {"sample_id", "slide_path"}.issubset(reader.fieldnames):
            raise DiscoveryError("Sample sheet must contain sample_id and slide_path columns")
        rows = []
        for line_number, source in enumerate(reader, start=2):
            sample_id = str(source.get("sample_id", "")).strip()
            raw_path = str(source.get("slide_path", "")).strip()
            if not sample_id or not raw_path:
                raise DiscoveryError(f"Empty sample_id or slide_path at {path}:{line_number}")
            slide_path = Path(raw_path).expanduser()
            if not slide_path.is_absolute():
                slide_path = input_root / slide_path
            rows.append(row_for_path(input_root, slide_path, sample_id, l2_policy))
    return rows


def discover_paths(
    input_root: Path,
    patterns: Iterable[str],
    excluded_roots: Iterable[Path],
) -> list[Path]:
    excluded = [path.expanduser().resolve() for path in excluded_roots]
    found: set[Path] = set()
    for pattern in patterns:
        for path in input_root.rglob(pattern):
            resolved = path.resolve()
            if any(is_within(resolved, root) for root in excluded):
                continue
            if any(part.startswith(".") for part in path.relative_to(input_root).parts):
                continue
            if resolved.is_file():
                found.add(resolved)
    return sorted(found, key=lambda path: natural_key(path.relative_to(input_root).as_posix()))


def validate_rows(rows: list[dict[str, str | int | bool]]) -> None:
    if not rows:
        raise DiscoveryError("No primary slides matched the requested patterns")
    reserved = sorted(
        {str(row["sample_id"]) for row in rows if str(row["sample_id"]).casefold() in RESERVED_SAMPLE_IDS},
        key=natural_key,
    )
    if reserved:
        raise DiscoveryError(
            "Sample IDs collide with workflow-owned directories: " + ", ".join(reserved)
        )
    by_id: dict[str, list[str]] = {}
    by_path: dict[str, list[str]] = {}
    for row in rows:
        by_id.setdefault(str(row["sample_id"]), []).append(str(row["slide_path"]))
        by_path.setdefault(str(row["slide_path"]), []).append(str(row["sample_id"]))
    duplicate_ids = {key: values for key, values in by_id.items() if len(values) > 1}
    duplicate_paths = {key: values for key, values in by_path.items() if len(values) > 1}
    if duplicate_ids:
        details = "; ".join(
            f"{sample_id} -> {', '.join(paths)}"
            for sample_id, paths in sorted(duplicate_ids.items(), key=lambda item: natural_key(item[0]))
        )
        raise DiscoveryError(f"Duplicate sample IDs; use --sample-sheet to disambiguate: {details}")
    if duplicate_paths:
        details = "; ".join(
            f"{path} -> {', '.join(sample_ids)}" for path, sample_ids in duplicate_paths.items()
        )
        raise DiscoveryError(f"A slide path is listed more than once: {details}")


def write_manifest(path: Path, rows: list[dict[str, str | int | bool]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Discover primary L0 TIFF slides and write a collision-safe TSV manifest. "
            "Companion L2/L3 files and excluded output directories are not selected."
        )
    )
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Output TSV manifest")
    parser.add_argument(
        "--pattern",
        action="append",
        default=None,
        help="Primary-slide glob; repeat for multiple patterns (default: *_L0_rgb.tif[f])",
    )
    parser.add_argument("--include", default="*", help="fnmatch filter over inferred sample IDs")
    parser.add_argument("--exclude", default="", help="fnmatch filter over inferred sample IDs")
    parser.add_argument(
        "--exclude-root",
        action="append",
        type=Path,
        default=[],
        help="Directory tree to prune; repeat as needed",
    )
    parser.add_argument(
        "--sample-sheet",
        type=Path,
        default=None,
        help="Optional CSV/TSV with explicit sample_id,slide_path columns",
    )
    parser.add_argument(
        "--l2-policy",
        choices=("ignore", "optional", "required"),
        default="ignore",
        help=(
            "Companion L2 handling: ignore for full runs, optional for manual audits, "
            "or required when sampled outputs consume L2. Used by the Nextflow wrapper."
        ),
    )
    parser.add_argument("--json", type=Path, default=None, help="Optional JSON copy of the manifest")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        input_root = args.input_root.expanduser().resolve()
        if not input_root.is_dir():
            raise DiscoveryError(f"Input root is not a directory: {input_root}")
        if args.sample_sheet is not None:
            rows = load_sample_sheet(input_root, args.sample_sheet, args.l2_policy)
        else:
            paths = discover_paths(input_root, args.pattern or DEFAULT_PATTERNS, args.exclude_root)
            rows = [row_for_path(input_root, path, l2_policy=args.l2_policy) for path in paths]
        rows = [
            row
            for row in rows
            if fnmatch.fnmatch(str(row["sample_id"]), args.include)
            and (not args.exclude or not fnmatch.fnmatch(str(row["sample_id"]), args.exclude))
        ]
        rows.sort(key=lambda row: natural_key(str(row["sample_id"])))
        validate_rows(rows)
        write_manifest(args.output, rows)
        if args.json is not None:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps({"slides": rows}, indent=2) + "\n", encoding="utf-8")
    except DiscoveryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"Discovered {len(rows)} primary slide(s)")
    print(f"Manifest: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
