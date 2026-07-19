#!/usr/bin/env python3
"""
LazySlide + HistoPLUS whole-slide cell-type pipeline for exported TIFF slides.

This script is designed for the *exported* TIFFs produced by the ASlide pipeline
(e.g. `*_L0_rgb.tif`). It uses LazySlide for WSI orchestration and HistoPLUS for
cell detection / segmentation / classification.

Per slide, the script produces:
  1) A high-resolution zoom overlay with cell types in distinctive colors.
  2) A tutorial-style overview + zoom figure saved as PNG and PDF.
  3) A CSV (optionally gzip-compressed) containing centroids, bounding boxes,
     and cell-type labels for every detected cell.
  4) A `.npy` file containing cell ids, class ids / names, centroids, bounding
     boxes, and polygon coordinates.

Optional extras:
  * QuPath-compatible annotation export (`--export-qupath`).
  * QC patch overlays (`--qc-patch-count N`).
  * Optional InstanSeg cell-segmentation stage before HistoPLUS (`--run-cells-stage`).
  * Optional on-the-fly conversion of non-pyramidal L0 TIFFs into tiled pyramidal BigTIFFs (`--convert-to-pyramidal`).

Typical usage
-------------
Single exported slide after requesting access to the gated HistoPLUS model and
authenticating on the server with `hf auth login`, a Python login snippet, or --hf-token/HF_TOKEN:
    python lazyslide_histoplus_wsi_celltype.py \
      --input-slide /path/to/1_L0_rgb.tif \
      --output-root /path/to/histoplus_results \
      --mpp 0.5 \
      --device cpu

Single exported slide with a manually downloaded HistoPLUS weight file:
    python lazyslide_histoplus_wsi_celltype.py \
      --input-slide /path/to/1_L0_rgb.tif \
      --output-root /path/to/histoplus_results \
      --mpp 0.5 \
      --device cpu \
      --histoplus-weight-file /path/to/histoplus_cellvit_segmentor_20x.pt

All exported H&E slides under an export root:
    python lazyslide_histoplus_wsi_celltype.py \
      --export-root /path/to/exported_slides \
      --output-root /path/to/histoplus_results \
      --include '*HE*' \
      --mpp 0.5 \
      --device cpu \
      --qc-patch-count 12 \
      --export-qupath
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import gzip
import hashlib
import json
import logging
import math
import os
import re
import shutil
import shlex
import site
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional, Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import ConnectionPatch, Patch, Rectangle
import numpy as np
import pandas as pd
import tifffile
from PIL import Image, ImageDraw

try:
    from tqdm.auto import tqdm
except Exception:  # pragma: no cover - tqdm is optional at runtime.
    class _NoOpTqdm:
        def __init__(self, iterable=None, **_kwargs):
            self.iterable = iterable

        def __iter__(self):
            return iter(self.iterable if self.iterable is not None else [])

        def update(self, _n: int = 1) -> None:
            return None

        def close(self) -> None:
            return None

    def tqdm(iterable=None, **kwargs):
        return _NoOpTqdm(iterable, **kwargs)


# ----------------------------- data models -----------------------------

@dataclass(frozen=True)
class RawSlideSource:
    source_path: Path
    relative_parent: Path
    base_stem: str
    slide_id: str


@dataclass(frozen=True)
class SlideJob:
    slide_id: str
    relative_parent: Path
    base_stem: str
    l0_path: Path


@dataclass(frozen=True)
class PatchRecord:
    patch_id: int
    mosaic_x0: int
    mosaic_y0: int
    source_x0: int
    source_y0: int
    width: int
    height: int
    tissue_fraction: float = 0.0


# ----------------------------- constants -----------------------------

# LazySlide documents the HistoPLUS output classes through its model API.
# We use the canonical names and a stable color palette for figure generation.
HISTOPLUS_CLASS_INFO: "OrderedDict[int, tuple[str, str]]" = OrderedDict(
    [
        (0, ("Background", "#000000")),
        (1, ("Cancer cell", "#005AB5")),
        (2, ("Lymphocytes", "#228B22")),
        (3, ("Fibroblasts", "#F97306")),
        (4, ("Plasmocytes", "#7B2CBF")),
        (5, ("Eosinophils", "#FFD23F")),
        (6, ("Neutrophils", "#00A6D6")),
        (7, ("Macrophages", "#D7263D")),
        (8, ("Muscle Cell", "#8B5E34")),
        (9, ("Endothelial Cell", "#B5BD00")),
        (10, ("Red blood cell", "#6E1E0E")),
        (11, ("Epithelial", "#3A0CA3")),
        (12, ("Apoptotic Body", "#595959")),
        (13, ("Mitotic Figures", "#F72585")),
        (14, ("Minor Stromal Cell", "#00C49A")),
    ]
)

DEFAULT_CLASS_COLORS: dict[str, str] = {
    name: color for _cid, (name, color) in HISTOPLUS_CLASS_INFO.items()
}
NAME_TO_ID: dict[str, int] = {
    re.sub(r"[^a-z0-9]", "", name.lower()): cid
    for cid, (name, _color) in HISTOPLUS_CLASS_INFO.items()
}

NAME_ALIASES: dict[str, int] = {
    "cancercell": 1,
    "cancercells": 1,
    "lymphocyte": 2,
    "lymphocytes": 2,
    "fibroblast": 3,
    "fibroblasts": 3,
    "plasmocyte": 4,
    "plasmocytes": 4,
    "eosinophil": 5,
    "eosinophils": 5,
    "neutrophil": 6,
    "neutrophils": 6,
    "macrophage": 7,
    "macrophages": 7,
    "musclecell": 8,
    "musclecells": 8,
    "endothelialcell": 9,
    "endothelialcells": 9,
    "redbloodcell": 10,
    "redbloodcells": 10,
    "erythrocyte": 10,
    "erythrocytes": 10,
    "epithelial": 11,
    "epithelialcell": 11,
    "epithelialcells": 11,
    "apoptoticbody": 12,
    "apoptoticbodies": 12,
    "mitoticfigure": 13,
    "mitoticfigures": 13,
    "minorstromalcell": 14,
    "minorstromalcells": 14,
    "background": 0,
}

HISTOPLUS_DEFAULT_TILE_PX = 840
HISTOPLUS_TILE_DIVISOR = 14
DEFAULT_HISTOPLUS_REPO_ID = "Owkin-Bioptimus/histoplus"
DEFAULT_HISTOPLUS_REVISION = "cde2eee81af9e39b03802fc33d4f284733b5ee5e"
OVERLAY_PALETTE_VERSION = "high_contrast_outline_centroid_halo_v3_2026_05_10"

HELP_EPILOG = r"""
Portable examples
-----------------
Inspect one exported L0 whole-slide image without running inference:

  python lazyslide_histoplus_wsi_celltype.py \
    --input-slide /data/case-001/slide_L0_rgb.tif \
    --output /results/case-001 \
    --dry-run

Run HistoPLUS on one exported slide:

  python lazyslide_histoplus_wsi_celltype.py \
    --input-slide /data/case-001/slide_L0_rgb.tif \
    --output /results/case-001 \
    --device cuda \
    --convert-to-pyramidal \
    --plain-csv

Run an exported-slide directory directly (the Nextflow workflow is preferred
for multi-slide runs because it isolates failures and cache state per sample):

  python lazyslide_histoplus_wsi_celltype.py \
    --export-root /data/exported_slides \
    --output-root /results \
    --include '*HE*' \
    --resume

HistoPLUS weights are gated. Set HF_TOKEN, pass --hf-token-file, or provide a
local --histoplus-weight-file. Avoid putting token values directly in shell
history. Raw Motic/ASlide export requires the proprietary Aslide module and is
therefore an optional direct-script mode, not part of the portable container
quickstart.
"""
class SmartHelpFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    pass



# ----------------------------- CLI -----------------------------



def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        formatter_class=SmartHelpFormatter,
        description=(
            "Run LazySlide + HistoPLUS on exported TIFF slides and export whole-slide cell-type overlays / coordinates. "
            "In --target-folder mode, the script can also create missing ASlide TIFF exports automatically."
        ),
        epilog=HELP_EPILOG,
    )

    ap.add_argument("--version", action="version", version=f"%(prog)s {OVERLAY_PALETTE_VERSION}")

    input_mode = ap.add_mutually_exclusive_group(required=False)
    input_mode.add_argument(
        "--target-folder",
        type=Path,
        help=(
            "Raw Motic/ASlide case folder. When this mode is used, the script derives "
            "<target>_EXPORT_L0_L3 and, when needed, <target>_EXPORT_L0_L3_PYRAMIDAL automatically."
        ),
    )
    input_mode.add_argument(
        "--slide-folder",
        "--case-folder",
        "--single-folder",
        dest="slide_folder",
        type=Path,
        help=(
            "Single raw WSI leaf folder containing files such as 1.mds, 1.ini, info.xml, label.jpg and macro.jpg. "
            "Example: /data/study/case-001. The export root is derived from the parent project folder."
        ),
    )
    input_mode.add_argument(
        "--export-root",
        type=Path,
        help="Root containing exported TIFF slides such as *_L0_rgb.tif.",
    )
    input_mode.add_argument(
        "--input-slide",
        type=Path,
        help="Single exported L0 TIFF slide to process.",
    )

    ap.add_argument("--internal-export-only", action="store_true", help="Export raw ASlide/Motic folders to TIFFs and exit. Requires --raw-root and --export-root; does not run segmentation.")
    ap.add_argument("--raw-root", type=Path, default=None, help="Raw WSI root used with --internal-export-only. Example: /data/raw_slides.")
    ap.add_argument("--raw-source-limit-dir", type=Path, default=None, help=argparse.SUPPRESS)

    ap.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Output root for batch mode, or for single-slide mode when you want outputs under <output-root>/<slide_id>.",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Exact output directory for single-slide mode. Use this with --input-slide when you do not want the extra <slide_id> layer.",
    )
    ap.add_argument("--slide-id", type=str, default=None, help="Explicit sample/slide ID for --input-slide; used in summaries and cohort aggregation.")
    ap.add_argument("--prefetch-histoplus", action="store_true", help="Resolve / download the gated HistoPLUS weight file and exit without processing any slides.")
    ap.add_argument("--include", type=str, default="*", help="fnmatch include filter over slide IDs.")
    ap.add_argument("--exclude", type=str, default="", help="fnmatch exclude filter over slide IDs.")
    ap.add_argument("--resume", "--continue", dest="resume", action="store_true", help="Skip slides with an existing completed summary.json. --continue is an alias for this behavior.")
    ap.add_argument("--overwrite", action="store_true", help="Delete existing per-slide outputs before rerun.")
    ap.add_argument("--dry-run", action="store_true", help="Plan discovery/export/processing and write the WSI discovery report without running ASlide, pyramidal conversion, LazySlide, or HistoPLUS.")
    ap.add_argument("--discovery-report-name", type=str, default="wsi_discovery_report", help="Base filename for discovery report files written under the output base.")
    ap.add_argument("--directory-tree-depth", type=int, default=4, help="Directory depth included in the discovery report text file.")
    ap.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")

    # Automatic ASlide export settings for --target-folder mode.
    ap.add_argument("--auto-export-missing", dest="auto_export_missing", action="store_true", default=True, help=argparse.SUPPRESS)
    ap.add_argument(
        "--no-auto-export",
        dest="auto_export_missing",
        action="store_false",
        help="With --target-folder, do not automatically create missing TIFF exports before LazySlide processing.",
    )
    ap.add_argument("--export-env-name", type=str, default="pathology_ai", help="Conda environment used for automatic ASlide export when Aslide is not importable in the current Python environment.")
    ap.add_argument("--export-python", type=Path, default=None, help="Optional Python executable used for the automatic ASlide export helper. Overrides --export-env-name.")
    ap.add_argument("--overwrite-export", action="store_true", help="Rebuild exported TIFFs instead of reusing existing exports during automatic ASlide export.")
    ap.add_argument("--export-levels", nargs="+", type=int, default=[0, 2], help="ASlide export levels used when automatically creating TIFF exports from --target-folder.")
    ap.add_argument("--export-tile", type=int, default=1024, help="Tile edge used for automatic ASlide BigTIFF export.")
    ap.add_argument("--export-compression", type=str, default="deflate", help="Compression used for automatic ASlide export: none, deflate, lzw, jpeg, zstd, etc.")
    ap.add_argument("--export-compression-level", type=int, default=9, help="Compression level used when --export-compression deflate is selected.")
    ap.add_argument("--raw-extensions", nargs="+", default=[".mds", ".mdsx"], help="Raw slide extensions discovered under --target-folder / --raw-root during automatic export.")
    ap.add_argument("--quiet-export", action="store_true", help="Reduce per-slide logging from the automatic ASlide export helper.")

    # Slide / tiling settings.
    ap.add_argument("--mpp", type=float, default=0.5, help="Requested microns-per-pixel for model tiles.")
    ap.add_argument(
        "--slide-mpp",
        type=float,
        default=None,
        help=(
            "Physical microns-per-pixel of the source L0 image. Overrides embedded "
            "metadata; required when the TIFF has no reliable MPP."
        ),
    )
    ap.add_argument("--tile-px", type=int, default=HISTOPLUS_DEFAULT_TILE_PX, help="Tile size passed to zs.pp.tile_tissues. HistoPLUS requires a value divisible by 14; invalid values are auto-corrected to the nearest valid size.")
    ap.add_argument("--overlap", type=float, default=0.2, help="Tile overlap ratio passed to zs.pp.tile_tissues.")
    ap.add_argument("--background-fraction", type=float, default=0.95, help="Max background fraction for kept tiles.")
    ap.add_argument(
        "--percent-slide",
        "--percent_slide",
        dest="percent_slide",
        type=float,
        default=100.0,
        help=(
            "Randomly process this percent of tissue tiles after tiling. Values below 100 enable fast "
            "approximate segmentation and require an adjacent *_L2_* export for sampled-patch auditing."
        ),
    )
    ap.add_argument(
        "--patch-random-seed",
        type=int,
        default=20260709,
        help="Random seed used when --percent-slide is below 100.",
    )
    ap.add_argument(
        "--max-sampled-patches",
        type=int,
        default=0,
        help="Maximum number of per-patch L0 images exported for the sampled patch report. Set 0 for no cap.",
    )
    ap.add_argument(
        "--collage",
        type=str,
        default=None,
        help="Square sampled patch collage grid, e.g. 3x3, 4x4, 5x5, or 6x6. Overrides --max-sampled-patches.",
    )
    ap.add_argument("--ops-level", type=int, default=0, help="ops_level for tile retrieval.")
    ap.add_argument("--tissue-level", default="auto", help="Level argument for zs.pp.find_tissues.")
    ap.add_argument("--thumbnail-size", type=int, default=2400, help="Maximum overview thumbnail dimension attached by open_wsi.")
    ap.add_argument("--store-root", type=Path, default=None, help="Optional root for LazySlide/WSIData zarr stores. Defaults to per-slide working dirs.")
    ap.add_argument("--keep-store", action="store_true", help="Keep the intermediate WSIData zarr store after processing.")
    ap.add_argument("--reuse-store", action="store_true", help="Reuse an existing WSIData zarr store. By default, previous stores are removed before each slide to avoid stale failed starts.")
    ap.add_argument("--convert-to-pyramidal", action="store_true", help="Convert each input L0 TIFF into a tiled pyramidal BigTIFF first, then run LazySlide on the converted slide. Cached conversions require an exact source/settings provenance sidecar.")
    ap.add_argument("--pyramidal-root", type=Path, default=None, help="Optional cache root for converted pyramidal BigTIFFs. Defaults to <slide_output>/pyramidal_input, or <target>_EXPORT_L0_L3_PYRAMIDAL in --target-folder mode.")
    ap.add_argument("--pyramidal-tile", type=int, default=512, help="Tile edge used when writing pyramidal BigTIFFs.")
    ap.add_argument("--pyramidal-compression", type=str, default="lzw", help="Compression for pyramidal BigTIFF conversion: none, lzw, deflate, zstd, or jpeg.")
    ap.add_argument("--pyramidal-jpeg-q", type=int, default=90, help="JPEG quality for pyramidal conversion when --pyramidal-compression jpeg is used.")

    # Model / runtime settings.
    ap.add_argument("--device", type=str, default="auto", help="cpu, cuda, gpu, cuda:0, or auto. gpu is normalized to cuda.")
    ap.add_argument("--num-workers", type=int, default=0, help="DataLoader workers for LazySlide model runners.")
    ap.add_argument("--amp", action="store_true", help="Use automatic mixed precision when supported.")
    ap.add_argument("--run-cells-stage", action="store_true", help="Run zs.seg.cells before HistoPLUS cell typing.")
    ap.add_argument("--cells-model", type=str, default="instanseg", help="Model passed to zs.seg.cells when --run-cells-stage is enabled.")
    ap.add_argument("--cells-batch-size", type=int, default=4)
    ap.add_argument("--celltypes-batch-size", type=int, default=2, help="HistoPLUS inference batch size. Keep low for server safety.")
    ap.add_argument("--histoplus-magnification", type=str, default="20x", help="Magnification passed to the LazySlide HistoPLUS model wrapper.")
    ap.add_argument(
        "--histoplus-weight-file",
        "--histoplus-model-path",
        dest="histoplus_model_path",
        type=Path,
        default=None,
        help=(
            "Optional local HistoPLUS weight file. The current LazySlide HistoPLUS implementation downloads "
            "histoplus_cellvit_segmentor_<20x|40x>.pt from the gated Hugging Face repo, so a local .pt file is "
            "the most reliable manual override."
        ),
    )
    ap.add_argument(
        "--histoplus-cache-dir",
        type=Path,
        default=Path("~/.cache/histoplus"),
        help=(
            "Local directory checked for provenance-validated HistoPLUS weights before download. "
            "Use --histoplus-weight-file for an unprovenanced manual file."
        ),
    )
    ap.add_argument(
        "--histoplus-repo-id",
        type=str,
        default=DEFAULT_HISTOPLUS_REPO_ID,
        help="Gated Hugging Face repo used for HistoPLUS weights.",
    )
    ap.add_argument(
        "--histoplus-revision",
        type=str,
        default=DEFAULT_HISTOPLUS_REVISION,
        help=(
            "Immutable 40-character Hugging Face commit revision used for HistoPLUS weights. "
            "Override only with another verified commit SHA."
        ),
    )
    ap.add_argument(
        "--histoplus-force-download",
        action="store_true",
        help="Force re-download of the HistoPLUS weight file instead of reusing the Hugging Face cache.",
    )
    ap.add_argument(
        "--copy-histoplus-weight-to",
        type=Path,
        default=None,
        help="Optional directory where the resolved HistoPLUS .pt file is copied after cache resolution.",
    )
    ap.add_argument("--hf-token", type=str, default=None, help="Optional Hugging Face personal access token for gated HistoPLUS weights.")
    ap.add_argument(
        "--hf-token-file",
        type=Path,
        default=None,
        help="Optional text file containing a Hugging Face personal access token.",
    )
    ap.add_argument("--hf-token-env", type=str, default="HF_TOKEN", help="Env var name checked when --hf-token and --hf-token-file are omitted.")
    ap.add_argument(
        "--hf-login",
        action="store_true",
        help="Persist the provided Hugging Face token with huggingface_hub.login() before downloading gated weights.",
    )

    # Figure / overlay settings.
    ap.add_argument("--zoom-box", nargs=4, type=int, metavar=("X0", "Y0", "X1", "Y1"), default=None,
                    help="Manual level-0 zoom box for the high-resolution overlay figure.")
    ap.add_argument("--zoom-size", type=int, default=2000, help="Auto-selected zoom window size in level-0 pixels when --zoom-box is omitted.")
    ap.add_argument("--overlay-alpha", type=float, default=0.35, help="Alpha for filled cell-type polygons when a filled overlay style is used.")
    ap.add_argument(
        "--overlay-style",
        choices=["filled", "outline", "centroid", "outline_centroid", "filled_outline", "filled-outline"],
        default="outline_centroid",
        help="How to draw cell-type annotations. outline_centroid minimizes visual overlap on dense ROIs.",
    )
    ap.add_argument("--overlay-outline-width", type=int, default=2, help="Color outline width in pixels for outline-based overlays.")
    ap.add_argument("--overlay-halo-width", type=int, default=4, help="Black halo width around outlines and centroid markers to separate adjacent cell colors.")
    ap.add_argument(
        "--overlay-draw-order",
        choices=["input", "small-last", "large-last"],
        default="small-last",
        help="Polygon drawing order. small-last draws larger polygons first so smaller cells remain visible.",
    )
    ap.add_argument("--cell-marker-radius", type=int, default=3, help="Centroid marker radius in pixels for centroid/outline_centroid overlays. Use 0 to disable markers.")
    ap.add_argument("--figure-dpi", type=int, default=300)
    ap.add_argument("--zoom-max-polygons", type=int, default=0,
                    help="Optional cap on the number of polygons drawn in the zoom overlay. 0 means no cap.")
    ap.add_argument("--legend-background", action="store_true", help="Include background in legend if present.")

    # Output controls.
    ap.add_argument("--plain-csv", action="store_true", help="Write plain .csv instead of .csv.gz for coordinates export.")
    ap.add_argument("--export-qupath", action="store_true", help="Also export QuPath-compatible annotations plus a SHA-256 integrity sidecar.")
    ap.add_argument("--save-geojson-like-json", action="store_true",
                    help="Also stream a JSON dump of per-cell polygon coordinates/classes plus a SHA-256 integrity sidecar.")

    # Optional QC patches.
    ap.add_argument("--qc-patch-count", type=int, default=0, help="Export this many dense QC patch overlays per slide.")
    ap.add_argument("--qc-patch-size", type=int, default=1024, help="Patch size in level-0 pixels for QC overlays.")
    ap.add_argument("--qc-min-distance-factor", type=float, default=0.85, help="Greedy patch-center minimum distance as a fraction of patch size.")

    args = ap.parse_args()

    if args.internal_export_only:
        if args.raw_root is None or args.export_root is None:
            ap.error("--internal-export-only requires --raw-root and --export-root.")
        if args.output is not None or args.input_slide is not None or args.output_root is not None or args.target_folder is not None or getattr(args, "slide_folder", None) is not None:
            ap.error("--internal-export-only cannot be combined with --target-folder, --slide-folder, --input-slide, --output, or --output-root.")
    else:
        if not args.prefetch_histoplus and args.target_folder is None and args.slide_folder is None and args.export_root is None and args.input_slide is None:
            ap.error("Provide --target-folder, --slide-folder, --export-root, or --input-slide, or use --prefetch-histoplus for download-only mode.")

    if str(args.histoplus_magnification).lower() not in {"20x", "40x"}:
        ap.error("--histoplus-magnification must be 20x or 40x")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", str(args.histoplus_revision).strip()):
        ap.error("--histoplus-revision must be an immutable 40-character hexadecimal commit SHA")
    args.histoplus_revision = str(args.histoplus_revision).strip().lower()
    if not math.isfinite(float(args.mpp)) or float(args.mpp) <= 0:
        ap.error("--mpp must be a finite value > 0")
    if args.slide_mpp is not None and (
        not math.isfinite(float(args.slide_mpp)) or float(args.slide_mpp) <= 0
    ):
        ap.error("--slide-mpp must be a finite value > 0")
    if args.tile_px <= 0:
        ap.error("--tile-px must be > 0")
    if not (0.0 < float(args.percent_slide) <= 100.0):
        ap.error("--percent-slide/--percent_slide must be > 0 and <= 100")
    if int(args.max_sampled_patches) < 0:
        ap.error("--max-sampled-patches must be >= 0")
    try:
        args.collage_grid = parse_collage_grid(args.collage)
    except ValueError as exc:
        ap.error(str(exc))
    if args.pyramidal_tile <= 0:
        ap.error("--pyramidal-tile must be > 0")
    if args.export_tile <= 0:
        ap.error("--export-tile must be > 0")
    if str(args.pyramidal_compression).lower() not in {"none", "lzw", "deflate", "zstd", "jpeg"}:
        ap.error("--pyramidal-compression must be one of: none, lzw, deflate, zstd, jpeg")
    if not (1 <= int(args.pyramidal_jpeg_q) <= 100):
        ap.error("--pyramidal-jpeg-q must be in [1, 100]")
    if args.zoom_size <= 0:
        ap.error("--zoom-size must be > 0")
    if not (0.0 <= args.overlay_alpha <= 1.0):
        ap.error("--overlay-alpha must be in [0, 1]")
    if args.overlay_outline_width < 1:
        ap.error("--overlay-outline-width must be >= 1")
    if args.overlay_halo_width < 0:
        ap.error("--overlay-halo-width must be >= 0")
    if args.cell_marker_radius < 0:
        ap.error("--cell-marker-radius must be >= 0")
    if args.qc_patch_count < 0:
        ap.error("--qc-patch-count must be >= 0")
    if args.qc_patch_size <= 0:
        ap.error("--qc-patch-size must be > 0")
    if args.qc_min_distance_factor < 0:
        ap.error("--qc-min-distance-factor must be >= 0")
    if args.zoom_box is not None:
        x0, y0, x1, y1 = args.zoom_box
        if x1 <= x0 or y1 <= y0:
            ap.error("--zoom-box must satisfy X1>X0 and Y1>Y0")

    if args.output is not None and args.output_root is not None:
        ap.error("Use either --output or --output-root, not both.")
    if args.output is not None and args.input_slide is None:
        ap.error("--output is only valid with --input-slide.")
    if args.slide_id is not None and args.input_slide is None:
        ap.error("--slide-id is only valid with --input-slide.")
    if args.slide_id is not None:
        args.slide_id = slugify(args.slide_id.strip())
        if not args.slide_id:
            ap.error("--slide-id must contain at least one letter, number, dot, underscore, or hyphen.")
        if args.slide_id.casefold() in {"aggregated_celltypes", "workflow_metadata", "class_id", "cell_type", "slides.tsv", "slides.json", "workflow_aggregation_manifest.csv", "build_workflow_manifest.py", "aggregate_histoplus_celltypes.py", "workflow_bin"}:
            ap.error("--slide-id is reserved by the workflow.")

    if not args.internal_export_only:
        if (args.target_folder is not None or getattr(args, "slide_folder", None) is not None) and args.output_root is None:
            ap.error("--output-root is required with --target-folder or --slide-folder.")
        if args.slide_folder is not None and args.output_root is None:
            ap.error("--output-root is required with --slide-folder.")
        if args.export_root is not None and args.output_root is None:
            ap.error("--output-root is required with --export-root.")
        if args.input_slide is not None and args.output is None and args.output_root is None:
            ap.error("With --input-slide, provide either --output or --output-root.")

    def _folder_has_direct_raw_slide(folder: Path) -> bool:
        try:
            exts = {str(e).lower() if str(e).startswith(".") else f".{str(e).lower()}" for e in args.raw_extensions}
            return any(p.is_file() and p.suffix.lower() in exts for p in folder.iterdir())
        except Exception:
            return False

    # Resolve paths.
    args._single_folder_mode = False
    args._single_relative_parent = None

    if args.target_folder is not None:
        target_path = args.target_folder.expanduser()
        target_path = (Path.cwd() / target_path).resolve() if not target_path.is_absolute() else target_path.resolve()
        args.target_folder = target_path
        if folder_contains_raw_slide_files(target_path, args.raw_extensions):
            project_root = target_path.parent.resolve()
            args.slide_folder = target_path
            args.raw_root = project_root
            args.raw_source_limit_dir = target_path
            args._single_folder_mode = True
            args._single_relative_parent = target_path.relative_to(project_root)
            args._target_folder_name = project_root.name
            args.export_root = (project_root.parent / f"{project_root.name}_EXPORT_L0_L3").resolve()
            args.include = "*"
            if args.convert_to_pyramidal and args.pyramidal_root is None:
                args.pyramidal_root = (project_root.parent / f"{project_root.name}_EXPORT_L0_L3_PYRAMIDAL").resolve()
        else:
            args.raw_root = target_path
            args._target_folder_name = target_path.name
            args.export_root = (target_path.parent / f"{target_path.name}_EXPORT_L0_L3").resolve()
            if args.convert_to_pyramidal and args.pyramidal_root is None:
                args.pyramidal_root = (target_path.parent / f"{target_path.name}_EXPORT_L0_L3_PYRAMIDAL").resolve()

    if args.slide_folder is not None and not args._single_folder_mode:
        slide_path = args.slide_folder.expanduser()
        slide_path = (Path.cwd() / slide_path).resolve() if not slide_path.is_absolute() else slide_path.resolve()
        if not folder_contains_raw_slide_files(slide_path, args.raw_extensions):
            ap.error(f"--slide-folder must point to a raw WSI leaf folder containing one of {args.raw_extensions}: {slide_path}")
        project_root = slide_path.parent.resolve()
        args.slide_folder = slide_path
        args.target_folder = project_root
        args.raw_root = project_root
        args.raw_source_limit_dir = slide_path
        args._single_folder_mode = True
        args._single_relative_parent = slide_path.relative_to(project_root)
        args._target_folder_name = project_root.name
        args.export_root = (project_root.parent / f"{project_root.name}_EXPORT_L0_L3").resolve()
        args.include = "*"
        if args.convert_to_pyramidal and args.pyramidal_root is None:
            args.pyramidal_root = (project_root.parent / f"{project_root.name}_EXPORT_L0_L3_PYRAMIDAL").resolve()

    if args.raw_root is not None:
        args.raw_root = args.raw_root.expanduser().resolve()
    if args.raw_source_limit_dir is not None:
        args.raw_source_limit_dir = args.raw_source_limit_dir.expanduser().resolve()
    if args.export_root is not None:
        args.export_root = args.export_root.expanduser().resolve()
    if args.input_slide is not None:
        args.input_slide = args.input_slide.expanduser().resolve()
    if args.output_root is not None:
        args.output_root = args.output_root.expanduser().resolve()
    if args.output is not None:
        args.output = args.output.expanduser().resolve()
    if args.store_root is not None:
        args.store_root = args.store_root.expanduser().resolve()
    if args.pyramidal_root is not None:
        args.pyramidal_root = args.pyramidal_root.expanduser().resolve()
    if args.export_python is not None:
        args.export_python = args.export_python.expanduser().resolve()
    if args.histoplus_model_path is not None:
        args.histoplus_model_path = args.histoplus_model_path.expanduser().resolve()
    if args.histoplus_cache_dir is not None:
        args.histoplus_cache_dir = args.histoplus_cache_dir.expanduser().resolve()
    if args.hf_token_file is not None:
        args.hf_token_file = args.hf_token_file.expanduser().resolve()
    if args.copy_histoplus_weight_to is not None:
        args.copy_histoplus_weight_to = args.copy_histoplus_weight_to.expanduser().resolve()

    return args



def main_output_base(args: argparse.Namespace) -> Path:
    if getattr(args, "internal_export_only", False):
        return Path(args.export_root)
    if getattr(args, "output", None) is not None:
        return Path(args.output)
    if getattr(args, "output_root", None) is not None:
        return Path(args.output_root)
    if getattr(args, "export_root", None) is not None:
        return Path(args.export_root)
    return Path.cwd()
    if getattr(args, "output", None) is not None:
        return Path(args.output)
    if getattr(args, "output_root", None) is not None:
        return Path(args.output_root)
    return Path.cwd()


def slide_output_dir(args: argparse.Namespace, job: SlideJob) -> Path:
    if getattr(args, "output", None) is not None:
        return Path(args.output)
    if getattr(args, "output_root", None) is not None:
        return Path(args.output_root) / job.slide_id
    return Path.cwd() / job.slide_id


# ----------------------------- utilities -----------------------------


def setup_logger(base_dir: Path, level: str) -> logging.Logger:
    base_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("lazyslide_histoplus")
    logger.setLevel(getattr(logging, level))
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(getattr(logging, level))
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    fh = logging.FileHandler(base_dir / "lazyslide_histoplus.log")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger


def slugify(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._-")


def fnmatch(text: str, pattern: str) -> bool:
    import fnmatch as _fnmatch
    return _fnmatch.fnmatch(text, pattern)


def normalized_extensions(extensions: Sequence[str]) -> set[str]:
    return {str(e).lower() if str(e).startswith(".") else f".{str(e).lower()}" for e in extensions}


def path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def folder_contains_raw_slide_files(folder: Path, extensions: Sequence[str]) -> bool:
    if folder is None or not Path(folder).exists() or not Path(folder).is_dir():
        return False
    wanted = normalized_extensions(extensions)
    try:
        return any(p.is_file() and p.suffix.lower() in wanted for p in Path(folder).iterdir())
    except Exception:
        return False


def safe_remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink()
        except Exception:
            pass


@contextmanager
def timed_stage(logger: logging.Logger, name: str) -> Iterator[None]:
    start = time.perf_counter()
    logger.info("STAGE START | %s", name)
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        logger.info("STAGE DONE | %s | elapsed_sec=%.1f elapsed_min=%.2f", name, elapsed, elapsed / 60.0)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Atomically replace a JSON completion marker after a durable file write."""

    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.close(file_descriptor)
        except OSError:
            pass
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def relativize_output_paths(value: Any, output_root: Path) -> Any:
    """Recursively replace task-local absolute output paths with portable relative paths."""

    if isinstance(value, dict):
        return {key: relativize_output_paths(item, output_root) for key, item in value.items()}
    if isinstance(value, list):
        return [relativize_output_paths(item, output_root) for item in value]
    if isinstance(value, tuple):
        return [relativize_output_paths(item, output_root) for item in value]
    if isinstance(value, str):
        candidate = Path(value)
        if candidate.is_absolute():
            try:
                return candidate.relative_to(output_root).as_posix()
            except ValueError:
                pass
    return value


