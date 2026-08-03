#!/usr/bin/env python3
"""Verify TumorQuantAI public lymphoma outputs produced with the fast preset."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def require_file(path: Path) -> None:
    if not path.is_file():
        fail(f"missing file: {path}")
    if path.stat().st_size <= 0:
        fail(f"empty file: {path}")


def parse_bool(value: str | None) -> bool:
    normalized = str(value or "").strip().casefold()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    fail(f"invalid boolean value in aggregation audit: {value!r}")
    return False


def read_csv(path: Path) -> list[dict[str, str]]:
    require_file(path)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        fail(f"CSV has no data rows: {path}")
    return rows


def matrix_samples(path: Path) -> list[str]:
    require_file(path)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            fail(f"matrix is empty: {path}")
        try:
            first_row = next(reader)
        except StopIteration:
            fail(f"matrix has no cell-type rows: {path}")
    if len(header) < 3 or len(first_row) < 3:
        fail(f"matrix has no sample columns: {path}")
    return header[2:]


def summary_percent(summary: dict[str, object]) -> float | None:
    sampling = summary.get("tile_sampling")
    if isinstance(sampling, dict) and sampling.get("percent_slide") not in (None, ""):
        return float(sampling["percent_slide"])
    for key in ("percent_slide", "sampling_percent"):
        if summary.get(key) not in (None, ""):
            return float(summary[key])
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-samples", type=int, default=21)
    parser.add_argument("--expected-percent", type=float, default=10.0)
    args = parser.parse_args()

    if args.expected_samples <= 0:
        fail("--expected-samples must be greater than zero")
    if not 0 < args.expected_percent <= 100:
        fail("--expected-percent must be in (0, 100]")

    output = args.output.expanduser().resolve()
    aggregate = output / "aggregated_celltypes"
    audit_path = aggregate / "sample_aggregation_audit.csv"
    counts_matrix = aggregate / "celltype_counts_by_sample.csv"
    fractions_matrix = aggregate / "celltype_fractions_by_sample.csv"

    for path in (
        output / "START_HERE.html",
        audit_path,
        counts_matrix,
        fractions_matrix,
    ):
        require_file(path)

    rows = read_csv(audit_path)
    if len(rows) != args.expected_samples:
        fail(
            f"expected {args.expected_samples} audit rows, found {len(rows)}"
        )

    included: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for row in rows:
        slide_id = str(row.get("slide_id", "")).strip()
        sample_id = str(row.get("sample_id", "")).strip() or slide_id
        if not slide_id:
            fail("aggregation audit contains an empty slide_id")
        if sample_id in seen_ids:
            fail(f"duplicate sample_id in aggregation audit: {sample_id}")
        seen_ids.add(sample_id)
        if not parse_bool(row.get("included")):
            fail(
                f"sample is not included: {sample_id} "
                f"status={row.get('status')!r} reason={row.get('reason')!r}"
            )
        if str(row.get("status", "")).strip().casefold() != "included":
            fail(f"unexpected audit status for {sample_id}: {row.get('status')!r}")
        try:
            percent = float(row.get("percent_slide", ""))
        except ValueError as exc:
            raise SystemExit(
                f"ERROR: audit percent_slide is not numeric for {sample_id}"
            ) from exc
        if not math.isclose(
            percent, args.expected_percent, rel_tol=0.0, abs_tol=1e-9
        ):
            fail(
                f"expected {args.expected_percent:g}% for {sample_id}, "
                f"found {percent:g}%"
            )
        included.append(row)

    for row in included:
        slide_id = str(row["slide_id"]).strip()
        sample_dir = output / slide_id
        required = (
            sample_dir / "overlays/celltypes_overview_and_zoom.png",
            sample_dir / "summary/summary.json",
            sample_dir / "cell_types/class_counts.csv",
            sample_dir / "cell_types/cell_type_coordinates.csv",
        )
        for path in required:
            require_file(path)

        summary_path = sample_dir / "summary/summary.json"
        with summary_path.open(encoding="utf-8") as handle:
            summary = json.load(handle)
        if not isinstance(summary, dict):
            fail(f"summary is not a JSON object: {summary_path}")
        declared = str(summary.get("slide_id", slide_id))
        if declared != slide_id:
            fail(
                f"summary slide_id mismatch for {slide_id}: {declared!r}"
            )
        percent = summary_percent(summary)
        if percent is not None and not math.isclose(
            percent, args.expected_percent, rel_tol=0.0, abs_tol=1e-9
        ):
            fail(
                f"summary sampling mismatch for {slide_id}: {percent:g}%"
            )

    expected_matrix_samples = {
        str(row.get("sample_id", "")).strip() or str(row["slide_id"]).strip()
        for row in included
    }
    for matrix in (counts_matrix, fractions_matrix):
        observed = set(matrix_samples(matrix))
        if observed != expected_matrix_samples:
            missing = sorted(expected_matrix_samples - observed)
            unexpected = sorted(observed - expected_matrix_samples)
            fail(
                f"matrix sample columns do not match the audit: {matrix}; "
                f"missing={missing}, unexpected={unexpected}"
            )

    print(
        f"SUCCESS: {args.expected_samples}-slide TumorQuantAI "
        f"{args.expected_percent:g}% tutorial outputs are complete."
    )
    print(f"Included samples: {len(included)}")
    print(f"Open first: {output / 'START_HERE.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
