#!/usr/bin/env python3
"""Tiny orchestration fixture; it does not inspect or process slide pixels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--input-slide", required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--slide-id", required=True)
for option in (
    "--mpp", "--tile-px", "--overlap", "--background-fraction", "--percent-slide",
    "--patch-random-seed", "--max-sampled-patches", "--collage", "--device",
    "--num-workers", "--cells-model", "--cells-batch-size", "--celltypes-batch-size",
    "--histoplus-magnification", "--histoplus-repo-id", "--histoplus-revision",
    "--histoplus-cache-dir", "--zoom-size", "--overlay-alpha",
    "--overlay-style", "--overlay-outline-width", "--overlay-halo-width", "--overlay-draw-order",
    "--cell-marker-radius", "--figure-dpi", "--qc-patch-count", "--qc-patch-size",
    "--pyramidal-tile", "--pyramidal-compression", "--pyramidal-jpeg-q", "--log-level",
):
    parser.add_argument(option)
for option in (
    "--convert-to-pyramidal", "--run-cells-stage", "--amp", "--plain-csv",
    "--export-qupath", "--save-geojson-like-json",
):
    parser.add_argument(option, action="store_true")
args = parser.parse_args()

if "case_fail" in args.slide_id or "case_fail" in args.input_slide:
    raise SystemExit("intentional fixture failure")

(args.output / "cell_types").mkdir(parents=True)
(args.output / "summary").mkdir(parents=True)
(args.output / "cell_types" / "class_counts.csv").write_text(
    "class_id,class_name,count\n1,Cancer cell,7\n2,Lymphocytes,3\n",
    encoding="utf-8",
)
(args.output / "summary" / "summary.json").write_text(
    json.dumps(
        {
            "slide_id": args.slide_id,
            "n_cells": 10,
            "tile_sampling": {
                "percent_slide": float(args.percent_slide),
                "random_seed": 20260709,
                "n_tiles_total": 10,
                "n_tiles_sampled": 1,
            },
        }
    ),
    encoding="utf-8",
)