def ensure_importable() -> tuple[Any, Any, Any, Any]:
    try:
        import lazyslide as zs  # type: ignore
        from wsidata import open_wsi  # type: ignore
        from shapely.geometry import Polygon, MultiPolygon, GeometryCollection, box  # type: ignore
        from tiffslide import TiffSlide  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "LazySlide / wsidata / shapely / tiffslide are not importable. Activate the lazyslide311 environment first."
        ) from exc
    return zs, open_wsi, (Polygon, MultiPolygon, GeometryCollection, box), TiffSlide


def normalize_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def canonical_class_name_and_id(value: Any) -> tuple[str, int]:
    if value is None:
        return "Unknown", -1
    if isinstance(value, (int, np.integer)):
        cid = int(value)
        if cid in HISTOPLUS_CLASS_INFO:
            return HISTOPLUS_CLASS_INFO[cid][0], cid
        return f"Class {cid}", cid
    if isinstance(value, float) and math.isfinite(value) and float(value).is_integer():
        cid = int(value)
        if cid in HISTOPLUS_CLASS_INFO:
            return HISTOPLUS_CLASS_INFO[cid][0], cid
        return f"Class {cid}", cid
    key = normalize_name(value)
    cid = NAME_TO_ID.get(key, NAME_ALIASES.get(key, -1))
    if cid in HISTOPLUS_CLASS_INFO:
        return HISTOPLUS_CLASS_INFO[cid][0], cid
    return str(value), cid


def color_hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    if len(color) != 6:
        raise ValueError(f"Unexpected hex color: {color}")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def nearest_divisible(value: int, divisor: int) -> int:
    if divisor <= 0:
        raise ValueError("divisor must be > 0")
    if value <= divisor:
        return divisor
    lower = max(divisor, (value // divisor) * divisor)
    upper = max(divisor, lower + divisor)
    if value % divisor == 0:
        return value
    if abs(value - lower) <= abs(upper - value):
        return lower
    return upper


def resolve_histoplus_tile_px(requested_tile_px: int, logger: Optional[logging.Logger] = None) -> int:
    effective = nearest_divisible(int(requested_tile_px), HISTOPLUS_TILE_DIVISOR)
    if int(requested_tile_px) != effective and logger is not None:
        logger.warning(
            "Requested --tile-px=%d is invalid for HistoPLUS. Adjusting to %d because the tile edge must be divisible by %d. "
            "For the documented LazySlide HistoPLUS default, use --tile-px %d.",
            int(requested_tile_px),
            int(effective),
            int(HISTOPLUS_TILE_DIVISOR),
            int(HISTOPLUS_DEFAULT_TILE_PX),
        )
    return effective


def inspect_tiff_layout(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "path": str(path),
        "exists": bool(path.exists()),
        "n_levels": 1,
        "is_tiled": False,
        "is_bigtiff": False,
        "width": None,
        "height": None,
        "error": None,
    }
    if not path.exists():
        return info
    try:
        with tifffile.TiffFile(str(path)) as tf:
            info["is_bigtiff"] = bool(getattr(tf, "is_bigtiff", False))
            try:
                series = tf.series[0]
                levels = getattr(series, "levels", None)
                if levels is not None and len(levels) > 0:
                    info["n_levels"] = int(len(levels))
                    page0 = levels[0].pages[0]
                    shape = getattr(levels[0], "shape", getattr(page0, "shape", None))
                else:
                    page0 = tf.pages[0]
                    shape = getattr(page0, "shape", None)
                info["is_tiled"] = bool(getattr(page0, "is_tiled", False))
                if shape is not None and len(shape) >= 2:
                    info["height"] = int(shape[0])
                    info["width"] = int(shape[1])
            except Exception:
                page0 = tf.pages[0]
                info["is_tiled"] = bool(getattr(page0, "is_tiled", False))
                shape = getattr(page0, "shape", None)
                if shape is not None and len(shape) >= 2:
                    info["height"] = int(shape[0])
                    info["width"] = int(shape[1])
    except Exception as exc:
        info["error"] = str(exc)
    return info


def is_tiled_pyramidal_tiff(info: dict[str, Any]) -> bool:
    try:
        return bool(info.get("exists")) and bool(info.get("is_tiled")) and int(info.get("n_levels", 1)) > 1
    except Exception:
        return False


def pyramidal_output_path(args: argparse.Namespace, job: SlideJob, slide_out: Path) -> Path:
    if args.pyramidal_root is not None:
        return args.pyramidal_root / job.relative_parent / job.l0_path.name
    return slide_out / "pyramidal_input" / job.l0_path.name


PYRAMIDAL_CACHE_PROVENANCE_SCHEMA = "histoplus_pyramidal_cache_v1"


def pyramidal_cache_provenance_path(pyramidal_path: Path) -> Path:
    return pyramidal_path.with_name(f"{pyramidal_path.name}.provenance.json")


def pyramidal_cache_provenance(src: Path, args: argparse.Namespace) -> dict[str, Any]:
    """Describe the source and conversion settings that a cached pyramid represents."""

    return {
        "schema": PYRAMIDAL_CACHE_PROVENANCE_SCHEMA,
        "source_l0": input_file_fingerprint(src),
        "conversion": {
            "tile": int(args.pyramidal_tile),
            "compression": _normalized_pyramidal_compression(args.pyramidal_compression),
            "jpeg_q": int(args.pyramidal_jpeg_q),
            "pyramid": True,
            "bigtiff": True,
            "slide_mpp_override": (
                float(args.slide_mpp) if getattr(args, "slide_mpp", None) is not None else None
            ),
        },
    }


def pyramidal_cache_provenance_matches(
    path: Path,
    expected: dict[str, Any],
) -> tuple[bool, str]:
    if not path.is_file():
        return False, "missing"
    try:
        candidate = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, RuntimeError, UnicodeError, json.JSONDecodeError):
        return False, "unreadable"
    if not isinstance(candidate, dict):
        return False, "not-a-json-object"
    if candidate != expected:
        return False, "source-or-settings-mismatch"
    return True, "match"


def _normalized_pyramidal_compression(value: str) -> str:
    comp = str(value).strip().lower()
    if comp in {"no", "none", "uncompressed"}:
        return "none"
    return comp


def _convert_with_pyvips(src: Path, dst: Path, args: argparse.Namespace) -> None:
    import pyvips  # type: ignore

    compression = _normalized_pyramidal_compression(args.pyramidal_compression)
    image = pyvips.Image.new_from_file(str(src), access="sequential")
    kwargs: dict[str, Any] = {
        "tile": True,
        "tile_width": int(args.pyramidal_tile),
        "tile_height": int(args.pyramidal_tile),
        "pyramid": True,
        "bigtiff": True,
        "compression": compression,
    }
    if compression == "jpeg":
        kwargs["Q"] = int(args.pyramidal_jpeg_q)
    source_mpp = getattr(args, "slide_mpp", None)
    if source_mpp is not None:
        pixels_per_mm = 1000.0 / float(source_mpp)
        kwargs["xres"] = pixels_per_mm
        kwargs["yres"] = pixels_per_mm
    else:
        for key in ["xres", "yres"]:
            try:
                value = float(image.get(key))
                if math.isfinite(value) and value > 0:
                    kwargs[key] = value
            except Exception:
                pass
    try:
        image.tiffsave(str(dst), **kwargs)
    except TypeError:
        # Some libvips builds accept a slightly smaller option set.
        kwargs.pop("xres", None)
        kwargs.pop("yres", None)
        image.tiffsave(str(dst), **kwargs)


def _convert_with_vips_cli(src: Path, dst: Path, args: argparse.Namespace) -> None:
    vips_bin = shutil.which("vips")
    if not vips_bin:
        raise RuntimeError("The 'vips' executable was not found in PATH.")

    compression = _normalized_pyramidal_compression(args.pyramidal_compression)
    cmd = [
        vips_bin,
        "tiffsave",
        str(src),
        str(dst),
        "--tile",
        f"--tile-width={int(args.pyramidal_tile)}",
        f"--tile-height={int(args.pyramidal_tile)}",
        "--pyramid",
        "--bigtiff",
        f"--compression={compression}",
    ]
    if compression == "jpeg":
        cmd.append(f"--Q={int(args.pyramidal_jpeg_q)}")
    source_mpp = getattr(args, "slide_mpp", None)
    if source_mpp is not None:
        pixels_per_mm = 1000.0 / float(source_mpp)
        cmd.extend([f"--xres={pixels_per_mm:.12g}", f"--yres={pixels_per_mm:.12g}"])
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"vips tiffsave failed with exit code {proc.returncode}")


def l2_companion_path(l0_path: Path) -> Path:
    return l0_path.with_name(l0_path.name.replace("_L0_", "_L2_"))


def sampled_patch_mode_enabled(args: argparse.Namespace) -> bool:
    # Percent-slide sampling now operates on LazySlide tissue tiles from the original
    # or converted slide. A collage processing slide is only built when explicitly
    # requested with --collage for backwards compatibility.
    return getattr(args, "collage_grid", None) is not None


def parse_collage_grid(value: Optional[str]) -> Optional[int]:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().lower()
    match = re.fullmatch(r"(\d+)\s*x\s*(\d+)", text)
    if not match:
        raise ValueError("--collage must use square NxN format, for example 3x3, 4x4, 5x5, or 6x6")
    rows = int(match.group(1))
    cols = int(match.group(2))
    if rows != cols:
        raise ValueError("--collage must be square; use NxN such as 3x3 or 4x4")
    if rows <= 0:
        raise ValueError("--collage grid size must be > 0")
    return rows


