#!/usr/bin/env python3
"""Convert a discovery TSV plus staged results into an aggregation audit roster."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with args.discovery.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows or "sample_id" not in rows[0]:
        parser.error("Discovery manifest is empty or lacks sample_id")

    output_rows = []
    for row in rows:
        slide_id = row["sample_id"]
        sample_dir = args.results_root / slide_id
        counts = sample_dir / "cell_types" / "class_counts.csv"
        summary = sample_dir / "summary" / "summary.json"
        completed = counts.is_file() and summary.is_file()
        output_rows.append(
            {
                "slide_id": slide_id,
                "raw_dir": "",
                "output_dir": slide_id,
                "expected_l0": row.get("slide_path", ""),
                "expected_l0_exists": Path(row.get("slide_path", "")).is_file(),
                "expected_l2_exists": "",
                "completed": completed,
                "selected": True,
                "returncode": 0 if completed else "",
                "elapsed_sec": "",
                "log_file": "",
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_rows[0].keys())
        writer.writeheader()
        writer.writerows(output_rows)
    completed_count = sum(str(row["completed"]).lower() == "true" for row in output_rows)
    print(f"Workflow manifest: completed={completed_count} incomplete={len(output_rows) - completed_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
