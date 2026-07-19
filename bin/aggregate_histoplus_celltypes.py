#!/usr/bin/env python3
"""Build HistoPLUS cell-type-by-sample count and fraction matrices.

The LazySlide/HistoPLUS pipeline writes one compact count table per completed
slide::

    <results-root>/<slide_id>/cell_types/class_counts.csv

This script validates those tables against each slide's ``summary.json`` and
the optional ``fast_batch_manifest.csv``, then writes matrices in the familiar
feature-by-sample orientation used by single-cell workflows.  A cell type that
was not detected in a *completed* slide is represented by zero.  Incomplete or
failed slides are excluded from the matrices and retained in the audit table;
they are never misrepresented as biological zeroes.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


DEFAULT_INPUT_ROOT = Path(".")
REQUIRED_COUNT_COLUMNS = ("class_id", "class_name", "count")


class AggregationError(RuntimeError):
    """Raised when an input would make the aggregate matrix unreliable."""


def natural_key(value: str) -> list[tuple[int, object]]:
    """Return a deterministic human-friendly ordering key."""

    return [
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", str(value))
    ]


def parse_bool(value: Any, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        raise AggregationError(f"Missing boolean value for {field}")
    normalized = str(value).strip().casefold()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise AggregationError(f"Invalid boolean value for {field}: {value!r}")


def optional_int(value: Any, *, field: str) -> int | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AggregationError(f"Invalid integer value for {field}: {value!r}") from exc
    if not math.isfinite(number) or not number.is_integer():
        raise AggregationError(f"Invalid integer value for {field}: {value!r}")
    return int(number)


def read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise AggregationError(f"Could not read JSON file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AggregationError(f"Expected a JSON object in {path}")
    return payload


def find_manifest(args: argparse.Namespace, input_root: Path) -> Path | None:
    if args.ignore_manifest:
        return None
    if args.manifest is not None:
        manifest = args.manifest.expanduser().resolve()
        if not manifest.is_file():
            raise AggregationError(f"Manifest does not exist: {manifest}")
        return manifest
    candidates = [
        input_root / "workflow_aggregation_manifest.csv",
        input_root / "fast_batch_manifest.csv",
    ]
    existing = [candidate for candidate in candidates if candidate.is_file()]
    if len(existing) > 1:
        raise AggregationError(
            "Multiple aggregation manifests were found; select one explicitly with --manifest: "
            + ", ".join(str(path) for path in existing)
        )
    return existing[0] if existing else None


def load_manifest(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    try:
        table = pd.read_csv(path)
    except Exception as exc:
        raise AggregationError(f"Could not read batch manifest {path}: {exc}") from exc
    required = {"slide_id", "completed"}
    missing = sorted(required.difference(table.columns))
    if missing:
        raise AggregationError(
            f"Manifest {path} is missing required column(s): {', '.join(missing)}"
        )
    table["slide_id"] = table["slide_id"].astype(str).str.strip()
    if (table["slide_id"] == "").any():
        raise AggregationError(f"Manifest {path} contains an empty slide_id")
    duplicates = table.loc[table["slide_id"].duplicated(keep=False), "slide_id"].tolist()
    if duplicates:
        raise AggregationError(
            f"Manifest {path} contains duplicate slide_id values: "
            + ", ".join(sorted(set(duplicates), key=natural_key))
        )
    return {str(row["slide_id"]): row.to_dict() for _, row in table.iterrows()}


def discover_slide_files(input_root: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    """Discover only canonical per-slide files, excluding ROI/QC count tables."""

    count_paths: dict[str, Path] = {}
    summary_paths: dict[str, Path] = {}
    for path in sorted(input_root.glob("*/cell_types/class_counts.csv")):
        slide_id = path.parents[1].name
        if slide_id in count_paths:
            raise AggregationError(f"Duplicate class-count file for sample {slide_id}")
        count_paths[slide_id] = path
    for path in sorted(input_root.glob("*/summary/summary.json")):
        slide_id = path.parents[1].name
        if slide_id in summary_paths:
            raise AggregationError(f"Duplicate summary file for sample {slide_id}")
        summary_paths[slide_id] = path
    return count_paths, summary_paths


def read_count_table(path: Path, slide_id: str) -> pd.DataFrame:
    try:
        table = pd.read_csv(path)
    except Exception as exc:
        raise AggregationError(f"Could not read counts for {slide_id} from {path}: {exc}") from exc

    missing = [column for column in REQUIRED_COUNT_COLUMNS if column not in table.columns]
    if missing:
        raise AggregationError(
            f"Count table for {slide_id} is missing column(s): {', '.join(missing)}"
        )
    table = table.loc[:, REQUIRED_COUNT_COLUMNS].copy()
    table["class_name"] = table["class_name"].astype("string").str.strip()
    if table["class_name"].isna().any() or (table["class_name"] == "").any():
        raise AggregationError(f"Count table for {slide_id} contains an empty class_name")

    for column in ("class_id", "count"):
        numeric = pd.to_numeric(table[column], errors="coerce")
        invalid = numeric.isna() | ~numeric.map(math.isfinite) | (numeric % 1 != 0)
        if invalid.any():
            values = table.loc[invalid, column].astype(str).tolist()
            raise AggregationError(
                f"Count table for {slide_id} has non-integer {column} value(s): {values}"
            )
        table[column] = numeric.astype("int64")
    if (table["count"] < 0).any():
        raise AggregationError(f"Count table for {slide_id} contains negative counts")
    if (table["count"] == 0).any():
        raise AggregationError(f"Count table for {slide_id} contains zero-count class rows")

    duplicate_rows = table.duplicated(["class_id", "class_name"], keep=False)
    if duplicate_rows.any():
        pairs = table.loc[duplicate_rows, ["class_id", "class_name"]].drop_duplicates()
        rendered = [f"{row.class_id}:{row.class_name}" for row in pairs.itertuples(index=False)]
        raise AggregationError(
            f"Count table for {slide_id} contains duplicate class rows: {', '.join(rendered)}"
        )
    return table


def summary_fields(summary: dict[str, Any]) -> dict[str, Any]:
    sampling = summary.get("tile_sampling")
    if not isinstance(sampling, dict):
        sampling = {}
    return {
        "percent_slide": sampling.get("percent_slide"),
        "random_seed": sampling.get("random_seed"),
        "n_tiles_total": sampling.get("n_tiles_total"),
        "n_tiles_sampled": sampling.get("n_tiles_sampled"),
    }


def load_sample_map(
    path: Path | None,
    included_ids: Iterable[str],
    roster_ids: Iterable[str] | None = None,
) -> dict[str, str]:
    included = set(included_ids)
    roster = set(roster_ids) if roster_ids is not None else set(included)
    if not included.issubset(roster):
        raise AggregationError("Internal error: included slide IDs are absent from the audit roster")
    if path is None:
        return {slide_id: slide_id for slide_id in roster}
    path = path.expanduser().resolve()
    try:
        table = pd.read_csv(path, dtype=str)
    except Exception as exc:
        raise AggregationError(f"Could not read sample map {path}: {exc}") from exc
    required = {"slide_id", "sample_id"}
    missing_columns = sorted(required.difference(table.columns))
    if missing_columns:
        raise AggregationError(
            f"Sample map {path} is missing column(s): {', '.join(missing_columns)}"
        )
    table = table.loc[:, ["slide_id", "sample_id"]].copy()
    for column in ("slide_id", "sample_id"):
        if table[column].isna().any():
            raise AggregationError(f"Sample map {path} contains an empty {column}")
        table[column] = table[column].astype(str).str.strip()
        if (table[column] == "").any():
            raise AggregationError(f"Sample map {path} contains an empty {column}")
    reserved_sample_ids = sorted(
        {
            value
            for value in table["sample_id"].tolist()
            if value.casefold() in {"class_id", "cell_type"}
        },
        key=natural_key,
    )
    if reserved_sample_ids:
        raise AggregationError(
            "Sample map uses matrix-header-reserved sample_id value(s): "
            + ", ".join(reserved_sample_ids)
        )
    duplicates = table.loc[table["slide_id"].duplicated(keep=False), "slide_id"].tolist()
    if duplicates:
        raise AggregationError(
            f"Sample map {path} contains duplicate slide_id values: "
            + ", ".join(sorted(set(duplicates), key=natural_key))
        )
    mapping = dict(zip(table["slide_id"], table["sample_id"]))
    missing_ids = sorted(roster.difference(mapping), key=natural_key)
    if missing_ids:
        raise AggregationError(
            "Sample map does not cover aggregation-roster slide(s): "
            + ", ".join(missing_ids)
        )
    return {slide_id: mapping[slide_id] for slide_id in roster}


def validate_class_mapping(long_table: pd.DataFrame) -> None:
    by_name = long_table.groupby("class_name")["class_id"].nunique()
    conflicting_names = by_name[by_name > 1].index.tolist()
    if conflicting_names:
        raise AggregationError(
            "Cell-type name(s) map to multiple class IDs: " + ", ".join(conflicting_names)
        )

    known = long_table.loc[long_table["class_id"] >= 0]
    by_id = known.groupby("class_id")["class_name"].nunique()
    conflicting_ids = by_id[by_id > 1].index.tolist()
    if conflicting_ids:
        raise AggregationError(
            "Class ID(s) map to multiple cell-type names: "
            + ", ".join(str(value) for value in conflicting_ids)
        )


def matrix_from_long(long_table: pd.DataFrame, sample_ids: Iterable[str]) -> pd.DataFrame:
    grouped = (
        long_table.groupby(["class_id", "class_name", "sample_id"], as_index=False)["count"]
        .sum()
    )
    ordered_columns = sorted({str(value) for value in sample_ids}, key=natural_key)
    if grouped.empty:
        empty_index = pd.MultiIndex.from_arrays([[], []], names=["class_id", "cell_type"])
        return pd.DataFrame(index=empty_index, columns=ordered_columns, dtype="int64")
    matrix = grouped.pivot(
        index=["class_id", "class_name"], columns="sample_id", values="count"
    ).fillna(0)
    matrix = matrix.astype("int64")
    ordered_rows = sorted(
        matrix.index.tolist(),
        key=lambda pair: (pair[0] < 0, pair[0] if pair[0] >= 0 else 0, pair[1].casefold()),
    )
    matrix = matrix.reindex(index=ordered_rows, columns=ordered_columns, fill_value=0)
    matrix.index = matrix.index.set_names(["class_id", "cell_type"])
    matrix.columns.name = None
    return matrix


def portable_path(path: Path | None, root: Path) -> str:
    if path is None:
        return ""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def aggregate(args: argparse.Namespace) -> dict[str, Any]:
    input_root = args.input_root.expanduser().resolve()
    if not input_root.is_dir():
        raise AggregationError(f"Input root is not a directory: {input_root}")
    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir is not None
        else input_root / "aggregated_celltypes"
    )
    manifest_path = find_manifest(args, input_root)
    manifest = load_manifest(manifest_path)
    count_paths, summary_paths = discover_slide_files(input_root)

    # When present, the manifest is authoritative so stale result folders cannot leak into a matrix.
    all_slide_ids = set(manifest) if manifest_path is not None else set(count_paths) | set(summary_paths)
    if not all_slide_ids:
        raise AggregationError(
            f"No per-slide class_counts.csv, summary.json, or manifest rows found under {input_root}"
        )

    included_tables: dict[str, pd.DataFrame] = {}
    included_summaries: dict[str, dict[str, Any]] = {}
    audit_rows: list[dict[str, Any]] = []

    for slide_id in sorted(all_slide_ids, key=natural_key):
        manifest_row = manifest.get(slide_id)
        count_path = count_paths.get(slide_id)
        summary_path = summary_paths.get(slide_id)
        manifest_completed: bool | None = None
        manifest_selected: bool | None = None
        returncode: int | None = None
        log_file: str | None = None
        if manifest_row is not None:
            manifest_completed = parse_bool(
                manifest_row.get("completed"), field=f"{slide_id}.completed"
            )
            raw_selected = manifest_row.get("selected", True)
            manifest_selected = (
                True
                if raw_selected is None or pd.isna(raw_selected) or str(raw_selected).strip() == ""
                else parse_bool(raw_selected, field=f"{slide_id}.selected")
            )
            returncode = optional_int(
                manifest_row.get("returncode"), field=f"{slide_id}.returncode"
            )
            raw_log = manifest_row.get("log_file")
            if raw_log is not None and not pd.isna(raw_log) and str(raw_log).strip():
                log_file = str(raw_log)

        eligible = (
            bool(manifest_selected) and bool(manifest_completed) and (returncode is None or returncode == 0)
            if manifest_row is not None
            else summary_path is not None
        )
        reason = ""
        status = "included"
        if not eligible:
            status = "excluded_unselected" if manifest_selected is False else "excluded_incomplete"
            if manifest_selected is False:
                reason = "batch manifest selected=False"
            elif manifest_completed is False:
                reason = "batch manifest completed=False"
            elif returncode not in (None, 0):
                reason = f"batch manifest returncode={returncode}"
            else:
                reason = "missing completion summary"
        elif count_path is None:
            raise AggregationError(
                f"Sample {slide_id} is marked complete but has no cell_types/class_counts.csv"
            )
        elif summary_path is None:
            raise AggregationError(
                f"Sample {slide_id} is marked complete but has no summary/summary.json"
            )

        summary: dict[str, Any] | None = None
        total_cells: int | None = None
        n_cell_types: int | None = None
        sampling = {
            "percent_slide": None,
            "random_seed": None,
            "n_tiles_total": None,
            "n_tiles_sampled": None,
        }
        if eligible and count_path is not None and summary_path is not None:
            summary = read_json(summary_path)
            summary_slide_id = str(summary.get("slide_id", slide_id))
            if summary_slide_id != slide_id:
                raise AggregationError(
                    f"Summary slide_id mismatch for folder {slide_id}: {summary_slide_id!r}"
                )
            table = read_count_table(count_path, slide_id)
            total_cells = int(table["count"].sum())
            n_cell_types = int(len(table))
            summary_total = optional_int(
                summary.get("n_cells"), field=f"{slide_id}.summary.n_cells"
            )
            if summary_total is None:
                raise AggregationError(f"Summary for {slide_id} is missing n_cells")
            if total_cells != summary_total:
                raise AggregationError(
                    f"Cell total mismatch for {slide_id}: class_counts.csv={total_cells}, "
                    f"summary.json={summary_total}"
                )
            declared_zero = bool(summary.get("zero_detections", False))
            observed_zero = total_cells == 0
            if declared_zero != observed_zero:
                raise AggregationError(
                    f"Zero-detection mismatch for {slide_id}: total_cells={total_cells}, "
                    f"zero_detections={declared_zero}"
                )
            sampling = summary_fields(summary)
            included_tables[slide_id] = table
            included_summaries[slide_id] = summary

        audit_rows.append(
            {
                "slide_id": slide_id,
                "sample_id": "",
                "included": bool(eligible),
                "status": status,
                "reason": reason,
                "manifest_completed": manifest_completed,
                "manifest_selected": manifest_selected,
                "returncode": returncode,
                "total_cells": total_cells,
                "n_detected_cell_types": n_cell_types,
                **sampling,
                "class_counts_csv": portable_path(count_path, input_root),
                "summary_json": portable_path(summary_path, input_root),
                "log_file": log_file or "",
            }
        )

    sample_map = load_sample_map(args.sample_map, included_tables, all_slide_ids)
    reserved_output_ids = sorted(
        {
            sample_id
            for sample_id in sample_map.values()
            if sample_id.casefold() in {"class_id", "cell_type"}
        },
        key=natural_key,
    )
    if reserved_output_ids:
        raise AggregationError(
            "Output sample ID(s) collide with matrix index headers: "
            + ", ".join(reserved_output_ids)
        )
    for row in audit_rows:
        row["sample_id"] = sample_map.get(str(row["slide_id"]), str(row["slide_id"]))

    long_parts: list[pd.DataFrame] = []
    for slide_id, table in included_tables.items():
        part = table.copy()
        part.insert(0, "sample_id", sample_map[slide_id])
        part.insert(0, "slide_id", slide_id)
        long_parts.append(part)
    if long_parts:
        long_table = pd.concat(long_parts, ignore_index=True)
    else:
        long_table = pd.DataFrame(
            {
                "slide_id": pd.Series(dtype="object"),
                "sample_id": pd.Series(dtype="object"),
                "class_id": pd.Series(dtype="int64"),
                "class_name": pd.Series(dtype="object"),
                "count": pd.Series(dtype="int64"),
            }
        )
    validate_class_mapping(long_table)

    sampling_by_slide = {
        slide_id: summary_fields(summary)
        for slide_id, summary in included_summaries.items()
    }
    percentages = sorted(
        {
            float(fields["percent_slide"])
            for fields in sampling_by_slide.values()
            if fields["percent_slide"] is not None
        }
    )
    seeds = sorted(
        {
            int(fields["random_seed"])
            for fields in sampling_by_slide.values()
            if fields["random_seed"] is not None
        }
    )
    missing_percentages = sorted(
        slide_id
        for slide_id, fields in sampling_by_slide.items()
        if fields["percent_slide"] is None
    )
    missing_sampled_seeds = sorted(
        slide_id
        for slide_id, fields in sampling_by_slide.items()
        if fields["percent_slide"] is not None
        and float(fields["percent_slide"]) < 100.0
        and fields["random_seed"] is None
    )
    if args.expected_percent_slide is not None:
        if missing_percentages:
            raise AggregationError(
                "Expected sampling metadata, but percent_slide is missing for: "
                + ", ".join(missing_percentages)
            )
        mismatched = [
            value
            for value in percentages
            if not math.isclose(value, args.expected_percent_slide, rel_tol=0, abs_tol=1e-9)
        ]
        if mismatched:
            raise AggregationError(
                f"Expected percent_slide={args.expected_percent_slide:g}, observed {percentages}"
            )
    if missing_sampled_seeds:
        raise AggregationError(
            "Sampled completed slides are missing random_seed metadata: "
            + ", ".join(missing_sampled_seeds)
        )
    if missing_percentages and any(value < 100.0 for value in percentages):
        raise AggregationError(
            "Cannot mix legacy summaries lacking percent_slide with sampled runs; missing for: "
            + ", ".join(missing_percentages)
        )
    if not args.allow_mixed_sampling and (len(percentages) > 1 or len(seeds) > 1):
        raise AggregationError(
            "Completed samples use mixed tile sampling settings: "
            f"percent_slide={percentages}, random_seed={seeds}. "
            "Use --allow-mixed-sampling only if this comparison is intentional."
        )

    matrix = matrix_from_long(
        long_table, (sample_map[slide_id] for slide_id in included_tables)
    )
    column_totals = matrix.sum(axis=0)
    fractions = matrix.divide(column_totals.where(column_totals != 0), axis="columns").fillna(0.0)
    fractions.index = fractions.index.set_names(["class_id", "cell_type"])

    output_dir.mkdir(parents=True, exist_ok=True)
    counts_csv = output_dir / "celltype_counts_by_sample.csv"
    fractions_csv = output_dir / "celltype_fractions_by_sample.csv"
    long_csv = output_dir / "celltype_counts_long.csv"
    audit_csv = output_dir / "sample_aggregation_audit.csv"
    summary_json = output_dir / "aggregation_summary.json"

    matrix.to_csv(counts_csv)
    fractions.to_csv(fractions_csv, float_format="%.10g")
    long_output = long_table.rename(columns={"class_name": "cell_type"})
    long_output = long_output.loc[
        :, ["slide_id", "sample_id", "class_id", "cell_type", "count"]
    ].sort_values(
        ["sample_id", "class_id", "cell_type"], kind="stable"
    )
    long_output.to_csv(long_csv, index=False)
    audit_table = pd.DataFrame(audit_rows).sort_values("slide_id", key=lambda values: values.map(natural_key))
    audit_table.to_csv(audit_csv, index=False)

    excluded = [row for row in audit_rows if not row["included"]]
    result = {
        "schema_version": "histoplus_celltype_aggregation_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_root": str(args.input_root),
        "manifest": portable_path(manifest_path, input_root) if manifest_path is not None else None,
        "sample_map": portable_path(args.sample_map.expanduser().resolve(), input_root) if args.sample_map else None,
        "n_manifest_slides": len(manifest),
        "n_included_slides": len(included_tables),
        "n_excluded_slides": len(excluded),
        "n_output_samples": int(matrix.shape[1]),
        "n_discovered_cell_types": int(matrix.shape[0]),
        "n_detected_cells": int(matrix.to_numpy().sum()),
        "percent_slide_values": percentages,
        "random_seed_values": seeds,
        "matrix_orientation": "cell_types_as_rows_samples_as_columns",
        "counts_are": "detected cells in sampled tiles; not full-slide extrapolations",
        "excluded_slides": [
            {
                "slide_id": row["slide_id"],
                "status": row["status"],
                "reason": row["reason"],
                "returncode": row["returncode"],
            }
            for row in excluded
        ],
        "outputs": {
            "counts_matrix_csv": portable_path(counts_csv, input_root),
            "fractions_matrix_csv": portable_path(fractions_csv, input_root),
            "long_counts_csv": portable_path(long_csv, input_root),
            "sample_audit_csv": portable_path(audit_csv, input_root),
        },
    }
    result["outputs"]["summary_json"] = portable_path(summary_json, input_root)
    write_json(summary_json, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate LazySlide/HistoPLUS per-slide class counts into "
            "cell-type-by-sample CSV matrices."
        )
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        default=DEFAULT_INPUT_ROOT,
        help="LazySlide result root containing <slide_id>/cell_types/class_counts.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: <input-root>/aggregated_celltypes)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Batch manifest (default: auto-detect workflow_aggregation_manifest.csv or fast_batch_manifest.csv)",
    )
    parser.add_argument(
        "--ignore-manifest",
        action="store_true",
        help="Ignore the batch manifest and use summary.json as the completion marker",
    )
    parser.add_argument(
        "--sample-map",
        type=Path,
        default=None,
        help=(
            "Optional CSV with slide_id,sample_id columns. Multiple slides mapped to "
            "one sample are summed; every slide in the aggregation roster must be mapped."
        ),
    )
    parser.add_argument(
        "--expected-percent-slide",
        type=float,
        default=None,
        help="Fail unless all recorded sampling percentages equal this value",
    )
    parser.add_argument(
        "--allow-mixed-sampling",
        action="store_true",
        help="Allow samples with different percent_slide values or random seeds",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = aggregate(args)
    except AggregationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print("HistoPLUS aggregation complete")
    print(
        f"  included slides: {result['n_included_slides']} | "
        f"excluded slides: {result['n_excluded_slides']}"
    )
    print(
        f"  matrix: {result['n_discovered_cell_types']} cell types x "
        f"{result['n_output_samples']} samples"
    )
    print(f"  detected cells: {result['n_detected_cells']:,}")
    for label, path in result["outputs"].items():
        print(f"  {label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