def select_patch_records_from_l2(
    l0_path: Path,
    l2_path: Path,
    percent_slide: float,
    patch_size: int,
    seed: int,
    max_patches: int,
    collage_grid: Optional[int],
    logger: logging.Logger,
) -> tuple[list[PatchRecord], dict[str, Any]]:
    with tifffile.TiffFile(str(l2_path)) as tif:
        l2_rgb = tif.asarray()
    if l2_rgb.ndim == 2:
        l2_rgb = np.stack([l2_rgb] * 3, axis=-1)
    if l2_rgb.ndim == 3 and l2_rgb.shape[-1] > 3:
        l2_rgb = l2_rgb[..., :3]

    with tifffile.TiffFile(str(l0_path)) as tif:
        page = tif.pages[0]
        l0_h, l0_w = int(page.shape[0]), int(page.shape[1])

    l2_h, l2_w = int(l2_rgb.shape[0]), int(l2_rgb.shape[1])
    sx = l0_w / float(l2_w)
    sy = l0_h / float(l2_h)
    patch_l2_w = max(1, int(round(patch_size / sx)))
    patch_l2_h = max(1, int(round(patch_size / sy)))
    stride_l2_x = max(1, patch_l2_w)
    stride_l2_y = max(1, patch_l2_h)

    gray = l2_rgb.astype(np.float32).mean(axis=2)
    tissue_mask = gray < 235.0
    candidates: list[tuple[int, int, float]] = []
    y_positions = list(range(0, max(1, l2_h - patch_l2_h + 1), stride_l2_y))
    x_positions = list(range(0, max(1, l2_w - patch_l2_w + 1), stride_l2_x))
    if not y_positions or y_positions[-1] != max(0, l2_h - patch_l2_h):
        y_positions.append(max(0, l2_h - patch_l2_h))
    if not x_positions or x_positions[-1] != max(0, l2_w - patch_l2_w):
        x_positions.append(max(0, l2_w - patch_l2_w))

    for y in tqdm(y_positions, desc="Scanning L2 patch grid", unit="row", leave=False):
        for x in x_positions:
            frac = float(tissue_mask[y : min(l2_h, y + patch_l2_h), x : min(l2_w, x + patch_l2_w)].mean())
            candidates.append((x, y, frac))

    if not candidates:
        candidates = [(max(0, l2_w // 2 - patch_l2_w // 2), max(0, l2_h // 2 - patch_l2_h // 2), 0.0)]

    requested_grid = int(collage_grid) if collage_grid is not None else None
    if requested_grid is not None:
        n_requested = requested_grid * requested_grid
        n_keep = min(len(candidates), n_requested)
        cols = requested_grid
        rows = requested_grid
    else:
        n_keep = max(1, min(len(candidates), int(math.ceil(len(candidates) * percent_slide / 100.0))))
        if int(max_patches) > 0:
            n_keep = min(n_keep, int(max_patches))
        cols = max(1, int(math.ceil(math.sqrt(n_keep))))
        rows = max(1, int(math.ceil(n_keep / float(cols))))
    rng = np.random.default_rng(int(seed))
    chosen_idx = rng.choice(len(candidates), size=n_keep, replace=False)

    records: list[PatchRecord] = []
    for out_i, cand_i in enumerate(tqdm(chosen_idx.tolist(), desc="Selecting sampled patches", unit="patch", leave=False)):
        x_l2, y_l2, frac = candidates[cand_i]
        src_x = max(0, min(l0_w - patch_size, int(round(x_l2 * sx)))) if l0_w > patch_size else 0
        src_y = max(0, min(l0_h - patch_size, int(round(y_l2 * sy)))) if l0_h > patch_size else 0
        width = min(patch_size, l0_w - src_x)
        height = min(patch_size, l0_h - src_y)
        row = out_i // cols
        col = out_i % cols
        records.append(
            PatchRecord(
                patch_id=out_i + 1,
                mosaic_x0=int(col * patch_size),
                mosaic_y0=int(row * patch_size),
                source_x0=int(src_x),
                source_y0=int(src_y),
                width=int(width),
                height=int(height),
                tissue_fraction=float(frac),
            )
        )

    summary = {
        "enabled": True,
        "l2_path": str(l2_path),
        "percent_slide": float(percent_slide),
        "patch_size": int(patch_size),
        "random_seed": int(seed),
        "n_candidate_patches": int(len(candidates)),
        "n_sampled_patches": int(len(records)),
        "actual_percent_patches": float(100.0 * len(records) / max(1, len(candidates))),
        "max_sampled_patches": int(max_patches),
        "collage": f"{requested_grid}x{requested_grid}" if requested_grid is not None else None,
        "collage_grid": int(requested_grid) if requested_grid is not None else None,
        "mosaic_columns": int(cols),
        "mosaic_rows": int(rows),
        "source_width": int(l0_w),
        "source_height": int(l0_h),
        "l2_width": int(l2_w),
        "l2_height": int(l2_h),
    }
    logger.info(
        "Patch sampling selected %d/%d L0 patches using L2 grid percent_slide=%.3f patch_size=%d",
        len(records),
        len(candidates),
        percent_slide,
        patch_size,
    )
    return records, summary


def write_patch_mosaic(
    l0_path: Path,
    records: Sequence[PatchRecord],
    patch_size: int,
    out_flat_tif: Path,
    logger: logging.Logger,
    mosaic_grid: Optional[int] = None,
) -> tuple[int, int]:
    if not records:
        raise ValueError("No sampled patches available for mosaic export.")
    if mosaic_grid is not None:
        cols = rows = int(mosaic_grid)
    else:
        cols = max(1, max(r.mosaic_x0 // patch_size for r in records) + 1)
        rows = max(1, max(r.mosaic_y0 // patch_size for r in records) + 1)
    mosaic_w = cols * patch_size
    mosaic_h = rows * patch_size
    mosaic = Image.new("RGB", (mosaic_w, mosaic_h), (255, 255, 255))
    from tiffslide import TiffSlide

    with TiffSlide(str(l0_path)) as slide:
        for rec in tqdm(records, desc="Writing patch mosaic", unit="patch", leave=False):
            region = slide.read_region((int(rec.source_x0), int(rec.source_y0)), 0, (int(rec.width), int(rec.height))).convert("RGB")
            mosaic.paste(region, (int(rec.mosaic_x0), int(rec.mosaic_y0)))
    out_flat_tif.parent.mkdir(parents=True, exist_ok=True)
    mosaic.save(out_flat_tif, compression="tiff_deflate")
    logger.info("Wrote sampled patch mosaic flat TIFF: %s size=%dx%d", out_flat_tif, mosaic_w, mosaic_h)
    return mosaic_w, mosaic_h


def write_patch_records(path: Path, records: Sequence[PatchRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["patch_id", "mosaic_x0", "mosaic_y0", "source_x0", "source_y0", "width", "height", "tissue_fraction"])
        writer.writeheader()
        for rec in records:
            writer.writerow({k: getattr(rec, k) for k in writer.fieldnames})


def export_sampled_patch_report(
    l0_path: Path,
    slide_out: Path,
    args: argparse.Namespace,
    logger: logging.Logger,
) -> dict[str, Any]:
    percent = float(getattr(args, "percent_slide", 100.0))
    if percent >= 100.0:
        return {"enabled": False}

    l2_path = l2_companion_path(l0_path)
    if not l2_path.exists():
        raise FileNotFoundError(
            f"--percent-slide below 100 requires the companion L2 export for the sampled-patch report: {l2_path}"
        )

    patch_size = max(int(args.tile_px), int(args.tile_px) * 2)
    patch_root = slide_out / "sampled_patches"
    patch_root.mkdir(parents=True, exist_ok=True)
    manifest_csv = patch_root / "patch_manifest.csv"
    summary_json = patch_root / "patch_summary.json"

    records, summary = select_patch_records_from_l2(
        l0_path=l0_path,
        l2_path=l2_path,
        percent_slide=percent,
        patch_size=patch_size,
        seed=int(args.patch_random_seed),
        max_patches=int(args.max_sampled_patches),
        collage_grid=None,
        logger=logger,
    )

    rows: list[dict[str, Any]] = []
    from tiffslide import TiffSlide

    with TiffSlide(str(l0_path)) as slide:
        for rec in tqdm(records, desc="Writing sampled patch report", unit="patch", leave=False):
            patch_dir = patch_root / f"patch_{rec.patch_id:05d}"
            patch_dir.mkdir(parents=True, exist_ok=True)
            rgb_path = patch_dir / "rgb.tif"
            png_path = patch_dir / "rgb.png"
            region = slide.read_region((int(rec.source_x0), int(rec.source_y0)), 0, (int(rec.width), int(rec.height))).convert("RGB")
            region.save(rgb_path, compression="tiff_deflate")
            region.save(png_path)
            row = {
                "patch_id": int(rec.patch_id),
                "source_x0": int(rec.source_x0),
                "source_y0": int(rec.source_y0),
                "source_x1": int(rec.source_x0 + rec.width),
                "source_y1": int(rec.source_y0 + rec.height),
                "width": int(rec.width),
                "height": int(rec.height),
                "tissue_fraction": float(rec.tissue_fraction),
                "rgb_tif": str(rgb_path),
                "rgb_png": str(png_path),
            }
            write_json(patch_dir / "metadata.json", row)
            rows.append(row)

    pd.DataFrame(rows).to_csv(manifest_csv, index=False)
    summary.update({
        "enabled": True,
        "mode": "sampled_patch_report",
        "source_l0_path": str(l0_path),
        "patch_root": str(patch_root),
        "patch_manifest_csv": str(manifest_csv),
    })
    write_json(summary_json, relativize_output_paths(summary, slide_out))
    logger.info("Wrote sampled patch report: %s | patches=%d", manifest_csv, len(rows))
    return summary


def build_sampled_patch_processing_slide(
    job: SlideJob,
    slide_out: Path,
    args: argparse.Namespace,
    logger: logging.Logger,
) -> tuple[Path, dict[str, Any], list[PatchRecord]]:
    l2_path = l2_companion_path(job.l0_path)
    if not l2_path.exists():
        raise FileNotFoundError(f"Sampled patch mode requires the L2 export next to L0: {l2_path}")
    patch_size = max(int(args.tile_px), int(args.tile_px) * 2)
    patch_root = slide_out / "sampled_patch_mosaic"
    flat_tif = patch_root / "patch_mosaic_flat.tif"
    pyramidal_tif = patch_root / "patch_mosaic_pyramidal.tif"
    mapping_csv = patch_root / "patch_mosaic_mapping.csv"
    summary_json = patch_root / "patch_mosaic_summary.json"

    records, summary = select_patch_records_from_l2(
        l0_path=job.l0_path,
        l2_path=l2_path,
        percent_slide=float(args.percent_slide),
        patch_size=patch_size,
        seed=int(args.patch_random_seed),
        max_patches=int(args.max_sampled_patches),
        collage_grid=getattr(args, "collage_grid", None),
        logger=logger,
    )
    write_patch_mosaic(job.l0_path, records, patch_size, flat_tif, logger, mosaic_grid=getattr(args, "collage_grid", None))
    tmp_pyr = pyramidal_tif.with_name(pyramidal_tif.name + ".tmp.tif")
    if tmp_pyr.exists():
        tmp_pyr.unlink()
    if pyramidal_tif.exists():
        pyramidal_tif.unlink()
    for backend_name, backend_fn in [("pyvips", _convert_with_pyvips), ("vips", _convert_with_vips_cli)]:
        try:
            logger.info("Converting sampled patch mosaic to pyramidal TIFF via %s: %s", backend_name, pyramidal_tif)
            backend_fn(flat_tif, tmp_pyr, args)
            tmp_pyr.replace(pyramidal_tif)
            summary["backend"] = backend_name
            break
        except Exception as exc:
            logger.warning("Sampled patch mosaic pyramidal conversion failed with %s: %s", backend_name, exc)
            if tmp_pyr.exists():
                tmp_pyr.unlink()
    if not pyramidal_tif.exists():
        logger.warning("Using non-pyramidal sampled patch mosaic because pyramidal conversion failed: %s", flat_tif)
        pyramidal_tif = flat_tif
        summary["backend"] = "flat_tiff_fallback"

    write_patch_records(mapping_csv, records)
    summary.update({
        "mode": "sampled_patch_mosaic",
        "source_l0_path": str(job.l0_path),
        "flat_mosaic_tif": str(flat_tif),
        "processing_l0_path": str(pyramidal_tif),
        "patch_mapping_csv": str(mapping_csv),
    })
    write_json(summary_json, relativize_output_paths(summary, slide_out))
    return pyramidal_tif, summary, records


def remap_patch_mosaic_dataframe(df: pd.DataFrame, records: Sequence[PatchRecord], logger: logging.Logger) -> pd.DataFrame:
    if df.empty or not records:
        return df
    try:
        from shapely import affinity
    except Exception as exc:
        logger.warning("Could not import shapely.affinity; leaving sampled patch coordinates in mosaic space: %s", exc)
        return df
    out = df.copy()
    patch_ids: list[int] = []
    source_x: list[float] = []
    source_y: list[float] = []
    new_geoms: list[Any] = []
    for row in out.itertuples(index=False):
        cx = float(row.centroid_x)
        cy = float(row.centroid_y)
        rec = next((r for r in records if r.mosaic_x0 <= cx < r.mosaic_x0 + r.width and r.mosaic_y0 <= cy < r.mosaic_y0 + r.height), None)
        if rec is None:
            patch_ids.append(-1)
            source_x.append(float("nan"))
            source_y.append(float("nan"))
            new_geoms.append(row.geometry)
            continue
        dx = float(rec.source_x0 - rec.mosaic_x0)
        dy = float(rec.source_y0 - rec.mosaic_y0)
        patch_ids.append(int(rec.patch_id))
        source_x.append(cx + dx)
        source_y.append(cy + dy)
        new_geoms.append(affinity.translate(row.geometry, xoff=dx, yoff=dy))
    out["patch_id"] = patch_ids
    out["centroid_x"] = source_x
    out["centroid_y"] = source_y
    out["geometry"] = new_geoms
    bounds = geometry_bounds_table(out)
    out["bbox_x0"] = bounds["minx"].to_numpy(dtype=float)
    out["bbox_y0"] = bounds["miny"].to_numpy(dtype=float)
    out["bbox_x1"] = bounds["maxx"].to_numpy(dtype=float)
    out["bbox_y1"] = bounds["maxy"].to_numpy(dtype=float)
    out["polygon_coords_json"] = [json.dumps(geometry_to_jsonable_coords(geom), ensure_ascii=False) for geom in out["geometry"]]
    logger.info("Remapped %d sampled patch cell geometries back to original L0 coordinates.", len(out))
    return out


def ensure_pyramidal_processing_slide(job: SlideJob, slide_out: Path, args: argparse.Namespace, logger: logging.Logger) -> tuple[Path, dict[str, Any]]:
    src = job.l0_path
    src_info = inspect_tiff_layout(src)
    conversion_summary: dict[str, Any] = {
        "source_l0_path": str(src),
        "source_info": src_info,
        "convert_to_pyramidal": bool(args.convert_to_pyramidal),
        "converted": False,
        "processing_l0_path": str(src),
        "processing_info": src_info,
        "backend": None,
        "compression": _normalized_pyramidal_compression(args.pyramidal_compression),
        "tile": int(args.pyramidal_tile),
        "jpeg_q": int(args.pyramidal_jpeg_q),
    }

    if not args.convert_to_pyramidal:
        if is_tiled_pyramidal_tiff(src_info):
            logger.info("Input slide is already tiled+pyramidal; using original L0 TIFF: %s", src)
        return src, conversion_summary

    if is_tiled_pyramidal_tiff(src_info):
        logger.info("Input slide is already tiled+pyramidal; reusing original L0 TIFF: %s", src)
        return src, conversion_summary

    dst = pyramidal_output_path(args, job, slide_out)
    provenance_path = pyramidal_cache_provenance_path(dst)
    expected_provenance = pyramidal_cache_provenance(src, args)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if args.overwrite:
        safe_remove_path(dst)
        safe_remove_path(provenance_path)

    if dst.exists():
        dst_info = inspect_tiff_layout(dst)
        provenance_matches, provenance_reason = pyramidal_cache_provenance_matches(
            provenance_path,
            expected_provenance,
        )
        if is_tiled_pyramidal_tiff(dst_info) and provenance_matches:
            logger.info("Using existing converted pyramidal BigTIFF: %s", dst)
            conversion_summary.update({
                "processing_l0_path": str(dst),
                "processing_info": dst_info,
                "converted": False,
                "backend": "cached",
                "cache_provenance_path": str(provenance_path),
            })
            return dst, conversion_summary
        cache_reason = (
            "invalid-or-incomplete-tiff"
            if not is_tiled_pyramidal_tiff(dst_info)
            else provenance_reason
        )
        logger.warning(
            "Existing pyramidal cache cannot be reused (%s); rebuilding: %s",
            cache_reason,
            dst,
        )
        safe_remove_path(dst)
        safe_remove_path(provenance_path)
    elif provenance_path.exists():
        logger.warning(
            "Removing orphaned pyramidal provenance sidecar before rebuilding: %s",
            provenance_path,
        )
        safe_remove_path(provenance_path)

    tmp_dst = dst.with_name(dst.name + ".tmp.tif")
    if tmp_dst.exists():
        try:
            tmp_dst.unlink()
        except Exception:
            shutil.rmtree(tmp_dst, ignore_errors=True)

    conversion_errors: list[str] = []
    backend_used: Optional[str] = None
    for backend_name, backend_fn in [("pyvips", _convert_with_pyvips), ("vips", _convert_with_vips_cli)]:
        try:
            logger.info(
                "Converting non-pyramidal L0 TIFF to tiled pyramidal BigTIFF via %s: %s -> %s",
                backend_name,
                src,
                dst,
            )
            backend_fn(src, tmp_dst, args)
            backend_used = backend_name
            break
        except Exception as exc:
            conversion_errors.append(f"{backend_name}: {exc}")
            try:
                if tmp_dst.exists():
                    tmp_dst.unlink()
            except Exception:
                pass

    if backend_used is None:
        raise RuntimeError(
            "Could not convert the L0 TIFF into a pyramidal BigTIFF. Install pyvips/libvips or the 'vips' CLI. "
            f"Backend errors: {' | '.join(conversion_errors)}"
        )

    tmp_dst.replace(dst)
    dst_info = inspect_tiff_layout(dst)
    if not is_tiled_pyramidal_tiff(dst_info):
        safe_remove_path(dst)
        safe_remove_path(provenance_path)
        raise RuntimeError(
            f"Converted TIFF does not look tiled+pyramidal: {dst} | info={dst_info}"
        )

    # The sidecar is the cache completion marker. Publish it atomically only
    # after the converted TIFF has passed structural validation.
    write_json_atomic(provenance_path, expected_provenance)

    logger.info(
        "Pyramidal BigTIFF ready: %s | tiled=%s levels=%s bigtiff=%s",
        dst,
        dst_info.get("is_tiled"),
        dst_info.get("n_levels"),
        dst_info.get("is_bigtiff"),
    )

    conversion_summary.update({
        "converted": True,
        "backend": backend_used,
        "processing_l0_path": str(dst),
        "processing_info": dst_info,
        "cache_provenance_path": str(provenance_path),
    })
    return dst, conversion_summary


def _read_first_nonempty_line(path: Path) -> Optional[str]:
    if not path.exists():
        raise FileNotFoundError(f"Hugging Face token file not found: {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        token = line.strip()
        if token:
            return token
    return None


def get_hf_token(args: argparse.Namespace) -> Optional[str]:
    cached = getattr(args, "_resolved_hf_token", None)
    if cached:
        return str(cached)
    if args.hf_token:
        token = str(args.hf_token).strip()
        if token:
            args._resolved_hf_token = token
            return token
    if args.hf_token_file is not None:
        token = _read_first_nonempty_line(args.hf_token_file)
        if token:
            args._resolved_hf_token = token
            return token
    for env_name in [args.hf_token_env, "HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN"]:
        token = os.getenv(env_name)
        if token and str(token).strip():
            token = str(token).strip()
            args._resolved_hf_token = token
            return token
    return None


def maybe_login_huggingface(args: argparse.Namespace, logger: logging.Logger) -> None:
    if not bool(args.hf_login):
        return
    if getattr(args, "_hf_login_done", False):
        return
    try:
        from huggingface_hub import login, interpreter_login  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "huggingface_hub is required for --hf-login. Install or upgrade it in the lazyslide environment first."
        ) from exc

    token = get_hf_token(args)
    try:
        if token:
            login(token=token, add_to_git_credential=False, skip_if_logged_in=False)
            logger.info("Stored Hugging Face token using huggingface_hub.login().")
        else:
            logger.info("Starting interactive Hugging Face terminal login via interpreter_login().")
            interpreter_login(skip_if_logged_in=True)
    except Exception as exc:
        raise RuntimeError(
            "Hugging Face login failed. Check that the token is a personal access token with read access."
        ) from exc
    args._hf_login_done = True


def expected_histoplus_weight_filename(magnification: str) -> str:
    mag = str(magnification).lower()
    if mag not in {"20x", "40x"}:
        raise ValueError(f"Unsupported HistoPLUS magnification: {magnification}")
    return f"histoplus_cellvit_segmentor_{mag}.pt"


HISTOPLUS_WEIGHT_PROVENANCE_SCHEMA = "histoplus_weight_provenance_v1"


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def weight_file_identity(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    before = resolved.stat()
    digest = sha256_file(resolved)
    after = resolved.stat()
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
        raise RuntimeError(f"File changed while it was fingerprinted: {resolved}")
    return {
        "path": str(resolved),
        "size_bytes": int(after.st_size),
        "mtime_ns": int(after.st_mtime_ns),
        "ctime_ns": int(after.st_ctime_ns),
        "device": int(after.st_dev),
        "inode": int(after.st_ino),
        "sha256": digest,
    }


def requested_histoplus_weight_identity(args: argparse.Namespace) -> dict[str, Any]:
    filename = expected_histoplus_weight_filename(
        getattr(args, "histoplus_magnification", "20x")
    )
    model_path = getattr(args, "histoplus_model_path", None)
    if model_path is not None:
        candidate = Path(model_path).expanduser().resolve()
        return {
            "source": "local_file",
            "filename": filename,
            "file": weight_file_identity(candidate) if candidate.is_file() else {
                "path": str(candidate),
                "available": False,
            },
        }
    return {
        "source": "huggingface",
        "repo_id": str(getattr(args, "histoplus_repo_id", DEFAULT_HISTOPLUS_REPO_ID)),
        "revision": str(getattr(args, "histoplus_revision", DEFAULT_HISTOPLUS_REVISION)).lower(),
        "filename": filename,
    }


def current_histoplus_weight_identity(args: argparse.Namespace) -> dict[str, Any]:
    resolved = getattr(args, "_resolved_histoplus_weight_identity", None)
    return resolved if isinstance(resolved, dict) else requested_histoplus_weight_identity(args)


def resolved_histoplus_weight_identity(
    requested_identity: dict[str, Any], weight_path: Path
) -> dict[str, Any]:
    resolved_path = weight_path.expanduser().resolve()
    requested_file = requested_identity.get("file")
    if (
        requested_identity.get("source") == "local_file"
        and isinstance(requested_file, dict)
        and requested_file.get("path") == str(resolved_path)
        and requested_file.get("sha256")
    ):
        resolved_file = requested_file
    else:
        resolved_file = weight_file_identity(resolved_path)
    return {**requested_identity, "resolved_file": resolved_file}


def histoplus_weight_provenance_path(weight_path: Path) -> Path:
    return weight_path.with_name(f"{weight_path.name}.provenance.json")


def write_histoplus_weight_provenance(
    weight_path: Path,
    requested_identity: dict[str, Any],
) -> None:
    payload = {
        "schema": HISTOPLUS_WEIGHT_PROVENANCE_SCHEMA,
        "requested_identity": requested_identity,
        "resolved_file": weight_file_identity(weight_path),
    }
    write_json_atomic(histoplus_weight_provenance_path(weight_path), payload)


def cached_weight_has_requested_provenance(
    weight_path: Path,
    requested_identity: dict[str, Any],
) -> bool:
    provenance_path = histoplus_weight_provenance_path(weight_path)
    try:
        payload = json.loads(provenance_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return False
        if payload.get("schema") != HISTOPLUS_WEIGHT_PROVENANCE_SCHEMA:
            return False
        if payload.get("requested_identity") != requested_identity:
            return False
        resolved_file = payload.get("resolved_file")
        if not isinstance(resolved_file, dict):
            return False
        current = weight_file_identity(weight_path)
        return (
            resolved_file.get("size_bytes") == current["size_bytes"]
            and resolved_file.get("sha256") == current["sha256"]
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False


def _huggingface_snapshot_weight_path(repo_id: str, revision: str, filename: str) -> Path:
    model_cache_name = f"models--{repo_id.replace('/', '--')}"
    return (
        Path.home()
        / ".cache"
        / "huggingface"
        / "hub"
        / model_cache_name
        / "snapshots"
        / revision
        / filename
    )


def find_local_histoplus_weight(
    args: argparse.Namespace,
    filename: str,
    logger: Optional[logging.Logger] = None,
) -> Optional[Path]:
    requested_identity = requested_histoplus_weight_identity(args)
    if requested_identity.get("source") != "huggingface":
        return None

    repo_id = str(requested_identity["repo_id"])
    revision = str(requested_identity["revision"])
    pinned_snapshot = _huggingface_snapshot_weight_path(repo_id, revision, filename)
    if pinned_snapshot.is_file():
        return pinned_snapshot.resolve()

    candidates: list[Path] = []
    cache_dir = getattr(args, "histoplus_cache_dir", None)
    if cache_dir is not None:
        candidates.append(Path(cache_dir) / filename)
    candidates.append(Path.home() / ".cache" / "histoplus" / filename)

    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.expanduser().resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        if not candidate.is_file():
            continue
        if cached_weight_has_requested_provenance(candidate, requested_identity):
            return candidate
        if logger is not None:
            logger.warning(
                "Ignoring unprovenanced or mismatched HistoPLUS cache file for pinned revision %s: %s",
                revision,
                candidate,
            )
    return None


def maybe_copy_histoplus_weight(
    args: argparse.Namespace,
    resolved_weight: Path,
    logger: logging.Logger,
    requested_identity: dict[str, Any],
) -> Path:
    target_dir = getattr(args, "copy_histoplus_weight_to", None)
    if target_dir is None:
        return resolved_weight
    target_dir = Path(target_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    dst = target_dir / resolved_weight.name
    if dst.resolve() != resolved_weight.resolve():
        shutil.copy2(resolved_weight, dst)
        logger.info("Copied HistoPLUS weight file to: %s", dst)
    write_histoplus_weight_provenance(dst, requested_identity)
    return dst



def resolve_histoplus_weight_source(args: argparse.Namespace, logger: logging.Logger) -> tuple[Path, str]:
    filename = expected_histoplus_weight_filename(args.histoplus_magnification)
    requested_identity = requested_histoplus_weight_identity(args)

    cached_path = getattr(args, "_resolved_histoplus_weight", None)
    cached_name = getattr(args, "_resolved_histoplus_weight_filename", None)
    if cached_path is not None:
        weight_path = Path(str(cached_path)).expanduser().resolve()
        if weight_path.is_file():
            existing_identity = getattr(args, "_resolved_histoplus_weight_identity", None)
            existing_file = (
                existing_identity.get("resolved_file")
                if isinstance(existing_identity, dict)
                else None
            )
            existing_requested = (
                {key: value for key, value in existing_identity.items() if key != "resolved_file"}
                if isinstance(existing_identity, dict)
                else None
            )
            stat_result = weight_path.stat()
            if not (
                isinstance(existing_file, dict)
                and existing_requested == requested_identity
                and existing_file.get("path") == str(weight_path)
                and existing_file.get("size_bytes") == int(stat_result.st_size)
                and existing_file.get("mtime_ns") == int(stat_result.st_mtime_ns)
                and existing_file.get("ctime_ns") == int(stat_result.st_ctime_ns)
                and existing_file.get("device") == int(stat_result.st_dev)
                and existing_file.get("inode") == int(stat_result.st_ino)
            ):
                args._resolved_histoplus_weight_identity = resolved_histoplus_weight_identity(
                    requested_identity, weight_path
                )
            return weight_path, str(cached_name or filename)

    if args.histoplus_model_path is not None:
        weight_path = args.histoplus_model_path.expanduser().resolve()
        if not weight_path.exists():
            raise FileNotFoundError(
                f"Requested local HistoPLUS weight file not found: {weight_path}"
            )
        weight_path = maybe_copy_histoplus_weight(
            args, weight_path, logger, requested_identity
        )
        logger.info("Using user-supplied HistoPLUS weight file: %s", weight_path)
        args._resolved_histoplus_weight = str(weight_path)
        args._resolved_histoplus_weight_filename = filename
        args._resolved_histoplus_weight_identity = resolved_histoplus_weight_identity(
            requested_identity, weight_path
        )
        return weight_path, filename

    local_weight = find_local_histoplus_weight(args, filename, logger)
    if local_weight is not None:
        local_weight = maybe_copy_histoplus_weight(
            args, local_weight, logger, requested_identity
        )
        logger.info("Using locally cached HistoPLUS weight file: %s", local_weight)
        args._resolved_histoplus_weight = str(local_weight)
        args._resolved_histoplus_weight_filename = filename
        args._resolved_histoplus_weight_identity = {
            **requested_identity,
            "resolved_file": weight_file_identity(local_weight),
        }
        return local_weight, filename

    try:
        from huggingface_hub import hf_hub_download  # type: ignore
        from huggingface_hub.errors import GatedRepoError  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "huggingface_hub is required to fetch HistoPLUS weights. Install or upgrade it in the lazyslide environment."
        ) from exc

    token = get_hf_token(args)
    download_kwargs: dict[str, Any] = {
        "repo_id": args.histoplus_repo_id,
        "filename": filename,
        "revision": args.histoplus_revision,
        "force_download": bool(args.histoplus_force_download),
    }
    if token:
        download_kwargs["token"] = token

    try:
        cached = Path(hf_hub_download(**download_kwargs)).resolve()
    except GatedRepoError as exc:
        raise RuntimeError(
            "Cannot access the gated HistoPLUS weights yet. Request access on the Hugging Face model page first, "
            "then authenticate this server with 'hf auth login' or pass --hf-token / --hf-token-file / HF_TOKEN. "
            "You can also persist the token without any CLI by using --hf-login together with a supplied token. "
            f"Expected file for {args.histoplus_magnification} is {filename} from "
            f"{args.histoplus_repo_id} at revision {args.histoplus_revision}."
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            "Could not resolve the HistoPLUS weight file from Hugging Face. If you already have the file locally, "
            "pass --histoplus-weight-file /path/to/histoplus_cellvit_segmentor_<20x|40x>.pt."
        ) from exc

    cached = maybe_copy_histoplus_weight(args, cached, logger, requested_identity)
    logger.info("Resolved HistoPLUS weights from Hugging Face cache: %s", cached)
    args._resolved_histoplus_weight = str(cached)
    args._resolved_histoplus_weight_filename = filename
    args._resolved_histoplus_weight_identity = {
        **requested_identity,
        "resolved_file": weight_file_identity(cached),
    }
    return cached, filename



@contextmanager
def override_hf_hub_download(local_weight: Path, expected_filename: str):
    """Temporarily redirect hf_hub_download to a known local HistoPLUS weight file.

    LazySlide's current HistoPLUS wrapper advertises model_path/token in its public
    signature, but the implementation still downloads
    `histoplus_cellvit_segmentor_<magnification>.pt` internally. This override lets
    the pipeline use an explicit local file or a pre-fetched cached file reliably.
    """
    try:
        import huggingface_hub  # type: ignore
    except Exception:
        yield
        return

    original = huggingface_hub.hf_hub_download

    def _patched(repo_id: str, filename: str, *args, **kwargs):
        if filename == expected_filename:
            return str(local_weight)
        return original(repo_id, filename, *args, **kwargs)

    huggingface_hub.hf_hub_download = _patched
    try:
        yield
    finally:
        huggingface_hub.hf_hub_download = original


def detect_class_column(gdf: pd.DataFrame) -> Optional[str]:
    candidates = [
        "class",
        "cell_type",
        "celltype",
        "label",
        "classification",
        "type",
        "name",
        "class_name",
        "cell_class",
    ]
    for col in candidates:
        if col in gdf.columns:
            return col
    return None


def detect_class_id_column(gdf: pd.DataFrame) -> Optional[str]:
    candidates = [
        "class_id",
        "class_idx",
        "label_id",
        "type_id",
        "cell_type_id",
        "id",
    ]
    for col in candidates:
        if col in gdf.columns:
            return col
    return None


def detect_cell_id_column(gdf: pd.DataFrame) -> Optional[str]:
    candidates = ["cell_id", "instance_id", "object_id", "id"]
    for col in candidates:
        if col in gdf.columns:
            return col
    return None


def get_wsi_shape_table(wsi: Any, key: str) -> pd.DataFrame:
    errors: list[str] = []

    # WSIData in docs supports dictionary-style access.
    try:
        out = wsi[key]
        if out is not None:
            return out
    except Exception as exc:
        errors.append(f"wsi[key]: {exc}")

    # SpatialData-like .shapes slot.
    try:
        shapes = getattr(wsi, "shapes")
        if key in shapes:
            return shapes[key]
    except Exception as exc:
        errors.append(f"wsi.shapes[key]: {exc}")

    raise KeyError(f"Could not retrieve shapes table {key!r}. Errors: {' | '.join(errors)}")


PROCESSING_SIGNATURE_SCHEMA = "histoplus_processing_v2"


def input_file_fingerprint(path: Path) -> dict[str, Any]:
    """Return a deterministic identity for a slide without hashing a multi-GB WSI."""
    resolved = path.expanduser().resolve()
    stat_result = resolved.stat()
    payload = {
        "path": str(resolved),
        "size_bytes": int(stat_result.st_size),
        "mtime_ns": int(stat_result.st_mtime_ns),
        "ctime_ns": int(stat_result.st_ctime_ns),
        "device": int(stat_result.st_dev),
        "inode": int(stat_result.st_ino),
    }
    payload["sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def content_file_fingerprint(path: Path) -> dict[str, Any]:
    """Stream-hash a dependency and reject a file that changes during hashing."""

    return weight_file_identity(path)


def _signature_value(args: argparse.Namespace, name: str, default: Any) -> Any:
    value = getattr(args, name, default)
    if isinstance(value, Path):
        return str(value.expanduser().resolve())
    if isinstance(value, tuple):
        return list(value)
    return value


def processing_l2_fingerprint(job: SlideJob, args: argparse.Namespace) -> dict[str, Any] | None:
    """Fingerprint L2 whenever requested outputs or collage selection consume it."""

    uses_l2 = (
        float(getattr(args, "percent_slide", 100.0)) < 100.0
        or getattr(args, "collage_grid", None) is not None
    )
    if not uses_l2:
        return None
    l2_path = l2_companion_path(job.l0_path).expanduser().resolve()
    if not l2_path.is_file():
        return {"path": str(l2_path), "available": False}
    return content_file_fingerprint(l2_path)


def processing_signature_payload(job: SlideJob, args: argparse.Namespace) -> dict[str, Any]:
    model_identity = requested_histoplus_weight_identity(args)

    defaults: dict[str, Any] = {
        "mpp": 0.5,
        "slide_mpp": None,
        "tile_px": HISTOPLUS_DEFAULT_TILE_PX,
        "overlap": 0.2,
        "background_fraction": 0.95,
        "percent_slide": 100.0,
        "patch_random_seed": 20260709,
        "max_sampled_patches": 0,
        "collage_grid": None,
        "ops_level": 0,
        "tissue_level": "auto",
        "thumbnail_size": 2400,
        "store_root": None,
        "keep_store": False,
        "convert_to_pyramidal": False,
        "pyramidal_tile": 512,
        "pyramidal_compression": "lzw",
        "pyramidal_jpeg_q": 90,
        "device": "auto",
        "num_workers": 0,
        "amp": False,
        "run_cells_stage": False,
        "cells_model": "instanseg",
        "cells_batch_size": 4,
        "celltypes_batch_size": 2,
        "histoplus_magnification": "20x",
        "histoplus_repo_id": DEFAULT_HISTOPLUS_REPO_ID,
        "histoplus_revision": DEFAULT_HISTOPLUS_REVISION,
        "histoplus_force_download": False,
        "zoom_box": None,
        "zoom_size": 2000,
        "overlay_alpha": 0.35,
        "overlay_style": "outline_centroid",
        "overlay_outline_width": 2,
        "overlay_halo_width": 4,
        "overlay_draw_order": "small-last",
        "cell_marker_radius": 3,
        "figure_dpi": 300,
        "zoom_max_polygons": 0,
        "legend_background": False,
        "plain_csv": False,
        "export_qupath": False,
        "save_geojson_like_json": False,
        "qc_patch_count": 0,
        "qc_patch_size": 1024,
        "qc_min_distance_factor": 0.85,
        "reuse_store": False,
    }
    parameters = {
        name: _signature_value(args, name, default)
        for name, default in defaults.items()
    }
    parameters["histoplus_model_path"] = model_identity
    parameters["histoplus_weight_identity"] = model_identity
    return {
        "schema": PROCESSING_SIGNATURE_SCHEMA,
        "slide_id": job.slide_id,
        "input": input_file_fingerprint(job.l0_path),
        "l2_input": processing_l2_fingerprint(job, args),
        "parameters": parameters,
    }


def processing_signature(job: SlideJob, args: argparse.Namespace) -> str:
    payload = processing_signature_payload(job, args)
    return processing_signature_from_payload(payload)


def processing_signature_from_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def summary_matches_requested_run(
    summary: dict[str, Any], job: SlideJob, args: argparse.Namespace
) -> bool:
    """Require an exact input/config signature; legacy summaries rerun safely."""
    existing = summary.get("processing_signature") if isinstance(summary, dict) else None
    return isinstance(existing, str) and existing == processing_signature(job, args)


def load_resume_summary(path: Path, logger: logging.Logger) -> dict[str, Any] | None:
    """Load a reusable completion marker, treating damaged/non-object JSON as incomplete."""

    try:
        candidate = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        logger.warning(
            "Resume mode: completion summary is unreadable and will be invalidated: %s (%s)",
            path,
            exc,
        )
        return None
    if not isinstance(candidate, dict):
        logger.warning(
            "Resume mode: completion summary is not a JSON object and will be invalidated: %s",
            path,
        )
        return None
    return candidate


def invalidate_completion_summary(path: Path, logger: logging.Logger) -> None:
    """Remove a stale completion marker before any slide work is attempted."""

    if not path.exists():
        return
    try:
        path.unlink()
    except OSError as exc:
        raise RuntimeError(f"Could not invalidate stale completion summary {path}: {exc}") from exc
    logger.info("Invalidated stale completion summary before rerun: %s", path)


def nonempty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def valid_json_artifact(path: Path) -> bool:
    if not nonempty_file(path):
        return False
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True
    except (OSError, RuntimeError, UnicodeError, json.JSONDecodeError):
        return False


JSON_INTEGRITY_SCHEMA = "json_artifact_integrity_v1"


def artifact_integrity_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.integrity.json")


def write_artifact_integrity(path: Path) -> Path:
    identity = weight_file_identity(path)
    integrity_path = artifact_integrity_path(path)
    write_json_atomic(
        integrity_path,
        {
            "schema": JSON_INTEGRITY_SCHEMA,
            "artifact": path.name,
            "size_bytes": identity["size_bytes"],
            "sha256": identity["sha256"],
        },
    )
    return integrity_path


def valid_integrity_checked_artifact(path: Path) -> bool:
    if not nonempty_file(path):
        return False
    integrity_path = artifact_integrity_path(path)
    try:
        payload = json.loads(integrity_path.read_text(encoding="utf-8"))
        identity = weight_file_identity(path)
        return (
            isinstance(payload, dict)
            and payload.get("schema") == JSON_INTEGRITY_SCHEMA
            and payload.get("artifact") == path.name
            and payload.get("size_bytes") == identity["size_bytes"]
            and payload.get("sha256") == identity["sha256"]
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False


def valid_csv_artifact(path: Path) -> bool:
    if not nonempty_file(path):
        return False
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8", newline="") as handle:
            header = next(csv.reader(handle), None)
        return bool(header and any(str(value).strip() for value in header))
    except (OSError, EOFError, UnicodeError, csv.Error):
        return False


def valid_npy_artifact(path: Path) -> bool:
    if not nonempty_file(path):
        return False
    try:
        with path.open("rb") as handle:
            return handle.read(6) == b"\x93NUMPY"
    except OSError:
        return False


def file_has_magic(path: Path, magic: bytes) -> bool:
    if not nonempty_file(path):
        return False
    try:
        with path.open("rb") as handle:
            return handle.read(len(magic)) == magic
    except OSError:
        return False


def resolve_slide_artifact_path(slide_out: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    return path if path.is_absolute() else slide_out / path


def valid_sampled_patch_report(slide_out: Path) -> bool:
    root = slide_out / "sampled_patches"
    manifest = root / "patch_manifest.csv"
    summary_path = root / "patch_summary.json"
    if not valid_csv_artifact(manifest) or not valid_json_artifact(summary_path):
        return False
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        count = int(summary.get("n_sampled_patches", 0))
    except (AttributeError, TypeError, ValueError, OSError, json.JSONDecodeError):
        return False
    if count <= 0:
        return False
    for patch_index in range(1, count + 1):
        patch_dir = root / f"patch_{patch_index:05d}"
        if not (
            nonempty_file(patch_dir / "rgb.tif")
            and file_has_magic(patch_dir / "rgb.png", b"\x89PNG\r\n\x1a\n")
            and valid_json_artifact(patch_dir / "metadata.json")
        ):
            return False
    return True


def valid_sampled_patch_collage(slide_out: Path) -> bool:
    root = slide_out / "sampled_patch_mosaic"
    summary_path = root / "patch_mosaic_summary.json"
    if not (
        valid_json_artifact(summary_path)
        and valid_csv_artifact(root / "patch_mosaic_mapping.csv")
        and nonempty_file(root / "patch_mosaic_flat.tif")
    ):
        return False
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        processing_path = resolve_slide_artifact_path(
            slide_out, summary.get("processing_l0_path")
        )
    except (AttributeError, OSError, json.JSONDecodeError):
        return False
    return processing_path is not None and nonempty_file(processing_path)


def valid_qc_patch_outputs(slide_out: Path) -> bool:
    root = slide_out / "qc_patches"
    manifest_path = root / "patch_manifest.csv"
    if not valid_csv_artifact(manifest_path):
        return False
    try:
        with manifest_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        patch_indices = [int(row["patch_index"]) for row in rows]
    except (OSError, UnicodeError, csv.Error, KeyError, TypeError, ValueError):
        return False
    if not patch_indices:
        return False
    return all(
        file_has_magic(root / f"patch_{index:03d}" / "rgb.png", b"\x89PNG\r\n\x1a\n")
        and file_has_magic(root / f"patch_{index:03d}" / "overlay.png", b"\x89PNG\r\n\x1a\n")
        and valid_csv_artifact(root / f"patch_{index:03d}" / "class_counts.csv")
        and valid_json_artifact(root / f"patch_{index:03d}" / "metadata.json")
        for index in patch_indices
    )


def expected_slide_store_path(
    args: argparse.Namespace, slide_out: Path, job: SlideJob
) -> Path:
    store_root = getattr(args, "store_root", None)
    base = Path(store_root) / job.slide_id if store_root is not None else slide_out / "working"
    return base / f"{job.base_stem}.zarr"


def valid_nonempty_directory(path: Path) -> bool:
    try:
        return path.is_dir() and any(
            child.is_file() and child.stat().st_size > 0 for child in path.rglob("*")
        )
    except OSError:
        return False


def slide_has_required_plot_exports(
    slide_out: Path,
    args: argparse.Namespace | None = None,
    job: SlideJob | None = None,
) -> bool:
    coordinate_name = (
        "cell_type_coordinates.csv"
        if args is not None and bool(getattr(args, "plain_csv", False))
        else "cell_type_coordinates.csv.gz"
    )
    core_checks = [
        valid_csv_artifact(slide_out / "cell_types" / "class_counts.csv"),
        valid_csv_artifact(slide_out / "cell_types" / coordinate_name),
        valid_npy_artifact(slide_out / "cell_types" / "cell_type_coordinates.npy"),
        file_has_magic(slide_out / "overlays" / "overview_with_zoom_box.png", b"\x89PNG\r\n\x1a\n"),
        file_has_magic(slide_out / "overlays" / "zoom_overlay_celltypes.png", b"\x89PNG\r\n\x1a\n"),
        file_has_magic(slide_out / "overlays" / "celltypes_overview_and_zoom.png", b"\x89PNG\r\n\x1a\n"),
        file_has_magic(slide_out / "overlays" / "celltypes_overview_and_zoom.pdf", b"%PDF-"),
        file_has_magic(slide_out / "paper_figures" / "celltypes_paper_figure.png", b"\x89PNG\r\n\x1a\n"),
        file_has_magic(slide_out / "paper_figures" / "celltypes_paper_figure.pdf", b"%PDF-"),
        file_has_magic(slide_out / "paper_figures" / "celltype_counts_barplot.png", b"\x89PNG\r\n\x1a\n"),
        file_has_magic(slide_out / "paper_figures" / "celltype_counts_barplot.pdf", b"%PDF-"),
        valid_csv_artifact(slide_out / "plotting_metadata" / "detected_cell_types.csv"),
        valid_json_artifact(slide_out / "plotting_metadata" / "detected_cell_types.json"),
        valid_json_artifact(slide_out / "plotting_metadata" / "cell_type_palette.json"),
        valid_json_artifact(slide_out / "summary" / "run_metadata.json"),
    ]
    if not all(core_checks):
        return False
    if args is None:
        return True
    if bool(getattr(args, "export_qupath", False)) and not valid_json_artifact(
        artifact_integrity_path(slide_out / "cell_types" / "cell_types_qupath.json")
    ):
        return False
    if bool(getattr(args, "export_qupath", False)) and not valid_integrity_checked_artifact(
        slide_out / "cell_types" / "cell_types_qupath.json"
    ):
        return False
    if bool(getattr(args, "save_geojson_like_json", False)) and not valid_integrity_checked_artifact(
        slide_out / "cell_types" / "cell_type_coordinates.json"
    ):
        return False
    if int(getattr(args, "qc_patch_count", 0)) > 0 and not valid_qc_patch_outputs(slide_out):
        return False
    if float(getattr(args, "percent_slide", 100.0)) < 100.0 and not valid_sampled_patch_report(slide_out):
        return False
    if getattr(args, "collage_grid", None) is not None and not valid_sampled_patch_collage(slide_out):
        return False
    if bool(getattr(args, "keep_store", False)):
        if job is None or not valid_nonempty_directory(
            expected_slide_store_path(args, slide_out, job)
        ):
            return False
    return True


def summary_matches_requested_sampling(summary: dict[str, Any], args: argparse.Namespace) -> bool:
    requested_percent = float(getattr(args, "percent_slide", 100.0))
    requested_seed = int(getattr(args, "patch_random_seed", 0))
    sampling = summary.get("tile_sampling") if isinstance(summary, dict) else None
    if not isinstance(sampling, dict):
        existing_percent = 100.0
        existing_seed = requested_seed
    else:
        existing_percent = float(sampling.get("percent_slide", 100.0))
        existing_seed = int(sampling.get("random_seed", requested_seed))
    requested_collage = getattr(args, "collage_grid", None)
    patch_sampling = summary.get("patch_sampling") if isinstance(summary, dict) else None
    existing_collage = patch_sampling.get("collage_grid") if isinstance(patch_sampling, dict) else None
    if requested_collage is not None:
        if existing_collage != int(requested_collage):
            return False
    elif existing_collage is not None:
        return False
    if not math.isclose(existing_percent, requested_percent, rel_tol=0.0, abs_tol=1e-9):
        return False
    if requested_percent < 100.0:
        return existing_seed == requested_seed
    return True


def sample_wsi_tiles(wsi: Any, args: argparse.Namespace, logger: logging.Logger, tile_key: str = "tiles") -> dict[str, Any]:
    percent = float(getattr(args, "percent_slide", 100.0))
    summary: dict[str, Any] = {
        "enabled": percent < 100.0,
        "percent_slide": percent,
        "random_seed": int(getattr(args, "patch_random_seed", 0)),
        "tile_key": tile_key,
        "n_tiles_total": None,
        "n_tiles_sampled": None,
    }
    if percent >= 100.0:
        return summary

    try:
        tiles = wsi.shapes[tile_key]
    except Exception as exc:
        raise KeyError(f"Could not retrieve tile table {tile_key!r} for --percent-slide sampling: {exc}") from exc

    n_total = int(len(tiles))
    summary["n_tiles_total"] = n_total
    if n_total == 0:
        summary["n_tiles_sampled"] = 0
        logger.warning("--percent-slide %.3f requested, but no tissue tiles were available.", percent)
        return summary

    n_keep = max(1, min(n_total, int(math.ceil(n_total * percent / 100.0))))
    summary["n_tiles_sampled"] = n_keep
    if n_keep >= n_total:
        logger.info("--percent-slide %.3f keeps all %d tissue tiles.", percent, n_total)
        return summary

    seed = int(getattr(args, "patch_random_seed", 0))
    sampled = tiles.sample(n=n_keep, random_state=seed).sort_index().reset_index(drop=True)
    try:
        from spatialdata.models import ShapesModel

        wsi.shapes[tile_key] = ShapesModel.parse(sampled)
    except Exception:
        wsi.shapes[tile_key] = sampled

    logger.info(
        "Random tile sampling enabled: percent_slide=%.3f total_tiles=%d sampled_tiles=%d seed=%d",
        percent,
        n_total,
        n_keep,
        seed,
    )
    return summary


def get_wsi_thumbnail_rgb(wsi: Any, fallback_slide: Any, max_dim: int) -> np.ndarray:
    # Try to retrieve the attached LazySlide thumbnail first.
    candidates: list[Any] = []
    for key in ["wsi_thumbnail", "thumbnail"]:
        try:
            candidates.append(wsi[key])
        except Exception:
            pass
        try:
            images = getattr(wsi, "images")
            if key in images:
                candidates.append(images[key])
        except Exception:
            pass

    for item in candidates:
        try:
            data = getattr(item, "data", item)
            arr = np.asarray(data)
            # DataArray often comes as (C, H, W)
            if arr.ndim == 3 and arr.shape[0] in {3, 4} and arr.shape[0] < arr.shape[-1]:
                arr = np.moveaxis(arr, 0, -1)
            if arr.ndim == 3 and arr.shape[-1] >= 3:
                arr = arr[..., :3]
                if arr.dtype != np.uint8:
                    if np.issubdtype(arr.dtype, np.floating):
                        arr = np.clip(arr, 0, 1) * 255.0
                    else:
                        arr = arr.astype(np.float32)
                        arr = 255.0 * (arr - arr.min()) / (arr.max() - arr.min() + 1e-8)
                    arr = arr.astype(np.uint8)
                return np.ascontiguousarray(arr)
        except Exception:
            continue

    thumb = fallback_slide.get_thumbnail((max_dim, max_dim)).convert("RGB")
    return np.asarray(thumb, dtype=np.uint8)


def geometry_bounds_table(gdf: pd.DataFrame) -> pd.DataFrame:
    try:
        bounds = gdf.geometry.bounds.copy()
        bounds.columns = ["minx", "miny", "maxx", "maxy"]
        return bounds
    except AttributeError:
        rows: list[tuple[float, float, float, float]] = []
        for geom in gdf["geometry"]:
            if geom is None or getattr(geom, "is_empty", False):
                rows.append((float("nan"), float("nan"), float("nan"), float("nan")))
            else:
                minx, miny, maxx, maxy = geom.bounds
                rows.append((float(minx), float(miny), float(maxx), float(maxy)))
        return pd.DataFrame(rows, columns=["minx", "miny", "maxx", "maxy"], index=gdf.index)


def geometry_to_coordinate_lists(geom: Any) -> list[np.ndarray]:
    """Return a list of Nx2 float arrays for polygon exteriors only."""
    if geom is None or geom.is_empty:
        return []
    geom_type = getattr(geom, "geom_type", "")
    if geom_type == "Polygon":
        coords = np.asarray(geom.exterior.coords, dtype=np.float32)
        return [coords]
    if geom_type == "MultiPolygon":
        out: list[np.ndarray] = []
        for part in geom.geoms:
            out.extend(geometry_to_coordinate_lists(part))
        return out
    if geom_type == "GeometryCollection":
        out: list[np.ndarray] = []
        for part in geom.geoms:
            out.extend(geometry_to_coordinate_lists(part))
        return out
    return []


def geometry_to_jsonable_coords(geom: Any) -> list[list[list[float]]]:
    return [coords.astype(float).tolist() for coords in geometry_to_coordinate_lists(geom)]


def build_export_dataframe(gdf: pd.DataFrame, logger: logging.Logger) -> pd.DataFrame:
    if gdf.empty:
        return pd.DataFrame(
            columns=[
                "cell_id",
                "class_id",
                "class_name",
                "centroid_x",
                "centroid_y",
                "bbox_x0",
                "bbox_y0",
                "bbox_x1",
                "bbox_y1",
                "polygon_coords_json",
                "geometry",
            ]
        )

    class_col = detect_class_column(gdf)
    class_id_col = detect_class_id_column(gdf)
    cell_id_col = detect_cell_id_column(gdf)

    if class_col is None and class_id_col is None:
        raise KeyError(
            "Could not detect a class column in the LazySlide/HistoPLUS output. "
            f"Available columns: {list(gdf.columns)}"
        )

    logger.info("Detected class column=%s class_id column=%s cell_id column=%s", class_col, class_id_col, cell_id_col)

    bounds = geometry_bounds_table(gdf)
    centroids = gdf.geometry.centroid

    class_names: list[str] = []
    class_ids: list[int] = []
    for idx in range(len(gdf)):
        raw_name = gdf.iloc[idx][class_col] if class_col is not None else None
        raw_id = gdf.iloc[idx][class_id_col] if class_id_col is not None else None
        if raw_name is not None and not (isinstance(raw_name, float) and not math.isfinite(raw_name)):
            cname, cid = canonical_class_name_and_id(raw_name)
            if cid < 0 and raw_id is not None:
                cname2, cid2 = canonical_class_name_and_id(raw_id)
                if cid2 >= 0:
                    cname, cid = cname2, cid2
        else:
            cname, cid = canonical_class_name_and_id(raw_id)
        class_names.append(cname)
        class_ids.append(cid)

    cell_ids: list[str] = []
    if cell_id_col is not None:
        cell_ids = [str(v) for v in gdf[cell_id_col].tolist()]
    else:
        cell_ids = [f"cell_{i+1:09d}" for i in range(len(gdf))]

    polygon_json = [json.dumps(geometry_to_jsonable_coords(geom), ensure_ascii=False) for geom in gdf.geometry]

    out = pd.DataFrame(
        {
            "cell_id": cell_ids,
            "class_id": class_ids,
            "class_name": class_names,
            "centroid_x": centroids.x.to_numpy(dtype=float),
            "centroid_y": centroids.y.to_numpy(dtype=float),
            "bbox_x0": bounds["minx"].to_numpy(dtype=float),
            "bbox_y0": bounds["miny"].to_numpy(dtype=float),
            "bbox_x1": bounds["maxx"].to_numpy(dtype=float),
            "bbox_y1": bounds["maxy"].to_numpy(dtype=float),
            "polygon_coords_json": polygon_json,
        }
    )
    out["geometry"] = gdf.geometry.values
    return out


def write_coordinates_csv(df: pd.DataFrame, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_df = df.drop(columns=["geometry", "polygon_coords_json"], errors="ignore").copy()
    if out_path.suffix == ".gz":
        with gzip.open(out_path, "wt", encoding="utf-8", newline="") as f:
            write_df.to_csv(f, index=False)
    else:
        write_df.to_csv(out_path, index=False)


def write_coordinates_npy(
    df: pd.DataFrame,
    out_path: Path,
    class_palette: Optional[dict[str, str]] = None,
    slide_id: Optional[str] = None,
    palette_version: str = OVERLAY_PALETTE_VERSION,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = len(df)
    polygon_obj = np.empty(n, dtype=object)
    for i, geom in enumerate(df["geometry"].tolist()):
        polygon_obj[i] = [coords.astype(np.float32) for coords in geometry_to_coordinate_lists(geom)]

    palette = class_palette or DEFAULT_CLASS_COLORS
    color_hex = np.asarray([palette.get(str(name), DEFAULT_CLASS_COLORS.get(str(name), "#CCCCCC")) for name in df["class_name"].tolist()], dtype=object)
    payload = {
        "schema_version": "cell_type_coordinates_v2",
        "slide_id": slide_id,
        "palette_version": palette_version,
        "class_palette": dict(palette),
        "cell_id": df["cell_id"].to_numpy(dtype=object),
        "class_id": df["class_id"].to_numpy(dtype=np.int32, copy=True),
        "class_name": df["class_name"].to_numpy(dtype=object),
        "class_color_hex": color_hex,
        "centroid_xy": df[["centroid_x", "centroid_y"]].to_numpy(dtype=np.float32, copy=True),
        "bbox_xyxy": df[["bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1"]].to_numpy(dtype=np.float32, copy=True),
        "polygon_xy": polygon_obj,
    }
    np.save(out_path, payload, allow_pickle=True)


def write_json_dump(df: pd.DataFrame, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        handle.write("[\n")
        first = True
        for row in df.itertuples(index=False):
            payload = {
                "cell_id": row.cell_id,
                "class_id": int(row.class_id),
                "class_name": row.class_name,
                "centroid_x": float(row.centroid_x),
                "centroid_y": float(row.centroid_y),
                "bbox_x0": float(row.bbox_x0),
                "bbox_y0": float(row.bbox_y0),
                "bbox_x1": float(row.bbox_x1),
                "bbox_y1": float(row.bbox_y1),
                "polygon_coords": json.loads(row.polygon_coords_json),
            }
            if not first:
                handle.write(",\n")
            json.dump(payload, handle, ensure_ascii=False)
            first = False
        handle.write("\n]\n")
    write_artifact_integrity(out_path)


def class_counts_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["class_id", "class_name", "count"])
    rows = (
        df.groupby(["class_id", "class_name"], dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values(["class_id", "class_name"], kind="stable")
        .reset_index(drop=True)
    )
    return rows


def build_detected_celltype_table(counts_df: pd.DataFrame, class_palette: dict[str, str]) -> pd.DataFrame:
    cols = ["class_id", "class_name", "count", "fraction", "color_hex"]
    if counts_df.empty:
        return pd.DataFrame(columns=cols)
    out = counts_df.copy()
    total = float(out["count"].sum()) if "count" in out.columns else 0.0
    out["fraction"] = out["count"].astype(float) / total if total > 0 else 0.0
    out["color_hex"] = [class_palette.get(str(name), DEFAULT_CLASS_COLORS.get(str(name), "#CCCCCC")) for name in out["class_name"].tolist()]
    return out[cols]


def write_plotting_metadata(
    out_dir: Path,
    slide_id: str,
    detected_df: pd.DataFrame,
    class_palette: dict[str, str],
    coord_npy_path: Path,
    tile_sampling_summary: dict[str, Any],
    patch_sampling_summary: dict[str, Any],
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    detected_csv = out_dir / "detected_cell_types.csv"
    detected_json = out_dir / "detected_cell_types.json"
    palette_json = out_dir / "cell_type_palette.json"
    detected_df.to_csv(detected_csv, index=False)
    detected_payload = detected_df.to_dict(orient="records")
    with detected_json.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "slide_id": slide_id,
                "palette_version": OVERLAY_PALETTE_VERSION,
                "coordinate_npy": relativize_output_paths(str(coord_npy_path), out_dir.parent),
                "tile_sampling": relativize_output_paths(tile_sampling_summary, out_dir.parent),
                "patch_sampling": relativize_output_paths(patch_sampling_summary, out_dir.parent),
                "detected_cell_types": detected_payload,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    with palette_json.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "slide_id": slide_id,
                "palette_version": OVERLAY_PALETTE_VERSION,
                "class_palette": class_palette,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    return {
        "detected_cell_types_csv": str(detected_csv),
        "detected_cell_types_json": str(detected_json),
        "cell_type_palette_json": str(palette_json),
    }


def choose_present_palette(df: pd.DataFrame) -> OrderedDict[str, str]:
    present = OrderedDict()
    seen = set()
    if df.empty:
        return present

    pairs = df[["class_id", "class_name"]].drop_duplicates().sort_values(["class_id", "class_name"], kind="stable")
    for row in pairs.itertuples(index=False):
        cid = int(row.class_id)
        cname = str(row.class_name)
        if cid == 0 and not cname:
            continue
        if cname in seen:
            continue
        seen.add(cname)
        if cid in HISTOPLUS_CLASS_INFO:
            present[cname] = HISTOPLUS_CLASS_INFO[cid][1]
        else:
            present[cname] = DEFAULT_CLASS_COLORS.get(cname, "#CCCCCC")
    return present


def choose_zoom_box(
    df: pd.DataFrame,
    slide_w: int,
    slide_h: int,
    manual_box: Optional[Sequence[int]],
    zoom_size: int,
) -> tuple[int, int, int, int]:
    if manual_box is not None:
        x0, y0, x1, y1 = [int(v) for v in manual_box]
        x0 = max(0, min(slide_w - 1, x0))
        y0 = max(0, min(slide_h - 1, y0))
        x1 = max(x0 + 1, min(slide_w, x1))
        y1 = max(y0 + 1, min(slide_h, y1))
        return x0, y0, x1, y1

    if df.empty:
        cx = slide_w // 2
        cy = slide_h // 2
    else:
        xs = df["centroid_x"].to_numpy(dtype=float)
        ys = df["centroid_y"].to_numpy(dtype=float)
        bx = np.floor(xs / float(zoom_size)).astype(np.int64)
        by = np.floor(ys / float(zoom_size)).astype(np.int64)
        keys = np.stack([bx, by], axis=1)
        uniq, counts = np.unique(keys, axis=0, return_counts=True)
        best = uniq[int(np.argmax(counts))]
        sel = (bx == best[0]) & (by == best[1])
        if np.any(sel):
            cx = int(round(float(np.median(xs[sel]))))
            cy = int(round(float(np.median(ys[sel]))))
        else:
            cx = int(round(float(np.median(xs))))
            cy = int(round(float(np.median(ys))))

    half = zoom_size // 2
    x0 = max(0, min(slide_w - zoom_size, cx - half))
    y0 = max(0, min(slide_h - zoom_size, cy - half))
    x1 = min(slide_w, x0 + zoom_size)
    y1 = min(slide_h, y0 + zoom_size)
    if x1 - x0 < zoom_size:
        x0 = max(0, x1 - zoom_size)
    if y1 - y0 < zoom_size:
        y0 = max(0, y1 - zoom_size)
    return int(x0), int(y0), int(x1), int(y1)


def choose_qc_patches(
    df: pd.DataFrame,
    slide_w: int,
    slide_h: int,
    patch_size: int,
    count: int,
    min_distance_factor: float,
) -> list[tuple[int, int, int, int]]:
    if count <= 0:
        return []
    if df.empty:
        x0 = max(0, (slide_w - patch_size) // 2)
        y0 = max(0, (slide_h - patch_size) // 2)
        return [(x0, y0, min(slide_w, x0 + patch_size), min(slide_h, y0 + patch_size))]

    xs = df["centroid_x"].to_numpy(dtype=float)
    ys = df["centroid_y"].to_numpy(dtype=float)
    bx = np.floor(xs / float(patch_size)).astype(np.int64)
    by = np.floor(ys / float(patch_size)).astype(np.int64)
    keys = np.stack([bx, by], axis=1)
    uniq, inverse, counts = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    order = np.argsort(-counts)

    selected: list[tuple[int, int, int, int]] = []
    centers: list[tuple[float, float]] = []
    min_d2 = (patch_size * float(min_distance_factor)) ** 2

    for idx in order:
        cell_sel = inverse == idx
        if not np.any(cell_sel):
            continue
        cx = float(np.median(xs[cell_sel]))
        cy = float(np.median(ys[cell_sel]))
        too_close = False
        for px, py in centers:
            dx = cx - px
            dy = cy - py
            if dx * dx + dy * dy < min_d2:
                too_close = True
                break
        if too_close:
            continue

        x0 = max(0, min(slide_w - patch_size, int(round(cx - patch_size / 2))))
        y0 = max(0, min(slide_h - patch_size, int(round(cy - patch_size / 2))))
        x1 = min(slide_w, x0 + patch_size)
        y1 = min(slide_h, y0 + patch_size)
        if x1 - x0 < patch_size:
            x0 = max(0, x1 - patch_size)
        if y1 - y0 < patch_size:
            y0 = max(0, y1 - patch_size)
        selected.append((int(x0), int(y0), int(x1), int(y1)))
        centers.append((cx, cy))
        if len(selected) >= count:
            break

    if not selected:
        return choose_qc_patches(pd.DataFrame(), slide_w, slide_h, patch_size, 1, min_distance_factor)
    return selected


def read_region_rgb(slide: Any, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
    w = max(1, int(x1 - x0))
    h = max(1, int(y1 - y0))
    canvas = Image.new("RGB", (w, h), color=(255, 255, 255))

    sx0 = max(0, int(x0))
    sy0 = max(0, int(y0))
    sx1 = min(int(slide.dimensions[0]), int(x1))
    sy1 = min(int(slide.dimensions[1]), int(y1))
    if sx1 > sx0 and sy1 > sy0:
        region = slide.read_region((sx0, sy0), 0, (sx1 - sx0, sy1 - sy0)).convert("RGB")
        canvas.paste(region, (sx0 - int(x0), sy0 - int(y0)))
    return np.asarray(canvas, dtype=np.uint8)


def subset_roi(df: pd.DataFrame, roi: tuple[int, int, int, int]) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    x0, y0, x1, y1 = roi
    sel = ~(
        (df["bbox_x1"].to_numpy(dtype=float) <= x0)
        | (df["bbox_x0"].to_numpy(dtype=float) >= x1)
        | (df["bbox_y1"].to_numpy(dtype=float) <= y0)
        | (df["bbox_y0"].to_numpy(dtype=float) >= y1)
    )
    return df.loc[sel].copy()


def maybe_cap_polygons(df: pd.DataFrame, max_polygons: int) -> pd.DataFrame:
    if max_polygons <= 0 or len(df) <= max_polygons:
        return df
    return df.iloc[:max_polygons].copy()


def render_celltype_overlay(
    base_rgb: np.ndarray,
    roi_df: pd.DataFrame,
    roi: tuple[int, int, int, int],
    alpha: float,
    class_palette: dict[str, str],
    logger: logging.Logger,
    overlay_style: str = "outline_centroid",
    outline_width: int = 2,
    halo_width: int = 4,
    marker_radius: int = 3,
    draw_order: str = "small-last",
) -> np.ndarray:
    if roi_df.empty:
        return base_rgb.copy()

    try:
        from shapely.geometry import box  # type: ignore
    except Exception as exc:
        raise RuntimeError("shapely is required for overlay rendering.") from exc

    style = str(overlay_style).strip().lower().replace("-", "_")
    if style not in {"filled", "outline", "centroid", "outline_centroid", "filled_outline"}:
        style = "outline_centroid"

    x0, y0, x1, y1 = roi
    roi_box = box(x0, y0, x1, y1)
    rgba = Image.fromarray(base_rgb, mode="RGB").convert("RGBA")
    overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")

    draw_fill = style in {"filled", "filled_outline"}
    draw_outline = style in {"filled", "filled_outline", "outline", "outline_centroid"}
    draw_centroid = style in {"centroid", "outline_centroid"}
    fill_alpha = int(round(255.0 * float(alpha))) if draw_fill else 0
    outline_width = max(1, int(outline_width))
    halo_width = max(0, int(halo_width))
    marker_radius = max(0, int(marker_radius))

    draw_df = roi_df
    order = str(draw_order).strip().lower()
    if order in {"small-last", "large-last"} and "geometry" in roi_df.columns:
        try:
            draw_df = roi_df.assign(_overlay_area=roi_df.geometry.area.astype(float)).sort_values(
                "_overlay_area",
                ascending=(order == "large-last"),
                kind="stable",
            )
        except Exception:
            draw_df = roi_df

    n_polygons = 0
    n_markers = 0
    for row in draw_df.itertuples(index=False):
        geom = getattr(row, "geometry")
        if geom is None or geom.is_empty:
            continue
        try:
            clipped = geom.intersection(roi_box)
        except Exception:
            clipped = geom
        if clipped is None or clipped.is_empty:
            continue

        cname = str(row.class_name)
        color = class_palette.get(cname, DEFAULT_CLASS_COLORS.get(cname, "#CCCCCC"))
        rgb = color_hex_to_rgb(color)
        fill = (*rgb, fill_alpha)
        outline = (*rgb, 255)
        halo = (0, 0, 0, 230)

        if draw_fill or draw_outline:
            for coords in geometry_to_coordinate_lists(clipped):
                local = coords.copy()
                local[:, 0] -= float(x0)
                local[:, 1] -= float(y0)
                xy = [tuple(map(float, pt)) for pt in local.tolist()]
                if len(xy) < 3:
                    continue
                if draw_fill:
                    draw.polygon(xy, fill=fill)
                if draw_outline:
                    closed = xy + [xy[0]]
                    if halo_width > 0:
                        draw.line(closed, fill=halo, width=outline_width + halo_width)
                    draw.line(closed, fill=outline, width=outline_width)
                n_polygons += 1

        if draw_centroid and marker_radius > 0:
            cx = getattr(row, "centroid_x", None)
            cy = getattr(row, "centroid_y", None)
            if cx is None or cy is None:
                try:
                    c = clipped.centroid
                    cx, cy = float(c.x), float(c.y)
                except Exception:
                    cx, cy = None, None
            if cx is not None and cy is not None:
                cx = float(cx)
                cy = float(cy)
                if x0 <= cx < x1 and y0 <= cy < y1:
                    lx = cx - float(x0)
                    ly = cy - float(y0)
                    r = float(marker_radius)
                    if halo_width > 0:
                        hr = r + max(1.0, float(halo_width) * 0.5)
                        draw.ellipse((lx - hr, ly - hr, lx + hr, ly + hr), fill=halo)
                    draw.ellipse((lx - r, ly - r, lx + r, ly + r), fill=(*rgb, 255))
                    n_markers += 1

    logger.info(
        "Rendered %d polygon(s) and %d centroid marker(s) into ROI %s using style=%s draw_order=%s halo_width=%d",
        n_polygons,
        n_markers,
        roi,
        style,
        order,
        halo_width,
    )
    out = Image.alpha_composite(rgba, overlay).convert("RGB")
    return np.asarray(out, dtype=np.uint8)

def save_rgb(path: Path, rgb: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.asarray(rgb, dtype=np.uint8)).save(path)


def format_scale_label(length_um: float) -> str:
    if length_um >= 1000.0 and abs(length_um / 1000.0 - round(length_um / 1000.0)) < 1e-6:
        return f"{int(round(length_um / 1000.0))} mm"
    if length_um >= 1000.0:
        return f"{length_um / 1000.0:.1f} mm"
    return f"{int(round(length_um))} um"


def choose_scale_bar_length(width_px: int, microns_per_pixel: float) -> tuple[int, str]:
    if width_px <= 0 or microns_per_pixel <= 0:
        return 0, ""
    target_um = max(float(width_px) * float(microns_per_pixel) * 0.20, float(microns_per_pixel))
    candidates = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]
    length_um = min(candidates, key=lambda value: abs(value - target_um))
    length_px = max(1, int(round(length_um / float(microns_per_pixel))))
    if length_px > max(1, int(width_px * 0.35)):
        length_px = max(1, int(width_px * 0.25))
        length_um = length_px * float(microns_per_pixel)
    return length_px, format_scale_label(float(length_um))


def add_scale_bar_to_rgb(rgb: np.ndarray, microns_per_pixel: float, margin_frac: float = 0.045) -> np.ndarray:
    arr = np.asarray(rgb, dtype=np.uint8)
    if arr.ndim != 3 or arr.shape[0] <= 0 or arr.shape[1] <= 0 or microns_per_pixel <= 0:
        return arr
    out = Image.fromarray(arr).convert("RGB")
    draw = ImageDraw.Draw(out)
    w, h = out.size
    bar_w, label = choose_scale_bar_length(w, float(microns_per_pixel))
    if bar_w <= 0:
        return np.asarray(out, dtype=np.uint8)
    margin = max(10, int(round(min(w, h) * margin_frac)))
    bar_h = max(3, int(round(h * 0.006)))
    x1 = w - margin
    x0 = max(margin, x1 - bar_w)
    y1 = h - margin
    y0 = max(margin, y1 - bar_h)
    outline_pad = max(2, bar_h)
    try:
        bbox = draw.textbbox((0, 0), label)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
    except Exception:
        text_w = len(label) * 7
        text_h = 10
    tx = int(round((x0 + x1 - text_w) / 2.0))
    tx = max(margin, min(tx, w - margin - text_w))
    ty = max(margin, y0 - text_h - 2 * outline_pad)
    draw.rectangle([min(x0, tx) - outline_pad, ty - outline_pad, max(x1, tx + text_w) + outline_pad, y1 + outline_pad], fill=(255, 255, 255))
    draw.rectangle([x0, y0, x1, y1], fill=(0, 0, 0))
    draw.text((tx, ty), label, fill=(0, 0, 0))
    return np.asarray(out, dtype=np.uint8)


def add_axis_scale_bar(ax: Any, image_width_px: int, image_height_px: int, microns_per_pixel: float) -> None:
    bar_w, label = choose_scale_bar_length(int(image_width_px), float(microns_per_pixel))
    if bar_w <= 0:
        return
    margin_x = max(8.0, float(image_width_px) * 0.045)
    margin_y = max(8.0, float(image_height_px) * 0.055)
    bar_h = max(2.0, float(image_height_px) * 0.008)
    x1 = float(image_width_px) - margin_x
    x0 = max(margin_x, x1 - float(bar_w))
    y1 = float(image_height_px) - margin_y
    y0 = y1 - bar_h
    ax.add_patch(Rectangle((x0 - bar_h, y0 - 2.8 * bar_h), (x1 - x0) + 2 * bar_h, 4.8 * bar_h, facecolor="white", edgecolor="none", zorder=20))
    ax.add_patch(Rectangle((x0, y0), x1 - x0, bar_h, facecolor="black", edgecolor="black", linewidth=0, zorder=21))
    ax.text((x0 + x1) / 2.0, y0 - 1.2 * bar_h, label, ha="center", va="bottom", fontsize=7, color="black", zorder=22)


def build_overview_with_box(
    thumb_rgb: np.ndarray,
    slide_w: int,
    slide_h: int,
    roi: tuple[int, int, int, int],
) -> np.ndarray:
    out = Image.fromarray(np.asarray(thumb_rgb, dtype=np.uint8)).convert("RGB")
    draw = ImageDraw.Draw(out)
    x0, y0, x1, y1 = roi
    tw, th = out.size
    sx = tw / float(slide_w)
    sy = th / float(slide_h)
    box_xy = [x0 * sx, y0 * sy, x1 * sx, y1 * sy]
    draw.rectangle(box_xy, outline=(0, 0, 0), width=4)
    draw.rectangle([box_xy[0] + 1, box_xy[1] + 1, box_xy[2] - 1, box_xy[3] - 1], outline=(255, 255, 255), width=2)
    return np.asarray(out, dtype=np.uint8)


def build_composite_figure(
    overview_rgb: np.ndarray,
    zoom_rgb: np.ndarray,
    roi: tuple[int, int, int, int],
    slide_w: int,
    slide_h: int,
    present_palette: OrderedDict[str, str],
    title: str,
    out_png: Path,
    out_pdf: Path,
    dpi: int,
    include_background: bool,
    mpp: float,
) -> None:
    x0, y0, x1, y1 = roi
    overview_mpp = float(mpp) * float(slide_w) / float(max(1, overview_rgb.shape[1]))
    overview_plot = add_scale_bar_to_rgb(overview_rgb, overview_mpp)
    zoom_plot = add_scale_bar_to_rgb(zoom_rgb, float(mpp))
    fig = plt.figure(figsize=(14.5, 5.7), constrained_layout=False)
    gs = fig.add_gridspec(1, 3, width_ratios=[0.62, 1.0, 1.0], wspace=0.18)
    ax_leg = fig.add_subplot(gs[0, 0])
    ax_main = fig.add_subplot(gs[0, 1])
    ax_zoom = fig.add_subplot(gs[0, 2])

    # Legend panel.
    ax_leg.axis("off")
    legend_handles: list[Patch] = []
    for cname, hex_color in present_palette.items():
        if cname == "Background" and not include_background:
            continue
        legend_handles.append(Patch(facecolor=hex_color, edgecolor=hex_color, label=cname))
    if legend_handles:
        ax_leg.legend(
            handles=legend_handles,
            loc="center left",
            frameon=False,
            fontsize=12,
            handlelength=0.8,
            handletextpad=0.4,
            borderpad=0.2,
        )

    # Main overview.
    ax_main.imshow(overview_plot, extent=[0, slide_w, slide_h, 0])
    ax_main.set_title("Overview", fontsize=13)
    ax_main.set_xlim(0, slide_w)
    ax_main.set_ylim(slide_h, 0)
    rect = Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor="black", linewidth=1.7)
    rect2 = Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor="white", linewidth=0.8)
    ax_main.add_patch(rect)
    ax_main.add_patch(rect2)

    # Zoom panel.
    ax_zoom.imshow(zoom_plot, extent=[x0, x1, y1, y0])
    ax_zoom.set_title("High-resolution zoom", fontsize=13)
    ax_zoom.set_xlim(x0, x1)
    ax_zoom.set_ylim(y1, y0)
    ax_zoom.xaxis.tick_top()

    # Connection lines.
    con1 = ConnectionPatch(
        xyA=(x1, y0), coordsA=ax_main.transData,
        xyB=(x0, y0), coordsB=ax_zoom.transData,
        color="0.35", lw=1.2,
    )
    con2 = ConnectionPatch(
        xyA=(x1, y1), coordsA=ax_main.transData,
        xyB=(x0, y1), coordsB=ax_zoom.transData,
        color="0.35", lw=1.2,
    )
    fig.add_artist(con1)
    fig.add_artist(con2)

    fig.suptitle(title, fontsize=14, y=0.98)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=dpi, bbox_inches="tight")
    fig.savefig(out_pdf, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def add_bar_count_labels(ax: Any, bars: Any, counts: Sequence[Any], fontsize: int = 7) -> None:
    if not counts:
        return
    max_count = max([float(c) for c in counts] + [1.0])
    ax.set_xlim(0, max_count * 1.16)
    for bar, count in zip(bars, counts):
        value = int(count)
        ax.text(
            float(bar.get_width()) + max_count * 0.015,
            float(bar.get_y()) + float(bar.get_height()) / 2.0,
            f"{value:,}",
            va="center",
            ha="left",
            fontsize=fontsize,
            color="black",
        )


def build_paper_celltype_figures(
    overview_rgb: np.ndarray,
    zoom_rgb: np.ndarray,
    detected_df: pd.DataFrame,
    slide_id: str,
    out_dir: Path,
    dpi: int,
    slide_w: int,
    mpp: float,
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paper_png = out_dir / "celltypes_paper_figure.png"
    paper_pdf = out_dir / "celltypes_paper_figure.pdf"
    counts_png = out_dir / "celltype_counts_barplot.png"
    counts_pdf = out_dir / "celltype_counts_barplot.pdf"
    overview_mpp = float(mpp) * float(slide_w) / float(max(1, overview_rgb.shape[1]))
    overview_plot = add_scale_bar_to_rgb(overview_rgb, overview_mpp)
    zoom_plot = add_scale_bar_to_rgb(zoom_rgb, float(mpp))

    with plt.rc_context({"font.size": 8, "axes.linewidth": 0.8, "pdf.fonttype": 42, "ps.fonttype": 42}):
        fig = plt.figure(figsize=(7.2, 3.0), constrained_layout=True)
        gs = fig.add_gridspec(1, 3, width_ratios=[1.0, 1.0, 0.85])
        ax0 = fig.add_subplot(gs[0, 0])
        ax1 = fig.add_subplot(gs[0, 1])
        ax2 = fig.add_subplot(gs[0, 2])
        ax0.imshow(overview_plot)
        ax0.set_title("Overview", fontsize=9)
        ax0.axis("off")
        ax1.imshow(zoom_plot)
        ax1.set_title("Cell types", fontsize=9)
        ax1.axis("off")
        plot_df = detected_df.sort_values("count", ascending=True).tail(12) if not detected_df.empty else detected_df
        if plot_df.empty:
            ax2.text(0.5, 0.5, "No cells", ha="center", va="center")
            ax2.set_axis_off()
        else:
            bars = ax2.barh(plot_df["class_name"], plot_df["count"], color=plot_df["color_hex"], edgecolor="black", linewidth=0.3)
            add_bar_count_labels(ax2, bars, plot_df["count"].tolist(), fontsize=7)
            ax2.set_xlabel("Cells", fontsize=8)
            ax2.tick_params(axis="both", labelsize=7)
            ax2.spines["top"].set_visible(False)
            ax2.spines["right"].set_visible(False)
        fig.suptitle(slide_id, fontsize=9)
        fig.savefig(paper_png, dpi=dpi, bbox_inches="tight")
        fig.savefig(paper_pdf, dpi=dpi, bbox_inches="tight")
        plt.close(fig)

        fig2, ax = plt.subplots(figsize=(3.6, max(1.8, 0.22 * max(1, len(detected_df)))))
        plot_df = detected_df.sort_values("count", ascending=True) if not detected_df.empty else detected_df
        if plot_df.empty:
            ax.text(0.5, 0.5, "No cells", ha="center", va="center")
            ax.set_axis_off()
        else:
            bars = ax.barh(plot_df["class_name"], plot_df["count"], color=plot_df["color_hex"], edgecolor="black", linewidth=0.3)
            add_bar_count_labels(ax, bars, plot_df["count"].tolist(), fontsize=7)
            ax.set_xlabel("Detected cells", fontsize=8)
            ax.tick_params(axis="both", labelsize=7)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
        fig2.savefig(counts_png, dpi=dpi, bbox_inches="tight")
        fig2.savefig(counts_pdf, dpi=dpi, bbox_inches="tight")
        plt.close(fig2)

    return {
        "paper_figure_png": str(paper_png),
        "paper_figure_pdf": str(paper_pdf),
        "celltype_counts_barplot_png": str(counts_png),
        "celltype_counts_barplot_pdf": str(counts_pdf),
    }


def export_qc_patches(
    slide: Any,
    df: pd.DataFrame,
    slide_w: int,
    slide_h: int,
    slide_out: Path,
    class_palette: dict[str, str],
    args: argparse.Namespace,
    logger: logging.Logger,
) -> list[dict[str, Any]]:
    if args.qc_patch_count <= 0:
        return []

    patch_root = slide_out / "qc_patches"
    patch_root.mkdir(parents=True, exist_ok=True)
    rois = choose_qc_patches(
        df=df,
        slide_w=slide_w,
        slide_h=slide_h,
        patch_size=int(args.qc_patch_size),
        count=int(args.qc_patch_count),
        min_distance_factor=float(args.qc_min_distance_factor),
    )

    manifest: list[dict[str, Any]] = []
    for idx, roi in enumerate(tqdm(rois, desc="Exporting QC patches", unit="patch", leave=False), start=1):
        x0, y0, x1, y1 = roi
        rgb = read_region_rgb(slide, x0, y0, x1, y1)
        roi_df = subset_roi(df, roi)
        overlay = render_celltype_overlay(
            base_rgb=rgb,
            roi_df=roi_df,
            roi=roi,
            alpha=float(args.overlay_alpha),
            class_palette=class_palette,
            logger=logger,
            overlay_style=args.overlay_style,
            outline_width=int(args.overlay_outline_width),
            halo_width=int(args.overlay_halo_width),
            marker_radius=int(args.cell_marker_radius),
            draw_order=str(args.overlay_draw_order),
        )
        patch_dir = patch_root / f"patch_{idx:03d}"
        patch_dir.mkdir(parents=True, exist_ok=True)
        rgb_path = patch_dir / "rgb.png"
        overlay_path = patch_dir / "overlay.png"
        save_rgb(rgb_path, add_scale_bar_to_rgb(rgb, float(getattr(args, "_resolved_slide_mpp", args.mpp))))
        save_rgb(overlay_path, add_scale_bar_to_rgb(overlay, float(getattr(args, "_resolved_slide_mpp", args.mpp))))

        counts = class_counts_table(roi_df)
        counts_path = patch_dir / "class_counts.csv"
        counts.to_csv(counts_path, index=False)

        row = {
            "patch_index": idx,
            "x0": int(x0),
            "y0": int(y0),
            "x1": int(x1),
            "y1": int(y1),
            "n_cells": int(len(roi_df)),
            "rgb_path": str(rgb_path),
            "overlay_path": str(overlay_path),
            "class_counts_path": str(counts_path),
        }
        write_json(patch_dir / "metadata.json", row)
        manifest.append(row)

    pd.DataFrame(manifest).to_csv(patch_root / "patch_manifest.csv", index=False)
    return manifest


def export_qupath_annotations(zs: Any, wsi: Any, class_col: str, class_palette: dict[str, str], out_path: Path, logger: logging.Logger) -> None:
    try:
        zs.io.export_annotations(
            wsi,
            key="cell_types",
            classes=class_col,
            colors=class_palette,
            format="qupath",
            file=str(out_path),
        )
        logger.info("Saved QuPath annotations: %s", out_path)
    except Exception as exc:
        raise RuntimeError(f"Requested QuPath export failed for {out_path}: {exc}") from exc
    if not nonempty_file(out_path):
        raise RuntimeError(
            f"Requested QuPath export did not produce a nonempty file: {out_path}"
        )
    write_artifact_integrity(out_path)


# ----------------------------- automatic ASlide export helper -----------------------------


def locate_aslide_setup_script() -> Optional[Path]:
    candidates: list[Path] = []
    env_aslide_path = os.getenv("ASLIDE_PATH")
    if env_aslide_path:
        env_path = Path(env_aslide_path)
        if env_path.is_dir():
            candidates.append(env_path / "setup_env.sh")
        elif env_path.name == "setup_env.sh":
            candidates.append(env_path)

    try:
        for root in site.getsitepackages():
            candidates.append(Path(root) / "Aslide" / "setup_env.sh")
    except Exception:
        pass
    try:
        user_site = site.getusersitepackages()
        if user_site:
            candidates.append(Path(user_site) / "Aslide" / "setup_env.sh")
    except Exception:
        pass

    for lib_root in [Path(sys.prefix) / "lib", Path(sys.prefix) / "Lib"]:
        if not lib_root.exists():
            continue
        for pat in ["python*/site-packages/Aslide/setup_env.sh", "python*/dist-packages/Aslide/setup_env.sh"]:
            for match in lib_root.glob(pat):
                candidates.append(match)

    seen: set[Path] = set()
    for cand in candidates:
        try:
            cand = cand.resolve()
        except Exception:
            cand = cand.expanduser()
        if cand in seen:
            continue
        seen.add(cand)
        if cand.exists() and cand.is_file():
            return cand
    return None


def maybe_apply_aslide_setup_env(logger: Optional[logging.Logger] = None) -> bool:
    script = locate_aslide_setup_script()
    if script is None:
        return False
    cmd = [
        "bash",
        "-lc",
        f"source {shlex.quote(str(script))} >/dev/null 2>&1 && env -0",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        if logger is not None:
            logger.debug("Unable to source ASlide setup script %s: %s", script, proc.stderr.decode(errors="ignore"))
        return False
    try:
        for item in proc.stdout.split(b"\0"):
            if not item or b"=" not in item:
                continue
            key, value = item.split(b"=", 1)
            os.environ[key.decode(errors="ignore")] = value.decode(errors="ignore")
    except Exception:
        return False
    if logger is not None:
        logger.debug("Applied ASlide runtime environment from %s", script)
    return True


def ensure_aslide_slide_class(logger: Optional[logging.Logger] = None) -> Any:
    try:
        from Aslide import Slide  # type: ignore
        return Slide
    except Exception:
        maybe_apply_aslide_setup_env(logger)
        try:
            from Aslide import Slide  # type: ignore
            return Slide
        except Exception as exc:
            raise RuntimeError(
                "ASlide is not importable in the current environment. Install Aslide in the chosen export environment "
                "and make sure its runtime setup_env.sh can be sourced."
            ) from exc


def discover_raw_sources(raw_root: Path, include: str, exclude: str, extensions: Sequence[str], logger: logging.Logger, limit_dir: Optional[Path] = None, ignore_include: bool = False) -> list[RawSlideSource]:
    wanted_exts = normalized_extensions(extensions)
    limit_dir = limit_dir.expanduser().resolve() if limit_dir is not None else None
    sources: list[RawSlideSource] = []
    seen: set[Path] = set()
    for path in sorted(raw_root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in wanted_exts:
            continue
        if limit_dir is not None and not path_is_relative_to(path.parent, limit_dir):
            continue
        if path in seen:
            continue
        seen.add(path)
        rel_parent = path.parent.relative_to(raw_root)
        base_stem = path.stem
        slide_id = slugify(str(rel_parent / base_stem))
        if not ignore_include and not fnmatch(slide_id, include):
            continue
        if exclude and fnmatch(slide_id, exclude):
            continue
        sources.append(RawSlideSource(source_path=path, relative_parent=rel_parent, base_stem=base_stem, slide_id=slide_id))

    logger.info("Discovered %d raw slide(s) for automatic export.", len(sources))
    if not sources:
        logger.warning("No raw .mds/.mdsx slides matched under %s", raw_root)
    return sources


def iter_aslide_export_tiles(slide: Any, level: int, tile_size: int, fill_value: int = 255) -> Iterator[np.ndarray]:
    width, height = slide.level_dimensions[level]
    downsample = float(slide.level_downsamples[level])
    tiles_x = math.ceil(width / tile_size)
    tiles_y = math.ceil(height / tile_size)

    for ty in range(tiles_y):
        for tx in range(tiles_x):
            x = tx * tile_size
            y = ty * tile_size
            rw = min(tile_size, width - x)
            rh = min(tile_size, height - y)
            x0 = int(round(x * downsample))
            y0 = int(round(y * downsample))
            region = slide.read_region((x0, y0), level, (rw, rh))
            if not isinstance(region, Image.Image):
                region = Image.fromarray(np.asarray(region))
            if region.mode != "RGB":
                region = region.convert("RGB")
            arr = np.asarray(region, dtype=np.uint8)
            if arr.shape[0] != tile_size or arr.shape[1] != tile_size:
                padded = np.empty((tile_size, tile_size, 3), dtype=np.uint8)
                padded[:] = fill_value
                padded[: arr.shape[0], : arr.shape[1], :] = arr
                arr = padded
            yield arr


def _compression_kwargs_for_export(args: argparse.Namespace) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    comp = str(args.export_compression).strip().lower()
    if comp in {"none", "no", "uncompressed"}:
        return None, None
    if comp in {"deflate", "zlib"}:
        return "deflate", {"level": int(args.export_compression_level)}
    return comp, None


def export_single_raw_level(source: RawSlideSource, level: int, output_path: Path, args: argparse.Namespace, logger: logging.Logger) -> tuple[str, Optional[str]]:
    if output_path.exists() and not bool(args.overwrite_export):
        if not bool(args.quiet_export):
            logger.info("SKIP existing export: %s", output_path)
        return "skipped_existing", None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    compression, compressionargs = _compression_kwargs_for_export(args)
    Slide = ensure_aslide_slide_class(logger)

    try:
        slide = Slide(str(source.source_path))
    except Exception as exc:
        msg = f"UnsupportedFormat or reading failure: {source.source_path}: {exc}"
        logger.error(msg)
        return "open_failed", msg

    try:
        with slide:
            if level < 0 or level >= int(slide.level_count):
                msg = (
                    f"Requested export level L{level} not available for {source.source_path}. "
                    f"Slide has levels 0..{int(slide.level_count) - 1}."
                )
                logger.warning(msg)
                return "missing_level", msg

            width, height = slide.level_dimensions[level]
            if not bool(args.quiet_export):
                logger.info(
                    "EXPORT | slide=%s | level=L%d | dims=%dx%d | out=%s",
                    source.slide_id,
                    int(level),
                    int(width),
                    int(height),
                    output_path,
                )
            tifffile.imwrite(
                str(output_path),
                data=iter_aslide_export_tiles(slide, int(level), int(args.export_tile), fill_value=255),
                shape=(int(height), int(width), 3),
                dtype=np.uint8,
                tile=(int(args.export_tile), int(args.export_tile)),
                photometric="rgb",
                planarconfig="contig",
                compression=compression,
                compressionargs=compressionargs,
                bigtiff=True,
                metadata=None,
                maxworkers=None,
            )
    except Exception as exc:
        try:
            if output_path.exists():
                output_path.unlink()
        except Exception:
            pass
        logger.exception("Automatic export failed for %s", source.source_path)
        return "export_failed", str(exc)

    logger.info("DONE export: %s", output_path)
    return "exported", None


def run_inprocess_aslide_export(args: argparse.Namespace, logger: logging.Logger) -> list[dict[str, Any]]:
    if args.raw_root is None or args.export_root is None:
        raise RuntimeError("Automatic export requires resolved raw_root and export_root.")
    if not args.raw_root.exists():
        raise FileNotFoundError(f"Raw target folder not found: {args.raw_root}")

    sources = discover_raw_sources(args.raw_root, args.include, args.exclude, args.raw_extensions, logger, limit_dir=getattr(args, "raw_source_limit_dir", None), ignore_include=bool(getattr(args, "raw_source_limit_dir", None)))
    if not sources:
        raise RuntimeError(f"No raw slides found under {args.raw_root}")

    rows: list[dict[str, Any]] = []
    for source in sources:
        for level in args.export_levels:
            out_dir = args.export_root / source.relative_parent
            out_path = out_dir / f"{source.base_stem}_L{int(level)}_rgb.tif"
            status, error = export_single_raw_level(source, int(level), out_path, args, logger)
            rows.append({
                "slide_id": source.slide_id,
                "source_path": str(source.source_path),
                "relative_parent": str(source.relative_parent),
                "level": int(level),
                "output_path": str(out_path),
                "status": status,
                "error_message": error or "",
            })

    args.export_root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(args.export_root / "export_manifest.csv", index=False)
    ok = sum(1 for row in rows if row["status"] in {"exported", "skipped_existing"})
    logger.info("Automatic ASlide export finished. ok_or_skipped=%d total_targets=%d", ok, len(rows))
    return rows


def aslide_available_here(logger: Optional[logging.Logger] = None) -> bool:
    try:
        ensure_aslide_slide_class(logger)
        return True
    except Exception:
        return False


def resolve_export_python_command(args: argparse.Namespace) -> list[str]:
    if args.export_python is not None:
        return [str(args.export_python)]

    env_candidates = [
        os.getenv("PATHOLOGY_AI_PYTHON"),
        os.getenv("EXPORT_PYTHON"),
    ]
    for cand in env_candidates:
        if cand and Path(cand).exists():
            return [str(Path(cand).expanduser().resolve())]

    common_candidates = [
        Path.home() / "anaconda3" / "envs" / str(args.export_env_name) / "bin" / "python",
        Path("/opt/conda/envs") / str(args.export_env_name) / "bin" / "python",
        Path(sys.prefix).parent / str(args.export_env_name) / "bin" / "python",
    ]
    for cand in common_candidates:
        if cand.exists():
            return [str(cand.resolve())]

    conda_bin = shutil.which("conda")
    if conda_bin:
        return [conda_bin, "run", "--no-capture-output", "-n", str(args.export_env_name), "python"]

    raise RuntimeError(
        "Could not resolve a Python interpreter for the automatic ASlide export helper. "
        "Use --export-python or make `conda run -n <env>` available."
    )


def run_export_helper_subprocess(args: argparse.Namespace, logger: logging.Logger) -> None:
    script_path = Path(__file__).resolve()
    cmd = resolve_export_python_command(args) + [
        str(script_path),
        "--internal-export-only",
        "--raw-root",
        str(args.raw_root),
        "--export-root",
        str(args.export_root),
        "--include",
        str(args.include),
        "--log-level",
        str(args.log_level),
        "--export-tile",
        str(int(args.export_tile)),
        "--export-compression",
        str(args.export_compression),
        "--export-compression-level",
        str(int(args.export_compression_level)),
    ]
    if args.exclude:
        cmd.extend(["--exclude", str(args.exclude)])
    if args.overwrite_export:
        cmd.append("--overwrite-export")
    if args.quiet_export:
        cmd.append("--quiet-export")
    if getattr(args, "raw_source_limit_dir", None) is not None:
        cmd.extend(["--raw-source-limit-dir", str(args.raw_source_limit_dir)])
    if args.export_levels:
        cmd.append("--export-levels")
        cmd.extend([str(int(x)) for x in args.export_levels])
    if args.raw_extensions:
        cmd.append("--raw-extensions")
        cmd.extend([str(x) for x in args.raw_extensions])

    logger.info("Re-invoking this script for ASlide export via: %s", " ".join(shlex.quote(part) for part in cmd))
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"Automatic ASlide export helper failed with exit code {proc.returncode}.")


def ensure_exports_ready(args: argparse.Namespace, logger: logging.Logger) -> None:
    if args.target_folder is None or not bool(args.auto_export_missing):
        return
    if args.raw_root is None or args.export_root is None:
        raise RuntimeError("--target-folder mode did not resolve raw/export roots correctly.")
    if not args.raw_root.exists():
        raise FileNotFoundError(f"Target folder not found: {args.raw_root}")

    logger.info("Target-folder mode enabled.")
    logger.info("Raw target folder=%s", args.raw_root)
    if getattr(args, "raw_source_limit_dir", None) is not None:
        logger.info("Single raw WSI folder limit=%s", args.raw_source_limit_dir)
    logger.info("Derived export root=%s", args.export_root)
    if args.convert_to_pyramidal and args.pyramidal_root is not None:
        logger.info("Derived pyramidal root=%s", args.pyramidal_root)

    if args.dry_run:
        logger.info("DRY-RUN | would ensure exported TIFFs exist under %s", args.export_root)
        return

    if aslide_available_here(logger):
        logger.info("ASlide is importable in the current environment; running automatic export in-process.")
        run_inprocess_aslide_export(args, logger)
    else:
        logger.info(
            "ASlide is not importable in the current environment; using automatic export helper via %s.",
            args.export_python if args.export_python is not None else f"conda env '{args.export_env_name}'",
        )
        run_export_helper_subprocess(args, logger)


def run_internal_export_only(args: argparse.Namespace, logger: logging.Logger) -> None:
    logger.info("Internal automatic ASlide export helper starting.")
    logger.info("Raw root=%s", args.raw_root)
    logger.info("Export root=%s", args.export_root)
    run_inprocess_aslide_export(args, logger)


# ----------------------------- slide discovery -----------------------------


def discover_jobs(args: argparse.Namespace, logger: logging.Logger) -> list[SlideJob]:
    jobs: list[SlideJob] = []

    if args.input_slide is not None:
        p = args.input_slide
        if not p.exists():
            raise FileNotFoundError(p)
        base_stem = p.stem.replace("_L0_rgb", "")
        rel_parent = Path(p.parent.name)
        slide_id = args.slide_id or slugify(str(rel_parent / base_stem))
        if fnmatch(slide_id, args.include) and not (args.exclude and fnmatch(slide_id, args.exclude)):
            jobs.append(SlideJob(slide_id=slide_id, relative_parent=rel_parent, base_stem=base_stem, l0_path=p))
        return jobs

    assert args.export_root is not None
    single_rel = getattr(args, "_single_relative_parent", None)
    single_rel = Path(single_rel) if single_rel is not None else None
    for p in sorted(args.export_root.rglob("*_L0_rgb.tif")):
        rel_parent = p.parent.relative_to(args.export_root)
        if single_rel is not None and rel_parent != single_rel:
            continue
        base_stem = p.stem.replace("_L0_rgb", "")
        slide_id = slugify(str(rel_parent / base_stem))
        if single_rel is None and not fnmatch(slide_id, args.include):
            continue
        if args.exclude and fnmatch(slide_id, args.exclude):
            continue
        jobs.append(SlideJob(slide_id=slide_id, relative_parent=rel_parent, base_stem=base_stem, l0_path=p))

    logger.info("Discovered %d exported L0 slide(s).", len(jobs))
    for job in jobs:
        logger.info("JOB | %s | %s", job.slide_id, job.l0_path)
    return jobs



# ----------------------------- discovery report -----------------------------

def directory_tree_lines(root: Path, max_depth: int = 4, max_lines: int = 500) -> list[str]:
    root = root.expanduser().resolve()
    if not root.exists():
        return [f"{root} [missing]"]
    lines: list[str] = [str(root)]
    root_depth = len(root.parts)
    count = 1
    for current, dirs, files in os.walk(root):
        cur = Path(current)
        depth = len(cur.parts) - root_depth
        if depth >= max_depth:
            dirs[:] = []
        dirs[:] = sorted([d for d in dirs if not d.startswith(".")])
        files_sorted = sorted([f for f in files if not f.startswith(".")])
        indent = "  " * max(0, depth)
        for d in dirs:
            if count >= max_lines:
                lines.append("  ... [truncated]")
                return lines
            lines.append(f"{indent}├── {d}/")
            count += 1
        for f in files_sorted[:25]:
            if count >= max_lines:
                lines.append("  ... [truncated]")
                return lines
            lines.append(f"{indent}├── {f}")
            count += 1
        if len(files_sorted) > 25:
            lines.append(f"{indent}└── ... {len(files_sorted) - 25} more file(s)")
            count += 1
    return lines


def planned_export_path(args: argparse.Namespace, source: RawSlideSource, level: int) -> Optional[Path]:
    if getattr(args, "export_root", None) is None:
        return None
    return Path(args.export_root) / source.relative_parent / f"{source.base_stem}_L{int(level)}_rgb.tif"


def write_wsi_discovery_report(
    args: argparse.Namespace,
    jobs: Sequence[SlideJob],
    raw_sources: Sequence[RawSlideSource],
    logger: logging.Logger,
) -> None:
    base = main_output_base(args)
    base.mkdir(parents=True, exist_ok=True)
    stem = slugify(str(getattr(args, "discovery_report_name", "wsi_discovery_report") or "wsi_discovery_report"))
    txt_path = base / f"{stem}.txt"
    csv_path = base / f"{stem}_manifest.csv"
    json_path = base / f"{stem}_manifest.json"

    lines: list[str] = []
    lines.append("LazySlide + HistoPLUS WSI discovery report")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"Palette version: {OVERLAY_PALETTE_VERSION}")
    lines.append("")
    lines.append(f"raw_root: {getattr(args, 'raw_root', None)}")
    lines.append(f"single_slide_folder: {getattr(args, 'raw_source_limit_dir', None)}")
    lines.append(f"export_root: {getattr(args, 'export_root', None)}")
    lines.append(f"pyramidal_root: {getattr(args, 'pyramidal_root', None)}")
    lines.append(f"output_base: {base}")
    lines.append(f"include: {getattr(args, 'include', None)}")
    lines.append(f"exclude: {getattr(args, 'exclude', None)}")
    lines.append("")
    lines.append(f"raw WSI found: {len(raw_sources)}")
    lines.append(f"exported L0 WSI found: {len(jobs)}")
    lines.append("")
    if raw_sources:
        lines.append("Raw WSI sources:")
        for src in raw_sources:
            planned = [str(planned_export_path(args, src, lvl)) for lvl in getattr(args, "export_levels", [0, 2])]
            lines.append(f"  - {src.slide_id} | {src.source_path} | planned_exports={planned}")
        lines.append("")
    if jobs:
        lines.append("Processing jobs:")
        for job in jobs:
            out_dir = slide_output_dir(args, job)
            py_path = pyramidal_output_path(args, job, out_dir) if getattr(args, "convert_to_pyramidal", False) else None
            lines.append(f"  - {job.slide_id} | L0={job.l0_path} | output={out_dir} | pyramidal={py_path}")
        lines.append("")
    tree_root = getattr(args, "raw_source_limit_dir", None) or getattr(args, "raw_root", None) or getattr(args, "export_root", None)
    if tree_root is not None:
        lines.append("Directory structure:")
        lines.extend(directory_tree_lines(Path(tree_root), max_depth=int(getattr(args, "directory_tree_depth", 4))))

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    rows: list[dict[str, Any]] = []
    for src in raw_sources:
        for lvl in getattr(args, "export_levels", [0, 2]):
            rows.append({
                "kind": "raw_export_plan",
                "slide_id": src.slide_id,
                "relative_parent": str(src.relative_parent),
                "base_stem": src.base_stem,
                "source_path": str(src.source_path),
                "level": int(lvl),
                "planned_export_path": str(planned_export_path(args, src, int(lvl)) or ""),
                "l0_path": "",
                "output_dir": "",
            })
    for job in jobs:
        rows.append({
            "kind": "processing_job",
            "slide_id": job.slide_id,
            "relative_parent": str(job.relative_parent),
            "base_stem": job.base_stem,
            "source_path": "",
            "level": 0,
            "planned_export_path": "",
            "l0_path": str(job.l0_path),
            "output_dir": str(slide_output_dir(args, job)),
        })
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    write_json(json_path, {"raw_wsi_count": len(raw_sources), "exported_l0_count": len(jobs), "rows": rows})
    logger.info("Wrote WSI discovery report: %s", txt_path)


def collect_raw_sources_for_report(args: argparse.Namespace, logger: logging.Logger) -> list[RawSlideSource]:
    if getattr(args, "raw_root", None) is None or not Path(args.raw_root).exists():
        return []
    try:
        return discover_raw_sources(
            Path(args.raw_root),
            str(getattr(args, "include", "*")),
            str(getattr(args, "exclude", "")),
            getattr(args, "raw_extensions", [".mds", ".mdsx"]),
            logger,
            limit_dir=getattr(args, "raw_source_limit_dir", None),
            ignore_include=bool(getattr(args, "raw_source_limit_dir", None)),
        )
    except Exception as exc:
        logger.warning("Could not collect raw WSI sources for discovery report: %s", exc)
        return []

# ----------------------------- main slide processing -----------------------------


def resolve_device(device_arg: str, logger: Optional[logging.Logger] = None) -> str:
    raw = str(device_arg).strip()
    raw_lower = raw.lower()

    try:
        import torch  # type: ignore
    except Exception:
        torch = None  # type: ignore

    if raw_lower == "auto":
        if torch is not None and torch.cuda.is_available():
            return "cuda"
        return "cpu"

    if raw_lower in {"gpu", "cuda"} or raw_lower.startswith("cuda:"):
        requested = "cuda" if raw_lower == "gpu" else raw
        if torch is None:
            if logger is not None:
                logger.warning("CUDA was requested (%s) but PyTorch is not importable. Falling back to cpu.", raw)
            return "cpu"
        if not torch.cuda.is_available():
            if logger is not None:
                logger.warning("CUDA was requested (%s) but torch.cuda.is_available() is False. Falling back to cpu.", raw)
            return "cpu"
        return requested

    return raw


def build_histoplus_model(zs: Any, args: argparse.Namespace, logger: logging.Logger) -> tuple[Any, Path, str]:
    token = get_hf_token(args)
    resolved_weight, expected_filename = resolve_histoplus_weight_source(args, logger)

    kwargs: dict[str, Any] = {"magnification": str(args.histoplus_magnification).lower()}
    # Keep forwarding these arguments for future LazySlide versions that may honour
    # them directly, but also patch hf_hub_download for current versions.
    kwargs["model_path"] = str(resolved_weight)
    if token:
        kwargs["token"] = token

    with override_hf_hub_download(resolved_weight, expected_filename):
        model = zs.models.segmentation.HistoPLUS(**kwargs)
    return model, resolved_weight, expected_filename


def resolve_source_slide_mpp(
    wsi: Any, args: argparse.Namespace, logger: logging.Logger
) -> float:
    """Resolve physical source MPP without conflating it with model target MPP."""

    override = getattr(args, "slide_mpp", None)
    if override is not None:
        source_mpp = float(override)
        if hasattr(wsi, "set_mpp"):
            wsi.set_mpp(source_mpp)
        logger.info("Using explicit source slide MPP override: %.6f", source_mpp)
    else:
        properties = getattr(wsi, "properties", None)
        embedded = getattr(properties, "mpp", None)
        try:
            source_mpp = float(embedded)
        except (TypeError, ValueError):
            source_mpp = float("nan")
        if not math.isfinite(source_mpp) or source_mpp <= 0:
            raise RuntimeError(
                "Source TIFF has no reliable physical MPP metadata. Pass "
                "--slide-mpp with a verified source value; --mpp controls the "
                "requested model-tile resolution and is not a source-MPP fallback."
            )
        logger.info("Using embedded source slide MPP: %.6f", source_mpp)

    args._resolved_slide_mpp = source_mpp
    return source_mpp


def run_histoplus_cell_types(
    zs: Any,
    wsi: Any,
    histoplus_model: Any,
    args: argparse.Namespace,
    device: str,
    logger: logging.Logger,
) -> None:
    """Run cell typing and preserve a verified empty result from LazySlide 0.10.x."""

    try:
        zs.seg.cell_types(
            wsi,
            model=histoplus_model,
            tile_key="tiles",
            magnification=args.histoplus_magnification,
            batch_size=int(args.celltypes_batch_size),
            num_workers=int(args.num_workers),
            device=device,
            amp=bool(args.amp),
            pbar=True,
            key_added="cell_types",
        )
    except KeyError as exc:
        # LazySlide 0.10.x filters runner output with cells["class"]. A true
        # empty result currently lacks that column and raises after inference.
        if exc.args != ("class",):
            raise
        import geopandas as gpd
        from wsidata.io import add_shapes

        logger.warning(
            "HistoPLUS returned zero detected cells; recording an explicit "
            "zero-detection result (LazySlide empty-schema workaround)."
        )
        empty_cells = gpd.GeoDataFrame(
            {"class": pd.Series(dtype="object")},
            geometry=gpd.GeoSeries([], dtype="geometry"),
        )
        add_shapes(wsi, key="cell_types", shapes=empty_cells)


def slide_store_path(args: argparse.Namespace, slide_out: Path, job: SlideJob) -> Path:
    path = expected_slide_store_path(args, slide_out, job)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def run_slide(job: SlideJob, args: argparse.Namespace, root_logger: logging.Logger) -> dict[str, Any]:
    slide_out = slide_output_dir(args, job)
    if slide_out.exists() and args.overwrite:
        shutil.rmtree(slide_out)
    slide_out.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"lazyslide_histoplus.{job.slide_id}")
    logger.setLevel(root_logger.level)
    logger.handlers.clear()
    logger.propagate = True
    fh = logging.FileHandler(slide_out / "slide.log")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(fh)

    requested_signature_payload: dict[str, Any] | None = None
    requested_signature: str | None = None
    summary_path = slide_out / "summary" / "summary.json"
    if args.resume and summary_path.exists() and not args.overwrite:
        existing_summary = load_resume_summary(summary_path, logger)
        if existing_summary is not None:
            requested_signature_payload = processing_signature_payload(job, args)
            requested_signature = processing_signature_from_payload(
                requested_signature_payload
            )
            signature_matches = (
                existing_summary.get("processing_signature") == requested_signature
            )
            outputs_complete = slide_has_required_plot_exports(slide_out, args, job)
            if signature_matches and outputs_complete:
                logger.info("Resume mode: using exact matching outputs for %s", job.slide_id)
                return existing_summary
            if signature_matches:
                logger.info(
                    "Resume mode: existing outputs are incomplete; rerunning %s", job.slide_id
                )
            else:
                logger.info(
                    "Resume mode: input or processing parameters changed (or legacy metadata is incomplete); rerunning %s",
                    job.slide_id,
                )
        else:
            logger.info(
                "Resume mode: completion metadata is invalid; rerunning %s",
                job.slide_id,
            )


    for name in ["overlays", "cell_types", "summary", "qc_patches", "working"]:
        (slide_out / name).mkdir(parents=True, exist_ok=True)

    logger.info("Processing %s", job.slide_id)
    logger.info("L0 slide: %s", job.l0_path)

    if args.dry_run:
        return {"slide_id": job.slide_id, "status": "dry_run"}

    if requested_signature_payload is None or requested_signature is None:
        requested_signature_payload = processing_signature_payload(job, args)
        requested_signature = processing_signature_from_payload(
            requested_signature_payload
        )

    # summary.json is the completion marker. Never leave an old matching marker
    # in place while a rerun is in progress, or a later --resume could accept a
    # partially rewritten output tree after this attempt fails.
    invalidate_completion_summary(summary_path, logger)

    # Runtime imports may themselves fail (for example, a missing optional
    # dependency). Load them only after the stale completion marker is gone;
    # an exact resume does not need the inference stack at all.
    zs, open_wsi, _shape_types, TiffSlide = ensure_importable()

    patch_records: list[PatchRecord] = []
    patch_sampling_summary: dict[str, Any] = export_sampled_patch_report(job.l0_path, slide_out, args, logger)
    if sampled_patch_mode_enabled(args):
        sampled_patch_report_summary = patch_sampling_summary
        processing_l0_path, patch_sampling_summary, patch_records = build_sampled_patch_processing_slide(job, slide_out, args, logger)
        patch_sampling_summary["sampled_patch_report"] = sampled_patch_report_summary
        pyramidal_summary = {
            "source_l0_path": str(job.l0_path),
            "convert_to_pyramidal": False,
            "converted": False,
            "processing_l0_path": str(processing_l0_path),
            "backend": "sampled_patch_mosaic",
            "sampled_patch_mode": True,
        }
    else:
        processing_l0_path, pyramidal_summary = ensure_pyramidal_processing_slide(job, slide_out, args, logger)
    logger.info("Processing slide path: %s", processing_l0_path)

    device = resolve_device(args.device, logger=logger)
    logger.info("Resolved device=%s", device)

    effective_tile_px = resolve_histoplus_tile_px(int(args.tile_px), logger=logger)

    store_path = slide_store_path(args, slide_out, job)
    if not bool(getattr(args, "reuse_store", False)) and store_path.exists():
        logger.info("Removing previous WSIData store before fresh run: %s", store_path)
        safe_remove_path(store_path)
    logger.info("WSIData store=%s", store_path)

    with timed_stage(logger, "open_wsi"):
        wsi = open_wsi(
            str(processing_l0_path),
            store=str(store_path),
            reader="tiffslide",
            attach_thumbnail=True,
            thumbnail_size=int(args.thumbnail_size),
            save_thumbnail=True,
        )

    source_slide_mpp = resolve_source_slide_mpp(wsi, args, logger)

    logger.info("Running tissue detection.")
    zs.pp.find_tissues(wsi, level=args.tissue_level, key_added="tissues")

    logger.info(
        "Tiling tissues: requested_tile_px=%d effective_tile_px=%d overlap=%s background_fraction=%.3f target_mpp=%.4f source_slide_mpp=%.6f ops_level=%d",
        int(args.tile_px),
        int(effective_tile_px),
        args.overlap,
        args.background_fraction,
        args.mpp,
        source_slide_mpp,
        args.ops_level,
    )
    zs.pp.tile_tissues(
        wsi,
        int(effective_tile_px),
        overlap=float(args.overlap),
        background_fraction=float(args.background_fraction),
        mpp=float(args.mpp),
        slide_mpp=source_slide_mpp,
        ops_level=int(args.ops_level),
        tissue_key="tissues",
        key_added="tiles",
    )

    if patch_records:
        tile_sampling_summary = {
            "enabled": False,
            "reason": "sampled_patch_mosaic_already_applied",
            "percent_slide": float(args.percent_slide),
            "random_seed": int(args.patch_random_seed),
        }
    else:
        tile_sampling_summary = sample_wsi_tiles(wsi, args, logger, tile_key="tiles")

    if args.run_cells_stage:
        logger.info("Running zs.seg.cells with model=%s", args.cells_model)
        zs.seg.cells(
            wsi,
            model=args.cells_model,
            tile_key="tiles",
            batch_size=int(args.cells_batch_size),
            num_workers=int(args.num_workers),
            device=device,
            amp=bool(args.amp),
            pbar=True,
            key_added="cells",
        )

    histoplus_model, resolved_histoplus_weight, resolved_histoplus_filename = build_histoplus_model(zs, args, logger)
    logger.info(
        "Running zs.seg.cell_types with HistoPLUS magnification=%s weight_file=%s token=%s",
        args.histoplus_magnification,
        resolved_histoplus_weight,
        "set" if get_hf_token(args) else "unset",
    )
    _histoplus_t0 = time.perf_counter()
    run_histoplus_cell_types(zs, wsi, histoplus_model, args, device, logger)

    logger.info("HistoPLUS cell_types elapsed_sec=%.1f elapsed_min=%.2f", time.perf_counter() - _histoplus_t0, (time.perf_counter() - _histoplus_t0) / 60.0)

    gdf = get_wsi_shape_table(wsi, "cell_types")
    export_df = build_export_dataframe(gdf, logger)
    if patch_records:
        export_df = remap_patch_mosaic_dataframe(export_df, patch_records, logger)
    export_df = export_df.sort_values(["class_id", "centroid_y", "centroid_x"], kind="stable").reset_index(drop=True)

    # Exports: counts / coords.
    cell_dir = slide_out / "cell_types"
    counts_df = class_counts_table(export_df)
    counts_df.to_csv(cell_dir / "class_counts.csv", index=False)
    present_palette = choose_present_palette(export_df)
    detected_celltype_df = build_detected_celltype_table(counts_df, dict(present_palette))

    coord_csv_path = cell_dir / ("cell_type_coordinates.csv" if args.plain_csv else "cell_type_coordinates.csv.gz")
    coord_npy_path = cell_dir / "cell_type_coordinates.npy"
    write_coordinates_csv(export_df, coord_csv_path)
    write_coordinates_npy(export_df, coord_npy_path, class_palette=dict(present_palette), slide_id=job.slide_id)
    if args.save_geojson_like_json:
        write_json_dump(export_df, cell_dir / "cell_type_coordinates.json")

    plotting_metadata_paths: dict[str, str] = {}
    paper_figure_paths: dict[str, str] = {}

    visual_l0_path = job.l0_path if patch_records else processing_l0_path

    # Visual exports use original L0 coordinates in sampled patch mode.
    with TiffSlide(str(visual_l0_path)) as slide:
        slide_w, slide_h = [int(v) for v in slide.dimensions]
        logger.info("Slide dimensions: %dx%d", slide_w, slide_h)
        thumb_rgb = get_wsi_thumbnail_rgb(wsi, slide, int(args.thumbnail_size))
        roi = choose_zoom_box(
            df=export_df,
            slide_w=slide_w,
            slide_h=slide_h,
            manual_box=args.zoom_box,
            zoom_size=int(args.zoom_size),
        )
        zoom_rgb = read_region_rgb(slide, *roi)
        roi_df = subset_roi(export_df, roi)
        roi_df = maybe_cap_polygons(roi_df, int(args.zoom_max_polygons))

        present_palette = choose_present_palette(export_df)
        zoom_overlay = render_celltype_overlay(
            base_rgb=zoom_rgb,
            roi_df=roi_df,
            roi=roi,
            alpha=float(args.overlay_alpha),
            class_palette=dict(present_palette),
            logger=logger,
            overlay_style=args.overlay_style,
            outline_width=int(args.overlay_outline_width),
            halo_width=int(args.overlay_halo_width),
            marker_radius=int(args.cell_marker_radius),
            draw_order=str(args.overlay_draw_order),
        )
        overview_rgb = build_overview_with_box(thumb_rgb, slide_w, slide_h, roi)

        overlays_dir = slide_out / "overlays"
        overview_path = overlays_dir / "overview_with_zoom_box.png"
        zoom_path = overlays_dir / "zoom_overlay_celltypes.png"
        fig_png = overlays_dir / "celltypes_overview_and_zoom.png"
        fig_pdf = overlays_dir / "celltypes_overview_and_zoom.pdf"
        overview_export_mpp = source_slide_mpp * float(slide_w) / float(max(1, overview_rgb.shape[1]))
        save_rgb(overview_path, add_scale_bar_to_rgb(overview_rgb, overview_export_mpp))
        save_rgb(zoom_path, add_scale_bar_to_rgb(zoom_overlay, source_slide_mpp))
        build_composite_figure(
            overview_rgb=overview_rgb,
            zoom_rgb=zoom_overlay,
            roi=roi,
            slide_w=slide_w,
            slide_h=slide_h,
            present_palette=present_palette,
            title=f"{job.slide_id} | LazySlide + HistoPLUS cell types",
            out_png=fig_png,
            out_pdf=fig_pdf,
            dpi=int(args.figure_dpi),
            include_background=bool(args.legend_background),
            mpp=source_slide_mpp,
        )

        plotting_metadata_paths = write_plotting_metadata(
            out_dir=slide_out / "plotting_metadata",
            slide_id=job.slide_id,
            detected_df=detected_celltype_df,
            class_palette=dict(present_palette),
            coord_npy_path=coord_npy_path,
            tile_sampling_summary=tile_sampling_summary,
            patch_sampling_summary=patch_sampling_summary,
        )
        paper_figure_paths = build_paper_celltype_figures(
            overview_rgb=overview_rgb,
            zoom_rgb=zoom_overlay,
            detected_df=detected_celltype_df,
            slide_id=job.slide_id,
            out_dir=slide_out / "paper_figures",
            dpi=int(args.figure_dpi),
            slide_w=slide_w,
            mpp=source_slide_mpp,
        )

        patch_rows = export_qc_patches(
            slide=slide,
            df=export_df,
            slide_w=slide_w,
            slide_h=slide_h,
            slide_out=slide_out,
            class_palette=dict(present_palette),
            args=args,
            logger=logger,
        )

    # Optional QuPath export.
    if args.export_qupath:
        class_col = detect_class_column(gdf) or detect_class_id_column(gdf) or "class"
        export_qupath_annotations(
            zs=zs,
            wsi=wsi,
            class_col=class_col,
            class_palette=dict(present_palette),
            out_path=cell_dir / "cell_types_qupath.json",
            logger=logger,
        )

    # L2 drives sampled-patch selection/exports. Refuse to attribute this run
    # to an input that changed after its initial content fingerprint.
    final_l2_fingerprint = processing_l2_fingerprint(job, args)
    if final_l2_fingerprint != requested_signature_payload.get("l2_input"):
        raise RuntimeError(
            "Companion L2 changed while the slide was being processed; "
            "completion marker will not be published."
        )

    summary = {
        "slide_id": job.slide_id,
        "processing_signature_schema": PROCESSING_SIGNATURE_SCHEMA,
        "processing_signature": requested_signature,
        "input_fingerprint": input_file_fingerprint(job.l0_path),
        "l2_input_fingerprint": requested_signature_payload.get("l2_input"),
        "slide_path": str(job.l0_path),
        "processing_slide_path": str(processing_l0_path),
        "slide_width_px": int(slide_w),
        "slide_height_px": int(slide_h),
        "mpp": float(args.mpp),
        "target_mpp": float(args.mpp),
        "slide_mpp": source_slide_mpp,
        "device": device,
        "histoplus_weight_identity": current_histoplus_weight_identity(args),
        "tile_px_requested": int(args.tile_px),
        "tile_px_effective": int(effective_tile_px),
        "n_cells": int(len(export_df)),
        "zero_detections": bool(export_df.empty),
        "n_present_classes": int(len(counts_df)),
        "class_counts": {str(row.class_name): int(row.count) for row in counts_df.itertuples(index=False)},
        "zoom_box": {"x0": int(roi[0]), "y0": int(roi[1]), "x1": int(roi[2]), "y1": int(roi[3])},
        "pyramidal_conversion": pyramidal_summary,
        "tile_sampling": relativize_output_paths(tile_sampling_summary, slide_out),
        "patch_sampling": relativize_output_paths(patch_sampling_summary, slide_out),
        "outputs": {
            "coordinates_csv": str(coord_csv_path),
            "coordinates_npy": str(coord_npy_path),
            "coordinates_json": str(cell_dir / "cell_type_coordinates.json") if args.save_geojson_like_json else None,
            "class_counts_csv": str(cell_dir / "class_counts.csv"),
            "histoplus_weight_file": str(resolved_histoplus_weight),
            "pyramidal_processing_slide": relativize_output_paths(str(processing_l0_path), slide_out),
            "patch_mapping_csv": patch_sampling_summary.get("patch_mapping_csv"),
            "sampled_patch_manifest_csv": patch_sampling_summary.get("patch_manifest_csv"),
            "patch_mosaic_tif": patch_sampling_summary.get("processing_l0_path"),
            "overview_png": str(slide_out / "overlays" / "overview_with_zoom_box.png"),
            "zoom_overlay_png": str(slide_out / "overlays" / "zoom_overlay_celltypes.png"),
            "figure_png": str(slide_out / "overlays" / "celltypes_overview_and_zoom.png"),
            "figure_pdf": str(slide_out / "overlays" / "celltypes_overview_and_zoom.pdf"),
            "paper_figures": paper_figure_paths,
            "plotting_metadata": plotting_metadata_paths,
            "qc_patch_manifest": str(slide_out / "qc_patches" / "patch_manifest.csv") if patch_rows else None,
            "qupath_json": str(cell_dir / "cell_types_qupath.json") if args.export_qupath else None,
            "wsi_store": str(store_path) if args.keep_store else None,
        },
    }

    summary = relativize_output_paths(summary, slide_out)
    write_json(
        slide_out / "summary" / "run_metadata.json",
        {
            "target_mpp": float(args.mpp),
            "slide_mpp": source_slide_mpp,
            "slide_mpp_source": "override" if args.slide_mpp is not None else "embedded",
            "tile_px_requested": int(args.tile_px),
            "tile_px_effective": int(effective_tile_px),
            "histoplus_tile_divisor": int(HISTOPLUS_TILE_DIVISOR),
            "histoplus_default_tile_px": int(HISTOPLUS_DEFAULT_TILE_PX),
            "overlap": float(args.overlap),
            "background_fraction": float(args.background_fraction),
            "ops_level": int(args.ops_level),
            "tissue_level": args.tissue_level,
            "device": device,
            "amp": bool(args.amp),
            "cells_stage_enabled": bool(args.run_cells_stage),
            "cells_model": args.cells_model if args.run_cells_stage else None,
            "cells_batch_size": int(args.cells_batch_size),
            "celltypes_batch_size": int(args.celltypes_batch_size),
            "percent_slide": float(args.percent_slide),
            "patch_random_seed": int(args.patch_random_seed),
            "max_sampled_patches": int(args.max_sampled_patches),
            "collage": args.collage,
            "collage_grid": getattr(args, "collage_grid", None),
            "tile_sampling": relativize_output_paths(tile_sampling_summary, slide_out),
            "patch_sampling": relativize_output_paths(patch_sampling_summary, slide_out),
            "histoplus_magnification": args.histoplus_magnification,
            "histoplus_repo_id": args.histoplus_repo_id,
            "histoplus_revision": args.histoplus_revision,
            "histoplus_weight_filename": resolved_histoplus_filename,
            "histoplus_weight_file": str(resolved_histoplus_weight),
            "histoplus_weight_identity": current_histoplus_weight_identity(args),
            "pyramidal_processing_slide": relativize_output_paths(str(processing_l0_path), slide_out),
            "histoplus_model_path": str(args.histoplus_model_path) if args.histoplus_model_path is not None else None,
            "histoplus_force_download": bool(args.histoplus_force_download),
            "hf_token_supplied": bool(get_hf_token(args)),
            "zoom_box": list(roi),
            "zoom_size": int(args.zoom_size),
            "overlay_alpha": float(args.overlay_alpha),
            "overlay_style": str(args.overlay_style),
            "overlay_outline_width": int(args.overlay_outline_width),
            "overlay_halo_width": int(args.overlay_halo_width),
            "overlay_draw_order": str(args.overlay_draw_order),
            "cell_marker_radius": int(args.cell_marker_radius),
            "overlay_palette_version": OVERLAY_PALETTE_VERSION,
            "qc_patch_count": int(args.qc_patch_count),
            "qc_patch_size": int(args.qc_patch_size),
        },
    )

    if not args.keep_store:
        try:
            if store_path.exists():
                shutil.rmtree(store_path, ignore_errors=True)
        except Exception:
            pass

    if not slide_has_required_plot_exports(slide_out, args, job):
        raise RuntimeError(
            "One or more required core/requested optional artifacts are missing or invalid; "
            "completion marker will not be published."
        )

    # Publish the completion marker last. Atomic replacement prevents an
    # interrupted JSON write from masquerading as a completed slide.
    write_json_atomic(summary_path, summary)

    logger.info("Done: %s | n_cells=%d", job.slide_id, len(export_df))
    return summary


def prefetch_histoplus(args: argparse.Namespace, logger: logging.Logger) -> dict[str, Any]:
    resolved_weight, filename = resolve_histoplus_weight_source(args, logger)
    summary = {
        "status": "ok",
        "histoplus_repo_id": args.histoplus_repo_id,
        "histoplus_revision": args.histoplus_revision,
        "histoplus_magnification": args.histoplus_magnification,
        "histoplus_weight_filename": filename,
        "histoplus_weight_file": str(resolved_weight),
        "histoplus_weight_identity": current_histoplus_weight_identity(args),
        "hf_token_supplied": bool(get_hf_token(args)),
    }
    write_json(main_output_base(args) / "histoplus_prefetch_summary.json", summary)
    return summary


# ----------------------------- batch runner -----------------------------


def run_batch(jobs: Sequence[SlideJob], args: argparse.Namespace, logger: logging.Logger) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for job in tqdm(jobs, desc="Processing slides", unit="slide"):
        try:
            summaries.append(run_slide(job, args, logger))
        except Exception as exc:
            logger.exception("FAILED slide %s: %s", job.slide_id, exc)
            summaries.append({"slide_id": job.slide_id, "status": "failed", "error": str(exc)})

    if summaries:
        manifest_base = main_output_base(args)
        manifest_csv = manifest_base / "run_manifest.csv"
        manifest_json = manifest_base / "run_manifest.json"
        pd.DataFrame(summaries).to_csv(manifest_csv, index=False)
        write_json(manifest_json, {"slides": summaries})
    return summaries



# ----------------------------- main -----------------------------


def main() -> None:
    args = parse_args()
    logger = setup_logger(main_output_base(args), args.log_level)

    if getattr(args, "internal_export_only", False):
        run_internal_export_only(args, logger)
        return

    maybe_login_huggingface(args, logger)
    logger.info("Output base=%s", main_output_base(args))
    logger.info("Overlay palette version=%s", OVERLAY_PALETTE_VERSION)
    if args.target_folder is not None:
        logger.info("Target folder=%s", args.target_folder)
        if getattr(args, "raw_source_limit_dir", None) is not None:
            logger.info("Single raw WSI folder=%s", args.raw_source_limit_dir)
        logger.info("Derived export root=%s", args.export_root)
    elif args.export_root is not None:
        logger.info("Export root=%s", args.export_root)
    if args.input_slide is not None:
        logger.info("Input slide=%s", args.input_slide)
    if args.output is not None:
        logger.info("Single-slide output=%s", args.output)
    if args.convert_to_pyramidal:
        logger.info("Pyramidal conversion is enabled for input L0 TIFFs.")
        if args.pyramidal_root is not None:
            logger.info("Pyramidal cache root=%s", args.pyramidal_root)

    if args.prefetch_histoplus:
        summary = prefetch_histoplus(args, logger)
        logger.info("Prefetch complete. HistoPLUS weights ready at: %s", summary["histoplus_weight_file"])
        return

    ensure_exports_ready(args, logger)

    raw_sources_for_report = collect_raw_sources_for_report(args, logger)
    jobs = discover_jobs(args, logger)
    write_wsi_discovery_report(args, jobs, raw_sources_for_report, logger)
    if not jobs:
        if args.dry_run and raw_sources_for_report:
            logger.info("DRY-RUN | no exported L0 slides found yet, but %d raw WSI source(s) were planned for export. See discovery report.", len(raw_sources_for_report))
            return
        logger.error("No matching exported L0 slides found.")
        sys.exit(1)

    if args.dry_run:
        for job in jobs:
            logger.info("DRY-RUN | %s | %s", job.slide_id, job.l0_path)
        return

    # Fail fast on gated-model access before the first slide spends time on tissue tiling.
    prefetch_summary = prefetch_histoplus(args, logger)
    logger.info("Using HistoPLUS weights at: %s", prefetch_summary["histoplus_weight_file"])

    summaries = run_batch(jobs, args, logger)
    ok = sum(1 for row in summaries if row.get("status", "ok") != "failed")
    fail = len(summaries) - ok
    logger.info("Finished. success=%d failed=%d", ok, fail)
    if fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
