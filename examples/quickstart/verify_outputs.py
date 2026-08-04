#!/usr/bin/env python3
"""Verify preparation or complete outputs from TumorQuantAI QuickStart Example 1."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

EXPECTED_SAMPLE = "TumorQuantAI_LymphomaWSI_022"
EXPECTED_PERCENT = 1.0


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
    if len(header) < 3:
        fail(f"matrix has no sample columns: {path}")
    return header[2:]


def verify_preparation(root: Path) -> None:
    converted = root / "converted"
    inspection = root / "inspection"
    required = (
        root / "START_HERE.html",
        root / "download/tumorquantai_lymphoma_mds_manifest.csv",
        root / f"download/raw/{EXPECTED_SAMPLE}/1.mds",
        converted / f"{EXPECTED_SAMPLE}/1_L0_rgb.tif",
        converted / f"{EXPECTED_SAMPLE}/1_L2_rgb.tif",
        converted / "samples.csv",
        inspection / "INSPECTION.html",
        inspection / "inspection_manifest.csv",
    )
    for path in required:
        require_file(path)

    rows = read_csv(inspection / "inspection_manifest.csv")
    matching = [
        row
        for row in rows
        if EXPECTED_SAMPLE
        in {
            str(row.get("sample_id", "")).strip(),
            str(row.get("slide_id", "")).strip(),
        }
    ]
    if len(matching) != 1:
        fail(
            f"expected one inspection row for {EXPECTED_SAMPLE}, "
            f"found {len(matching)}"
        )


def verify_inference(root: Path) -> None:
    result = root / "smoke-results"
    sample = result / EXPECTED_SAMPLE
    aggregate = result / "aggregated_celltypes"

    required = (
        result / "START_HERE.html",
        sample / "overlays/celltypes_overview_and_zoom.png",
        sample / "summary/summary.json",
        sample / "cell_types/class_counts.csv",
        sample / "cell_types/cell_type_coordinates.csv",
        aggregate / "sample_aggregation_audit.csv",
        aggregate / "celltype_counts_by_sample.csv",
        aggregate / "celltype_fractions_by_sample.csv",
    )
    for path in required:
        require_file(path)

    with (sample / "summary/summary.json").open(encoding="utf-8") as handle:
        summary = json.load(handle)
    if not isinstance(summary, dict):
        fail("summary.json is not a JSON object")
    if str(summary.get("slide_id", EXPECTED_SAMPLE)) != EXPECTED_SAMPLE:
        fail("summary.json slide_id does not match the fixed QuickStart sample")

    audit_path = aggregate / "sample_aggregation_audit.csv"
    audit_rows = read_csv(audit_path)
    matching = [
        row
        for row in audit_rows
        if row.get("slide_id") == EXPECTED_SAMPLE
        or row.get("sample_id") == EXPECTED_SAMPLE
    ]
    if len(matching) != 1:
        fail(f"expected one audit row for {EXPECTED_SAMPLE}, found {len(matching)}")
    included_rows = [row for row in audit_rows if parse_bool(row.get("included"))]
    if len(included_rows) != 1:
        fail(f"expected exactly one included audit row, found {len(included_rows)}")
    row = matching[0]
    if not parse_bool(row.get("included")):
        fail("the QuickStart sample is not included in the aggregation audit")
    if str(row.get("status", "")).strip().casefold() != "included":
        fail(f"unexpected QuickStart audit status: {row.get('status')!r}")
    try:
        percent = float(row.get("percent_slide", ""))
    except ValueError as exc:
        raise SystemExit("ERROR: audit percent_slide is not numeric") from exc
    if not math.isclose(percent, EXPECTED_PERCENT, rel_tol=0.0, abs_tol=1e-9):
        fail(f"expected percent_slide=1, found {percent:g}")

    for matrix in (
        aggregate / "celltype_counts_by_sample.csv",
        aggregate / "celltype_fractions_by_sample.csv",
    ):
        samples = matrix_samples(matrix)
        if EXPECTED_SAMPLE not in samples:
            fail(f"matrix does not contain {EXPECTED_SAMPLE}: {matrix}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tutorial-root",
        required=True,
        type=Path,
        help="root passed to ./tumorquantai quickstart --output",
    )
    parser.add_argument(
        "--preparation-only",
        action="store_true",
        help="verify download, conversion, and inspection without HistoPLUS outputs",
    )
    args = parser.parse_args()

    root = args.tutorial_root.expanduser().resolve()
    verify_preparation(root)
    if args.preparation_only:
        print("SUCCESS: one-slide TumorQuantAI QuickStart preparation is complete.")
        print(f"Sample: {EXPECTED_SAMPLE}")
        print(f"Open first: {root / 'START_HERE.html'}")
        return 0

    verify_inference(root)
    print("SUCCESS: one-slide TumorQuantAI QuickStart outputs are complete.")
    print(f"Sample: {EXPECTED_SAMPLE}")
    print("Sampling: 1% of detected tissue tiles")
    print(f"Open first: {root / 'START_HERE.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
