#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import warnings
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Patch, Rectangle
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFilter

try:
    from tiffslide import TiffSlide  # type: ignore
except Exception:
    TiffSlide = None


# ----------------------------- constants -----------------------------

CLASS_INFO: "OrderedDict[int, tuple[str, str]]" = OrderedDict([
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
])

NAME_TO_COLOR = {name: color for _cid, (name, color) in CLASS_INFO.items()}
ID_TO_NAME = {cid: name for cid, (name, _color) in CLASS_INFO.items()}
ID_TO_COLOR = {cid: color for cid, (_name, color) in CLASS_INFO.items()}

# Reserved extra colors for future unseen cell types in new slides.
RESERVED_NEW_TYPE_COLORS = ["#00BFC4", "#C77CFF", "#B79F00", "#F564E3"]

def _norm_class_name(x: Any) -> str:
    s = str(x).strip().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

CANONICAL_NAME_ALIASES = {
    _norm_class_name("Cancer cell"): "Cancer cell",
    _norm_class_name("Cancer cells"): "Cancer cell",
    _norm_class_name("Lymphocyte"): "Lymphocytes",
    _norm_class_name("Lymphocytes"): "Lymphocytes",
    _norm_class_name("Fibroblast"): "Fibroblasts",
    _norm_class_name("Fibroblasts"): "Fibroblasts",
    _norm_class_name("Plasmocyte"): "Plasmocytes",
    _norm_class_name("Plasmocytes"): "Plasmocytes",
    _norm_class_name("Plasma cell"): "Plasmocytes",
    _norm_class_name("Plasma cells"): "Plasmocytes",
    _norm_class_name("Eosinophil"): "Eosinophils",
    _norm_class_name("Eosinophils"): "Eosinophils",
    _norm_class_name("Neutrophil"): "Neutrophils",
    _norm_class_name("Neutrophils"): "Neutrophils",
    _norm_class_name("Macrophage"): "Macrophages",
    _norm_class_name("Macrophages"): "Macrophages",
    _norm_class_name("Muscle Cell"): "Muscle Cell",
    _norm_class_name("Muscle Cells"): "Muscle Cell",
    _norm_class_name("Smooth Muscle Cell"): "Muscle Cell",
    _norm_class_name("Smooth Muscle Cells"): "Muscle Cell",
    _norm_class_name("Endothelial Cell"): "Endothelial Cell",
    _norm_class_name("Endothelial Cells"): "Endothelial Cell",
    _norm_class_name("Red blood cell"): "Red blood cell",
    _norm_class_name("Red blood cells"): "Red blood cell",
    _norm_class_name("RBC"): "Red blood cell",
    _norm_class_name("Epithelial"): "Epithelial",
    _norm_class_name("Epithelial cell"): "Epithelial",
    _norm_class_name("Epithelial cells"): "Epithelial",
    _norm_class_name("Apoptotic Body"): "Apoptotic Body",
    _norm_class_name("Apoptotic Bodies"): "Apoptotic Body",
    _norm_class_name("Mitotic Figure"): "Mitotic Figures",
    _norm_class_name("Mitotic Figures"): "Mitotic Figures",
    _norm_class_name("Mitosis"): "Mitotic Figures",
    _norm_class_name("Mitoses"): "Mitotic Figures",
    _norm_class_name("Minor Stromal Cell"): "Minor Stromal Cell",
    _norm_class_name("Minor Stromal Cells"): "Minor Stromal Cell",
}

def canonicalize_class_name(x: Any) -> str:
    s = str(x).strip()
    if s == "" or s.lower() == "nan":
        return s
    return CANONICAL_NAME_ALIASES.get(_norm_class_name(s), s)

ALT_COLS = {
    "cell_id": ["cell_id", "instance_id", "object_id", "id"],
    "class_id": ["class_id", "class_idx", "label_id", "type_id", "cell_type_id"],
    "class_name": ["class_name", "class", "cell_type", "celltype", "label", "classification", "type", "name"],
    "centroid_x": ["centroid_x", "x", "center_x", "cx"],
    "centroid_y": ["centroid_y", "y", "center_y", "cy"],
    "bbox_x0": ["bbox_x0", "minx", "x0", "left"],
    "bbox_y0": ["bbox_y0", "miny", "y0", "top"],
    "bbox_x1": ["bbox_x1", "maxx", "x1", "right"],
    "bbox_y1": ["bbox_y1", "maxy", "y1", "bottom"],
}

# Plot styling tuned for better readability without clutter.
# The fonts are large enough for PDF viewing, but titles are kept short to avoid overlap.
FONT_SMALL = 11
FONT_MED = 13
FONT_LARGE = 15
FONT_XL = 16
LINE_THIN = 1.8
LINE_MED = 2.4
LINE_HEAVY = 4.2
GRID_ALPHA = 0.18

def set_axis_style(ax: Any) -> None:
    ax.tick_params(axis="both", labelsize=FONT_SMALL, width=LINE_THIN, length=5)
    for spine in ax.spines.values():
        spine.set_linewidth(LINE_THIN)


@dataclass
class SlidePaths:
    slide_dir: Path
    coords_csv: Path
    coords_npy: Optional[Path]
    summary_json: Optional[Path]
    slide_path: Optional[Path]
    outdir: Path


# ----------------------------- CLI -----------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description=(
            "Post-processing visualization for LazySlide + HistoPLUS outputs. "
            "It does not rerun HistoPLUS. It reads cell_type_coordinates.csv/.csv.gz, "
            "summary.json, and the pyramidal TIFF used by the original run."
        ),
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--slide-output-dir", type=Path, help="One LazySlide/HistoPLUS per-slide output directory, e.g. results/case_001")
    mode.add_argument("--output-root", type=Path, help="Batch mode: root containing multiple per-slide LazySlide/HistoPLUS output directories")

    p.add_argument("--include", default="*", help="Batch mode include filter over slide directory names")
    p.add_argument("--exclude", default="", help="Batch mode exclude filter over slide directory names")
    p.add_argument("--outdir", type=Path, default=None, help="Output directory. In batch mode this becomes a global root; per-slide outputs go under <outdir>/<slide_id>")
    p.add_argument("--slide", type=Path, default=None, help="Optional TIFF/BigTIFF path if summary.json cannot resolve the slide")
    p.add_argument("--coords-csv", type=Path, default=None, help="Optional explicit cell_type_coordinates.csv or .csv.gz path")
    p.add_argument("--coords-npy", type=Path, default=None, help="Optional explicit cell_type_coordinates.npy path")
    p.add_argument("--use-npy-polygons", action="store_true", help="Load cell_type_coordinates.npy for exact polygon-derived shape features in the embedding. This can be memory-heavy for >1M cells, so it is off by default.")

    p.add_argument("--mpp", type=float, default=0.5, help="Microns per pixel; used only for feature labels/area units")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--dpi", type=int, default=250)
    p.add_argument("--thumbnail-max-dim", type=int, default=4500)

    # Spatial report
    p.add_argument("--no-spatial-report", action="store_true")
    p.add_argument("--num-rois", type=int, default=9, help="Number of tissue square ROIs to select")
    p.add_argument("--roi-size", type=int, default=1200, help="Square ROI size in level-0 pixels")
    p.add_argument("--roi-grid-cols", type=int, default=3, help="Number of columns in the ROI page")
    p.add_argument("--roi-min-distance-factor", type=float, default=0.85, help="Minimum distance between selected ROI centers, as a fraction of ROI size")
    p.add_argument("--roi-score-diversity-weight", type=float, default=0.20, help="Higher values favor local class diversity during ROI selection")
    p.add_argument("--roi-score-rare-weight", type=float, default=0.35, help="Higher values favor areas enriched for globally rarer classes")
    p.add_argument("--max-cells-per-roi", type=int, default=900, help="Maximum cells plotted in each ROI overlay")
    p.add_argument("--min-class-cells-per-roi", type=int, default=25, help="Attempt to preserve at least this many cells per local class before thinning")
    p.add_argument("--min-distance-px", type=float, default=9.0, help="Approximate grid thinning distance inside ROI overlays")
    p.add_argument("--overview-max-cells", type=int, default=60000, help="Maximum cells in the full-slide overview scatter")
    p.add_argument("--point-size", type=float, default=9.0, help="Base cell marker size in ROI overlays")
    p.add_argument("--overview-point-size", type=float, default=1.0, help="Base cell marker size in the whole-slide overview scatter")
    p.add_argument("--point-alpha", type=float, default=0.88)
    p.add_argument("--draw-bbox", action="store_true", help="Draw approximate bbox outlines for sampled cells in ROI overlays; useful but can be cluttered")
    p.add_argument("--roi-detail-pages", action="store_true", help="Add one detailed page per ROI after the grid page")

    # Embedding report
    p.add_argument("--no-embedding-report", action="store_true")
    p.add_argument("--embedding-max-cells", type=int, default=60000)
    p.add_argument("--embedding-method", choices=["auto", "umap", "pca"], default="auto")
    p.add_argument("--umap-n-neighbors", type=int, default=30)
    p.add_argument("--umap-min-dist", type=float, default=0.12)
    p.add_argument("--embedding-point-size", type=float, default=1.7)
    p.add_argument("--embedding-alpha", type=float, default=0.68)
    p.add_argument("--label-umap-counts", dest="label_umap_counts", action="store_true", default=True, help="Label each UMAP/PCA class centroid with the total number of cells in that class")
    p.add_argument("--no-label-umap-counts", dest="label_umap_counts", action="store_false", help="Disable class-count labels at UMAP/PCA centroids")
    p.add_argument("--save-embedding-csv", action="store_true", default=True)
    p.add_argument("--no-save-embedding-csv", dest="save_embedding_csv", action="store_false")

    args = p.parse_args()
    if args.num_rois < 1:
        p.error("--num-rois must be >= 1")
    if args.roi_size < 64:
        p.error("--roi-size must be >= 64")
    if args.max_cells_per_roi < 10:
        p.error("--max-cells-per-roi must be >= 10")
    if args.embedding_max_cells < 100 and not args.no_embedding_report:
        p.error("--embedding-max-cells should be >= 100")

    matplotlib.rcParams.update({
        "font.size": FONT_MED,
        "font.weight": "regular",
        "axes.titlesize": FONT_LARGE,
        "axes.labelsize": FONT_MED,
        "axes.titleweight": "bold",
        "axes.labelweight": "bold",
        "xtick.labelsize": FONT_SMALL,
        "ytick.labelsize": FONT_SMALL,
        "legend.fontsize": FONT_SMALL,
        "axes.linewidth": LINE_THIN,
        "grid.linewidth": LINE_THIN,
        "lines.linewidth": LINE_MED,
        "patch.linewidth": LINE_THIN,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })
    return args


# ----------------------------- helpers -----------------------------

def log(msg: str) -> None:
    print(msg, flush=True)


def slugify(x: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(x)).strip("_")


def fnmatch(text: str, pattern: str) -> bool:
    import fnmatch as _fnmatch
    return _fnmatch.fnmatch(text, pattern)


def resolve_existing_path(path_like: Any) -> Optional[Path]:
    if not path_like:
        return None
    candidates = [str(path_like)]
    seen = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        p = Path(c).expanduser()
        try:
            p = p.resolve()
        except Exception:
            pass
        if p.exists():
            return p
    return None


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def find_summary(slide_dir: Path) -> Optional[Path]:
    for p in [slide_dir / "summary" / "summary.json", slide_dir / "summary.json"]:
        if p.exists():
            return p
    return None


def find_coords_csv(slide_dir: Path, explicit: Optional[Path] = None) -> Path:
    if explicit is not None:
        p = explicit.expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"coords CSV not found: {p}")
        return p
    candidates = [
        slide_dir / "cell_types" / "cell_type_coordinates.csv",
        slide_dir / "cell_types" / "cell_type_coordinates.csv.gz",
        slide_dir / "cell_type_coordinates.csv",
        slide_dir / "cell_type_coordinates.csv.gz",
    ]
    for p in candidates:
        if p.exists():
            return p
    found = sorted(slide_dir.rglob("cell_type_coordinates.csv")) + sorted(slide_dir.rglob("cell_type_coordinates.csv.gz"))
    if found:
        return found[0]
    raise FileNotFoundError(f"No cell_type_coordinates.csv/.csv.gz found under {slide_dir}")

def find_coords_npy(slide_dir: Path, explicit: Optional[Path] = None) -> Optional[Path]:
    if explicit is not None:
        p = explicit.expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"coords NPY not found: {p}")
        return p
    candidates = [
        slide_dir / "cell_types" / "cell_type_coordinates.npy",
        slide_dir / "cell_type_coordinates.npy",
    ]
    for p in candidates:
        if p.exists():
            return p
    found = sorted(slide_dir.rglob("cell_type_coordinates.npy"))
    return found[0] if found else None


def resolve_slide_path(slide_dir: Path, summary_path: Optional[Path], explicit_slide: Optional[Path]) -> Optional[Path]:
    if explicit_slide is not None:
        p = resolve_existing_path(explicit_slide)
        if p is None:
            raise FileNotFoundError(f"Explicit --slide does not exist: {explicit_slide}")
        return p
    if summary_path is None:
        return None
    summary = load_json(summary_path)
    keys = [
        summary.get("processing_slide_path"),
        summary.get("slide_path"),
        summary.get("outputs", {}).get("pyramidal_processing_slide") if isinstance(summary.get("outputs"), dict) else None,
    ]
    pyr = summary.get("pyramidal_conversion")
    if isinstance(pyr, dict):
        keys.append(pyr.get("processing_l0_path"))
        keys.append(pyr.get("source_l0_path"))
    for k in keys:
        p = resolve_existing_path(k)
        if p is not None:
            return p
    return None


def discover_slide_dirs(args: argparse.Namespace) -> list[SlidePaths]:
    if args.slide_output_dir is not None:
        slide_dirs = [args.slide_output_dir.expanduser().resolve()]
    else:
        root = args.output_root.expanduser().resolve()
        if not root.exists():
            raise FileNotFoundError(root)
        found = set()
        for pat in ["**/cell_types/cell_type_coordinates.csv", "**/cell_types/cell_type_coordinates.csv.gz"]:
            for p in root.glob(pat):
                found.add(p.parent.parent)
        slide_dirs = sorted(found)
        slide_dirs = [d for d in slide_dirs if fnmatch(d.name, args.include)]
        if args.exclude:
            slide_dirs = [d for d in slide_dirs if not fnmatch(d.name, args.exclude)]

    out: list[SlidePaths] = []
    for sd in slide_dirs:
        summary = find_summary(sd)
        coords = find_coords_csv(sd, args.coords_csv if args.slide_output_dir is not None else None)
        coords_npy = find_coords_npy(sd, args.coords_npy if args.slide_output_dir is not None else None)
        slide_path = resolve_slide_path(sd, summary, args.slide)
        if args.outdir is None:
            od = sd / "post_visualization"
        else:
            root = args.outdir.expanduser().resolve()
            od = root if args.slide_output_dir is not None else root / sd.name
        out.append(SlidePaths(slide_dir=sd, coords_csv=coords, coords_npy=coords_npy, summary_json=summary, slide_path=slide_path, outdir=od))
    return out


def pick_existing_col(cols: Sequence[str], logical: str) -> Optional[str]:
    cols_set = set(cols)
    for c in ALT_COLS[logical]:
        if c in cols_set:
            return c
    return None


def read_cell_table(csv_path: Path) -> pd.DataFrame:
    log(f"Reading cell coordinates: {csv_path}")
    # Read only potentially useful columns; this avoids loading polygon JSON if present.
    wanted = set(sum(ALT_COLS.values(), []))
    preview = pd.read_csv(csv_path, nrows=1)
    available = list(preview.columns)
    usecols = [c for c in available if c in wanted]
    if not usecols:
        raise ValueError(f"Could not identify useful columns in {csv_path}. Available columns: {available}")
    df_raw = pd.read_csv(csv_path, usecols=usecols)

    rename = {}
    for logical in ALT_COLS:
        col = pick_existing_col(df_raw.columns, logical)
        if col is not None:
            rename[col] = logical
    df = df_raw.rename(columns=rename)

    if "centroid_x" not in df.columns or "centroid_y" not in df.columns:
        raise ValueError("Coordinate table must contain centroid_x/centroid_y or equivalent x/y columns")

    if "class_id" not in df.columns:
        if "class_name" in df.columns:
            inverse = {v: k for k, v in ID_TO_NAME.items()}
            canon = df["class_name"].astype(str).map(canonicalize_class_name)
            df["class_name"] = canon
            df["class_id"] = canon.map(inverse).fillna(-1).astype(np.int16)
        else:
            df["class_id"] = -1
    if "class_name" not in df.columns:
        df["class_name"] = df["class_id"].map(ID_TO_NAME).fillna(df["class_id"].astype(str).map(lambda x: f"Class {x}"))
    if "cell_id" not in df.columns:
        df["cell_id"] = np.array([f"cell_{i+1:09d}" for i in range(len(df))], dtype=object)

    # If bbox is missing, create a small fallback bbox around the centroid.
    for col in ["bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1"]:
        if col not in df.columns:
            if col.endswith("x0"):
                df[col] = df["centroid_x"] - 2
            elif col.endswith("y0"):
                df[col] = df["centroid_y"] - 2
            elif col.endswith("x1"):
                df[col] = df["centroid_x"] + 2
            else:
                df[col] = df["centroid_y"] + 2

    numeric_cols = ["class_id", "centroid_x", "centroid_y", "bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1"]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["centroid_x", "centroid_y"]).reset_index(drop=True)
    df["class_id"] = df["class_id"].fillna(-1).astype(np.int16)
    for c in ["centroid_x", "centroid_y", "bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1"]:
        df[c] = df[c].astype(np.float32)

    df["class_name"] = df["class_name"].astype(str).map(canonicalize_class_name)
    # Prefer canonical names/colors for known ids.
    known = df["class_id"].isin(list(ID_TO_NAME.keys()))
    df.loc[known, "class_name"] = df.loc[known, "class_id"].map(ID_TO_NAME).astype(str)
    inverse = {v: k for k, v in ID_TO_NAME.items()}
    unknown_mask = ~known
    recovered_ids = df.loc[unknown_mask, "class_name"].map(inverse)
    recovered_mask = recovered_ids.notna()
    if recovered_mask.any():
        ridx = recovered_ids.index[recovered_mask]
        df.loc[ridx, "class_id"] = recovered_ids.loc[ridx].astype(np.int16)
        df.loc[ridx, "class_name"] = df.loc[ridx, "class_id"].map(ID_TO_NAME).astype(str)

    df["bbox_w"] = np.maximum(1.0, (df["bbox_x1"] - df["bbox_x0"]).astype(np.float32))
    df["bbox_h"] = np.maximum(1.0, (df["bbox_y1"] - df["bbox_y0"]).astype(np.float32))
    df["bbox_area"] = (df["bbox_w"] * df["bbox_h"]).astype(np.float32)
    df["aspect"] = (df["bbox_w"] / np.maximum(df["bbox_h"], 1.0)).astype(np.float32)
    df["source_index"] = np.arange(len(df), dtype=np.int64)
    return df


def get_slide_dimensions(slide_path: Optional[Path], df: pd.DataFrame, summary_path: Optional[Path]) -> tuple[int, int]:
    if slide_path is not None and TiffSlide is not None:
        with TiffSlide(str(slide_path)) as slide:
            w, h = slide.dimensions
            return int(w), int(h)
    if summary_path is not None:
        s = load_json(summary_path)
        if s.get("slide_width_px") and s.get("slide_height_px"):
            return int(s["slide_width_px"]), int(s["slide_height_px"])
    w = int(math.ceil(float(df["centroid_x"].max()) + 1000))
    h = int(math.ceil(float(df["centroid_y"].max()) + 1000))
    return w, h


def get_slide_thumbnail(slide_path: Optional[Path], slide_w: int, slide_h: int, max_dim: int) -> np.ndarray:
    if slide_path is not None and TiffSlide is not None:
        with TiffSlide(str(slide_path)) as slide:
            img = slide.get_thumbnail((int(max_dim), int(max_dim))).convert("RGB")
        return np.asarray(img, dtype=np.uint8)
    # fallback white canvas preserving aspect
    if slide_w >= slide_h:
        tw = int(max_dim)
        th = max(1, int(round(max_dim * slide_h / slide_w)))
    else:
        th = int(max_dim)
        tw = max(1, int(round(max_dim * slide_w / slide_h)))
    return np.full((th, tw, 3), 255, dtype=np.uint8)


def read_region_rgb(slide_path: Optional[Path], roi: tuple[int, int, int, int]) -> np.ndarray:
    x0, y0, x1, y1 = map(int, roi)
    w = max(1, x1 - x0)
    h = max(1, y1 - y0)
    if slide_path is None or TiffSlide is None:
        return np.full((h, w, 3), 255, dtype=np.uint8)
    with TiffSlide(str(slide_path)) as slide:
        sw, sh = slide.dimensions
        canvas = Image.new("RGB", (w, h), (255, 255, 255))
        sx0 = max(0, x0)
        sy0 = max(0, y0)
        sx1 = min(int(sw), x1)
        sy1 = min(int(sh), y1)
        if sx1 > sx0 and sy1 > sy0:
            patch = slide.read_region((sx0, sy0), 0, (sx1 - sx0, sy1 - sy0)).convert("RGB")
            canvas.paste(patch, (sx0 - x0, sy0 - y0))
    return np.asarray(canvas, dtype=np.uint8)


def present_palette(df: pd.DataFrame) -> OrderedDict[str, str]:
    out: OrderedDict[str, str] = OrderedDict()
    tmp = df[["class_id", "class_name"]].drop_duplicates().sort_values(["class_id", "class_name"])
    extra_idx = 0
    for row in tmp.itertuples(index=False):
        cid = int(row.class_id)
        cname = canonicalize_class_name(str(row.class_name))
        color = ID_TO_COLOR.get(cid, NAME_TO_COLOR.get(cname))
        if color is None:
            color = RESERVED_NEW_TYPE_COLORS[extra_idx % len(RESERVED_NEW_TYPE_COLORS)]
            extra_idx += 1
        out[cname] = color
    return out


def hex_to_rgb01(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def stratified_sample(df: pd.DataFrame, max_n: int, seed: int, min_per_class: int = 50) -> pd.DataFrame:
    if len(df) <= max_n:
        return df.copy()
    rng = np.random.default_rng(seed)
    counts = df["class_name"].value_counts()
    classes = counts.index.to_list()
    weights = np.sqrt(counts.astype(float).to_numpy())
    weights = weights / weights.sum()
    alloc = np.floor(max_n * weights).astype(int)
    for i, cls in enumerate(classes):
        alloc[i] = min(int(counts.loc[cls]), max(1, alloc[i], min(min_per_class, int(counts.loc[cls]))))
    while alloc.sum() > max_n:
        i = int(np.argmax(alloc))
        if alloc[i] <= 1:
            break
        alloc[i] -= 1
    while alloc.sum() < max_n:
        room = np.array([int(counts.loc[c]) for c in classes]) - alloc
        if room.max() <= 0:
            break
        i = int(np.argmax(room))
        alloc[i] += 1
    parts = []
    for cls, n in zip(classes, alloc):
        g = df[df["class_name"] == cls]
        if len(g) <= n:
            parts.append(g)
        else:
            # pandas random_state needs int, generate per-class deterministic seed
            parts.append(g.sample(n=int(n), random_state=int(rng.integers(0, 2**31 - 1))))
    if not parts:
        return df.sample(n=max_n, random_state=seed)
    return pd.concat(parts, axis=0).sample(frac=1.0, random_state=seed).reset_index(drop=True)


def choose_rois(df: pd.DataFrame, slide_w: int, slide_h: int, args: argparse.Namespace) -> list[tuple[int, int, int, int, dict[str, Any]]]:
    roi_size = int(args.roi_size)
    work = df[["centroid_x", "centroid_y", "class_name"]].copy()
    work["gx"] = np.floor(work["centroid_x"].to_numpy(dtype=float) / roi_size).astype(np.int32)
    work["gy"] = np.floor(work["centroid_y"].to_numpy(dtype=float) / roi_size).astype(np.int32)
    class_counts = work["class_name"].value_counts()
    total = float(len(work))
    rarity = (total / np.maximum(class_counts.astype(float), 1.0)).pow(0.5)
    rarity = rarity / max(float(rarity.max()), 1.0)
    work["rare_w"] = work["class_name"].map(rarity).astype(np.float32)

    grouped = work.groupby(["gx", "gy"], sort=False).agg(
        count=("centroid_x", "size"),
        medx=("centroid_x", "median"),
        medy=("centroid_y", "median"),
        n_classes=("class_name", "nunique"),
        rare_sum=("rare_w", "sum"),
    ).reset_index()
    if grouped.empty:
        return []
    grouped["score"] = grouped["count"].astype(float) * (1.0 + float(args.roi_score_diversity_weight) * grouped["n_classes"].astype(float)) + float(args.roi_score_rare_weight) * grouped["rare_sum"].astype(float)
    grouped = grouped.sort_values("score", ascending=False)

    selected: list[tuple[int, int, int, int, dict[str, Any]]] = []
    centers: list[tuple[float, float]] = []
    min_d2 = (roi_size * float(args.roi_min_distance_factor)) ** 2
    for row in grouped.itertuples(index=False):
        cx = float(row.medx)
        cy = float(row.medy)
        if any((cx - px) ** 2 + (cy - py) ** 2 < min_d2 for px, py in centers):
            continue
        x0 = int(round(cx - roi_size / 2))
        y0 = int(round(cy - roi_size / 2))
        x0 = max(0, min(max(0, slide_w - roi_size), x0))
        y0 = max(0, min(max(0, slide_h - roi_size), y0))
        x1 = min(slide_w, x0 + roi_size)
        y1 = min(slide_h, y0 + roi_size)
        meta = {"count": int(row.count), "n_classes": int(row.n_classes), "score": float(row.score)}
        selected.append((x0, y0, x1, y1, meta))
        centers.append((cx, cy))
        if len(selected) >= int(args.num_rois):
            break

    # If strict distance left too few ROIs, append remaining high-score bins with relaxed distance.
    if len(selected) < int(args.num_rois):
        for row in grouped.itertuples(index=False):
            cx = float(row.medx)
            cy = float(row.medy)
            x0 = int(round(cx - roi_size / 2))
            y0 = int(round(cy - roi_size / 2))
            x0 = max(0, min(max(0, slide_w - roi_size), x0))
            y0 = max(0, min(max(0, slide_h - roi_size), y0))
            x1 = min(slide_w, x0 + roi_size)
            y1 = min(slide_h, y0 + roi_size)
            box = (x0, y0, x1, y1)
            if any(box[:4] == s[:4] for s in selected):
                continue
            meta = {"count": int(row.count), "n_classes": int(row.n_classes), "score": float(row.score)}
            selected.append((x0, y0, x1, y1, meta))
            if len(selected) >= int(args.num_rois):
                break
    return selected


def subset_roi(df: pd.DataFrame, roi: tuple[int, int, int, int]) -> pd.DataFrame:
    x0, y0, x1, y1 = roi
    m = (
        (df["centroid_x"] >= x0) & (df["centroid_x"] < x1) &
        (df["centroid_y"] >= y0) & (df["centroid_y"] < y1)
    )
    return df.loc[m].copy()


def thin_roi_cells(roi_df: pd.DataFrame, roi: tuple[int, int, int, int], args: argparse.Namespace, seed: int) -> pd.DataFrame:
    max_n = int(args.max_cells_per_roi)
    if len(roi_df) <= max_n:
        return roi_df.copy()
    cand = stratified_sample(roi_df, max_n=max(max_n * 3, max_n), seed=seed, min_per_class=int(args.min_class_cells_per_roi))
    d = float(args.min_distance_px)
    if d > 0 and len(cand) > max_n:
        x0, y0, _x1, _y1 = roi
        # Rare/small classes first, then random, so visually minor classes are not erased by abundant cancer cells.
        counts = cand["class_name"].value_counts()
        cand = cand.assign(
            _class_count=cand["class_name"].map(counts).astype(int),
            _rand=np.random.default_rng(seed).random(len(cand)),
            _gx=np.floor((cand["centroid_x"] - x0) / d).astype(np.int32),
            _gy=np.floor((cand["centroid_y"] - y0) / d).astype(np.int32),
        ).sort_values(["_class_count", "_rand"], ascending=[True, True])
        cand = cand.drop_duplicates(subset=["class_name", "_gx", "_gy"], keep="first")
        cand = cand.drop(columns=[c for c in cand.columns if c.startswith("_")], errors="ignore")
    if len(cand) > max_n:
        cand = stratified_sample(cand, max_n=max_n, seed=seed + 13, min_per_class=int(args.min_class_cells_per_roi))
    return cand.reset_index(drop=True)


def marker_sizes(df: pd.DataFrame, base: float) -> np.ndarray:
    sqrt_area = np.sqrt(np.maximum(df["bbox_area"].to_numpy(dtype=float), 1.0))
    med = np.median(sqrt_area) if len(sqrt_area) else 1.0
    s = base * (sqrt_area / max(med, 1e-6))
    return np.clip(s, base * 0.35, base * 3.2)


def draw_roi_overlay(ax: Any, crop: np.ndarray, roi_df: pd.DataFrame, roi: tuple[int, int, int, int], palette: dict[str, str], args: argparse.Namespace, title: str) -> None:
    x0, y0, x1, y1 = roi
    ax.imshow(crop, extent=[x0, x1, y1, y0])
    ax.set_xlim(x0, x1)
    ax.set_ylim(y1, y0)
    ax.set_xticks([])
    ax.set_yticks([])
    set_axis_style(ax)
    if roi_df.empty:
        ax.set_title(title + "\nno cells in ROI", fontsize=FONT_MED, fontweight="bold", pad=8)
        return

    # Optional bbox outlines before markers.
    if args.draw_bbox:
        for row in roi_df.itertuples(index=False):
            cname = str(row.class_name)
            color = palette.get(cname, "#999999")
            ax.add_patch(Rectangle((float(row.bbox_x0), float(row.bbox_y0)), float(row.bbox_w), float(row.bbox_h),
                                   fill=False, edgecolor=color, linewidth=LINE_THIN, alpha=0.42))

    for cname, g in roi_df.groupby("class_name", sort=False):
        color = palette.get(str(cname), "#999999")
        sizes = marker_sizes(g, float(args.point_size))
        # black halo
        ax.scatter(g["centroid_x"], g["centroid_y"], s=sizes * 1.85, c="black", alpha=min(0.55, float(args.point_alpha)), linewidths=0, rasterized=True)
        ax.scatter(g["centroid_x"], g["centroid_y"], s=sizes, c=color, alpha=float(args.point_alpha), linewidths=0, rasterized=True)
    ax.set_title(title, fontsize=FONT_MED, fontweight="bold", pad=8)


def save_roi_pngs(slide_path: Optional[Path], df: pd.DataFrame, rois: list[tuple[int, int, int, int, dict[str, Any]]], palette: OrderedDict[str, str], outdir: Path, args: argparse.Namespace) -> pd.DataFrame:
    roi_dir = outdir / "spatial_rois"
    roi_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, item in enumerate(rois, start=1):
        x0, y0, x1, y1, meta = item
        roi = (x0, y0, x1, y1)
        crop = read_region_rgb(slide_path, roi)
        roi_all = subset_roi(df, roi)
        roi_plot = thin_roi_cells(roi_all, roi, args, seed=int(args.seed) + i)
        fig, ax = plt.subplots(figsize=(4.2, 4.2), constrained_layout=True)
        draw_roi_overlay(ax, crop, roi_plot, roi, dict(palette), args, title=f"ROI {i}: {len(roi_plot):,}/{len(roi_all):,} cells plotted")
        fig.savefig(roi_dir / f"roi_{i:02d}_overlay.png", dpi=int(args.dpi), bbox_inches="tight")
        plt.close(fig)
        counts = roi_all["class_name"].value_counts().rename_axis("class_name").reset_index(name="count")
        counts.to_csv(roi_dir / f"roi_{i:02d}_class_counts.csv", index=False)
        rows.append({
            "roi_index": i, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "n_cells_all": int(len(roi_all)), "n_cells_plotted": int(len(roi_plot)),
            "n_classes": int(roi_all["class_name"].nunique()),
            "selection_score": float(meta.get("score", np.nan)),
            "overlay_png": str(roi_dir / f"roi_{i:02d}_overlay.png"),
            "class_counts_csv": str(roi_dir / f"roi_{i:02d}_class_counts.csv"),
        })
    manifest = pd.DataFrame(rows)
    manifest.to_csv(roi_dir / "roi_manifest.csv", index=False)
    return manifest


def add_class_legend(ax: Any, palette: OrderedDict[str, str], present_classes: Sequence[str], max_items: int = 18) -> None:
    handles = []
    for cname in present_classes:
        if str(cname) == "Background":
            continue
        handles.append(Patch(facecolor=palette.get(str(cname), "#999999"), edgecolor="black", linewidth=LINE_THIN, label=str(cname)))
    if len(handles) > max_items:
        handles = handles[:max_items]
    if handles:
        ax.legend(handles=handles, loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False, fontsize=FONT_SMALL)


def draw_labeled_barh(ax: Any, counts: pd.Series, palette: OrderedDict[str, str], title: str, xlabel: str = "detected cells") -> None:
    counts = counts.sort_values(ascending=True)
    y = np.arange(len(counts))
    colors = [palette.get(str(c), "#999999") for c in counts.index]
    bars = ax.barh(y, counts.values, height=0.58, color=colors, edgecolor="black", linewidth=LINE_THIN)
    ax.set_yticks(y)
    ax.set_yticklabels(counts.index, fontsize=FONT_SMALL, fontweight="bold")
    for tick, cname in zip(ax.get_yticklabels(), counts.index):
        tick.set_color(palette.get(str(cname), "black"))
    ax.set_xlabel(xlabel, fontweight="bold")
    ax.set_title(title, fontsize=FONT_LARGE, fontweight="bold", pad=10)
    ax.grid(axis="x", alpha=GRID_ALPHA)

    max_val = float(counts.max()) if len(counts) else 0.0
    if max_val <= 0:
        max_val = 1.0
    ax.set_xlim(0, max_val * 1.30)
    pad = max_val * 0.018

    ax.margins(y=0.04)
    set_axis_style(ax)
    for bar, val in zip(bars, counts.values):
        x = float(bar.get_width())
        ytxt = bar.get_y() + bar.get_height() / 2.0
        ax.text(
            x + pad,
            ytxt,
            f"{int(val):,}",
            va="center",
            ha="left",
            fontsize=FONT_SMALL,
            fontweight="bold",
            color="black",
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.82, pad=0.15),
            zorder=5,
        )


def build_class_spotlight_image(class_df: pd.DataFrame, thumb: np.ndarray, slide_w: int, slide_h: int, radius_px: int = 6) -> np.ndarray:
    """Return a white-background thumbnail that keeps H&E only near the class spots."""
    h, w = thumb.shape[:2]
    out = np.full_like(thumb, 255)
    if class_df.empty or h <= 0 or w <= 0:
        return out

    tx = np.clip(np.rint((class_df["centroid_x"].to_numpy(dtype=float) / max(float(slide_w), 1.0)) * (w - 1)).astype(np.int32), 0, w - 1)
    ty = np.clip(np.rint((class_df["centroid_y"].to_numpy(dtype=float) / max(float(slide_h), 1.0)) * (h - 1)).astype(np.int32), 0, h - 1)
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[ty, tx] = 255
    filt_size = max(3, int(2 * radius_px + 1))
    if filt_size % 2 == 0:
        filt_size += 1
    mask_img = Image.fromarray(mask, mode="L").filter(ImageFilter.MaxFilter(size=filt_size))
    mask2 = np.asarray(mask_img, dtype=np.uint8) > 0
    out[mask2] = thumb[mask2]
    return out


def draw_class_spotlight(ax: Any, class_df: pd.DataFrame, thumb: np.ndarray, slide_w: int, slide_h: int, class_name: str, color: str, total_count: int, seed: int) -> None:
    spotlight = build_class_spotlight_image(class_df, thumb, slide_w, slide_h, radius_px=6)
    ax.imshow(spotlight, extent=[0, slide_w, slide_h, 0])

    # Light centroid overlay for the same class to make the hotspots explicit.
    if len(class_df) > 0:
        rng = np.random.default_rng(int(seed))
        max_overlay = 12000
        if len(class_df) > max_overlay:
            idx = rng.choice(len(class_df), size=max_overlay, replace=False)
            plot_df = class_df.iloc[idx]
        else:
            plot_df = class_df
        ax.scatter(plot_df["centroid_x"], plot_df["centroid_y"], s=0.9, c=color, alpha=0.55, linewidths=0, rasterized=True)

    ax.set_xlim(0, slide_w)
    ax.set_ylim(slide_h, 0)
    ax.set_title(f"{class_name}\n n={int(total_count):,}", fontsize=FONT_MED, fontweight="bold", pad=8)
    ax.set_xlabel("level-0 X px")
    ax.set_ylabel("level-0 Y px")
    set_axis_style(ax)


def make_spatial_report(sp: SlidePaths, df: pd.DataFrame, slide_w: int, slide_h: int, args: argparse.Namespace) -> None:
    outdir = sp.outdir
    outdir.mkdir(parents=True, exist_ok=True)
    palette = present_palette(df)
    rois = choose_rois(df, slide_w, slide_h, args)
    if not rois:
        log("No ROIs selected; skipping spatial report.")
        return
    roi_manifest = save_roi_pngs(sp.slide_path, df, rois, palette, outdir, args)

    thumb = get_slide_thumbnail(sp.slide_path, slide_w, slide_h, int(args.thumbnail_max_dim))
    pdf_path = outdir / "spatial_rois_report.pdf"
    log(f"Writing spatial PDF: {pdf_path}")
    with PdfPages(pdf_path) as pdf:
        # Page 1: full-slide sampled map + global class counts side by side.
        overview_df = stratified_sample(df, int(args.overview_max_cells), int(args.seed), min_per_class=500)
        fig = plt.figure(figsize=(14.0, 7.4), constrained_layout=True)
        gs = fig.add_gridspec(1, 2, width_ratios=[1.85, 0.82], wspace=0.12)

        ax = fig.add_subplot(gs[0, 0])
        ax.imshow(thumb, extent=[0, slide_w, slide_h, 0])
        for cname, g in overview_df.groupby("class_name", sort=False):
            ax.scatter(g["centroid_x"], g["centroid_y"], s=float(args.overview_point_size),
                       c=palette.get(str(cname), "#999999"), alpha=0.55, linewidths=0, rasterized=True)
        ax.set_xlim(0, slide_w)
        ax.set_ylim(slide_h, 0)
        ax.set_title(f"Whole-slide sampled cell map over H&E\n{len(overview_df):,} / {len(df):,} cells", fontsize=FONT_LARGE, fontweight="bold", pad=10)
        ax.set_xlabel("level-0 X px")
        ax.set_ylabel("level-0 Y px")
        set_axis_style(ax)

        ax2 = fig.add_subplot(gs[0, 1])
        counts = df["class_name"].value_counts()
        draw_labeled_barh(ax2, counts, palette, title=f"Class counts\nTotal n={len(df):,}")

        pdf.savefig(fig, dpi=int(args.dpi), bbox_inches="tight")
        plt.close(fig)

        # Page 2+: class-specific whole-slide spotlights (all classes, max 4 per PDF page).
        class_counts_all = df["class_name"].value_counts()
        class_items = list(class_counts_all.items())
        n_per_page = 4
        for page_idx, start in enumerate(range(0, len(class_items), n_per_page), start=1):
            batch = class_items[start:start + n_per_page]
            fig, axes = plt.subplots(2, 2, figsize=(14.8, 10.6), constrained_layout=True)
            axes_flat = axes.ravel()
            for axx in axes_flat:
                axx.axis("off")
            for j, (cname, ccount) in enumerate(batch):
                axx = axes_flat[j]
                axx.axis("on")
                class_df = df[df["class_name"] == cname]
                draw_class_spotlight(
                    axx,
                    class_df,
                    thumb,
                    slide_w,
                    slide_h,
                    str(cname),
                    palette.get(str(cname), "#999999"),
                    int(ccount),
                    int(args.seed) + start + j + 1000,
                )
            total_pages = int(math.ceil(len(class_items) / float(n_per_page)))
            fig.suptitle(
                f"Class-specific whole-slide H&E spotlights | page {page_idx}/{total_pages}",
                fontsize=FONT_XL,
                fontweight="bold",
            )
            pdf.savefig(fig, dpi=int(args.dpi), bbox_inches="tight")
            plt.close(fig)

        # Next page: ROI selection overview on the tissue thumbnail.
        fig = plt.figure(figsize=(10.0, 7.6), constrained_layout=True)
        ax = fig.add_subplot(111)
        ax.imshow(thumb, extent=[0, slide_w, slide_h, 0])
        ax.set_title(f"{sp.slide_dir.name}: selected square ROIs", fontsize=FONT_LARGE, fontweight="bold", pad=10)
        ax.set_xlim(0, slide_w)
        ax.set_ylim(slide_h, 0)
        ax.set_xlabel("level-0 X px")
        ax.set_ylabel("level-0 Y px")
        set_axis_style(ax)
        for i, (x0, y0, x1, y1, _meta) in enumerate(rois, start=1):
            ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor="black", linewidth=LINE_HEAVY))
            ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor="white", linewidth=LINE_MED))
            ax.text(x0 + 0.02 * (x1 - x0), y0 + 0.08 * (y1 - y0), str(i), fontsize=FONT_SMALL, color="white",
                    bbox=dict(facecolor="black", edgecolor="white", boxstyle="round,pad=0.15", alpha=0.85))
        pdf.savefig(fig, dpi=int(args.dpi), bbox_inches="tight")
        plt.close(fig)

        # Optional detailed pages.
        if args.roi_detail_pages:
            for i, item in enumerate(rois, start=1):
                x0, y0, x1, y1, _meta = item
                roi = (x0, y0, x1, y1)
                crop = read_region_rgb(sp.slide_path, roi)
                roi_all = subset_roi(df, roi)
                roi_plot = thin_roi_cells(roi_all, roi, args, seed=int(args.seed) + i)
                fig = plt.figure(figsize=(12.2, 5.6), constrained_layout=True)
                gs = fig.add_gridspec(1, 3, width_ratios=[1.0, 1.0, 0.62], wspace=0.18)
                ax0 = fig.add_subplot(gs[0, 0])
                ax0.imshow(crop, extent=[x0, x1, y1, y0])
                ax0.set_xlim(x0, x1); ax0.set_ylim(y1, y0); ax0.set_xticks([]); ax0.set_yticks([])
                ax0.set_title(f"ROI {i}: raw H&E", fontsize=FONT_LARGE, fontweight="bold")
                ax1 = fig.add_subplot(gs[0, 1])
                draw_roi_overlay(ax1, crop, roi_plot, roi, dict(palette), args, title=f"ROI {i}: less-cluttered overlay")
                ax2 = fig.add_subplot(gs[0, 2])
                cts = roi_all["class_name"].value_counts()
                draw_labeled_barh(ax2, cts, palette, title="ROI class counts")
                fig.suptitle(f"{sp.slide_dir.name} | ROI {i} | x={x0}-{x1}, y={y0}-{y1}", fontsize=FONT_LARGE, fontweight="bold")
                pdf.savefig(fig, dpi=int(args.dpi), bbox_inches="tight")
                plt.close(fig)

    # Save a machine-readable manifest.
    meta = {
        "slide_dir": str(sp.slide_dir),
        "slide_path": str(sp.slide_path) if sp.slide_path else None,
        "coords_csv": str(sp.coords_csv),
        "coords_npy": str(sp.coords_npy) if sp.coords_npy else None,
        "slide_width_px": int(slide_w),
        "slide_height_px": int(slide_h),
        "spatial_pdf": str(pdf_path),
        "roi_manifest_csv": str(outdir / "spatial_rois" / "roi_manifest.csv"),
    }
    (outdir / "post_visualization_summary.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    log(f"ROI manifest: {outdir / 'spatial_rois' / 'roi_manifest.csv'}")


# ----------------------------- optional NPY polygon features -----------------------------

def load_npy_payload(npy_path: Optional[Path]) -> Optional[dict[str, Any]]:
    if npy_path is None:
        return None
    log(f"Loading NPY polygon payload: {npy_path}")
    payload = np.load(npy_path, allow_pickle=True).item()
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected NPY payload type: {type(payload)}")
    return payload

def polygon_area_perimeter(coords: np.ndarray) -> tuple[float, float, int]:
    if coords is None or len(coords) < 3:
        return 0.0, 0.0, 0
    arr = np.asarray(coords, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] < 2 or len(arr) < 3:
        return 0.0, 0.0, 0
    xy = arr[:, :2]
    x = xy[:, 0]
    y = xy[:, 1]
    area = 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))
    dxy = np.diff(np.vstack([xy, xy[0]]), axis=0)
    perim = float(np.sqrt((dxy ** 2).sum(axis=1)).sum())
    return area, perim, int(len(xy))

def polygon_features_for_indices(payload: Optional[dict[str, Any]], indices: np.ndarray, mpp: float) -> dict[str, np.ndarray]:
    n = len(indices)
    out = {
        "poly_area_um2": np.full(n, np.nan, dtype=np.float32),
        "poly_perimeter_um": np.full(n, np.nan, dtype=np.float32),
        "poly_vertices": np.full(n, np.nan, dtype=np.float32),
        "poly_compactness": np.full(n, np.nan, dtype=np.float32),
    }
    if payload is None or "polygon_xy" not in payload:
        return out
    poly_obj = payload["polygon_xy"]
    for j, idx in enumerate(indices.astype(int)):
        try:
            polys = poly_obj[idx]
            total_area = 0.0
            total_perim = 0.0
            total_vertices = 0
            if isinstance(polys, np.ndarray) and polys.dtype != object and polys.ndim == 2:
                polys_iter = [polys]
            else:
                polys_iter = polys
            for coords in polys_iter:
                area, perim, vertices = polygon_area_perimeter(coords)
                total_area += area
                total_perim += perim
                total_vertices += vertices
            out["poly_area_um2"][j] = total_area * (float(mpp) ** 2)
            out["poly_perimeter_um"][j] = total_perim * float(mpp)
            out["poly_vertices"][j] = float(total_vertices)
            if total_perim > 0:
                out["poly_compactness"][j] = float(4.0 * math.pi * total_area / (total_perim ** 2))
        except Exception:
            continue
    return out

# ----------------------------- embedding / UMAP -----------------------------

def sample_rgb_from_thumbnail(df: pd.DataFrame, thumb: np.ndarray, slide_w: int, slide_h: int) -> np.ndarray:
    th, tw = thumb.shape[:2]
    xs = np.clip(np.round(df["centroid_x"].to_numpy(dtype=float) * (tw / max(slide_w, 1))).astype(int), 0, tw - 1)
    ys = np.clip(np.round(df["centroid_y"].to_numpy(dtype=float) * (th / max(slide_h, 1))).astype(int), 0, th - 1)
    return thumb[ys, xs, :3].astype(np.float32)


def prepare_embedding_features(sample: pd.DataFrame, rgb: np.ndarray, slide_w: int, slide_h: int, mpp: float, polygon_payload: Optional[dict[str, Any]] = None) -> tuple[pd.DataFrame, np.ndarray, list[str]]:
    out = sample.copy().reset_index(drop=True)
    rgb01 = np.clip(rgb / 255.0, 0, 1)
    od = -np.log(np.clip((rgb + 1.0) / 256.0, 1e-4, 1.0))
    gray = (0.299 * rgb[:, 0] + 0.587 * rgb[:, 1] + 0.114 * rgb[:, 2]) / 255.0
    maxc = rgb01.max(axis=1)
    minc = rgb01.min(axis=1)
    sat = (maxc - minc) / np.maximum(maxc, 1e-6)
    purple_index = ((rgb[:, 0] + rgb[:, 2]) / 2.0 - rgb[:, 1]) / 255.0
    eosin_index = (rgb[:, 0] - rgb[:, 2]) / 255.0
    darkness = 1.0 - gray

    out["he_r"] = rgb[:, 0].astype(np.uint8)
    out["he_g"] = rgb[:, 1].astype(np.uint8)
    out["he_b"] = rgb[:, 2].astype(np.uint8)
    out["he_gray"] = gray.astype(np.float32)
    out["he_saturation"] = sat.astype(np.float32)
    out["he_darkness"] = darkness.astype(np.float32)
    out["he_purple_proxy"] = purple_index.astype(np.float32)
    out["he_eosin_proxy"] = eosin_index.astype(np.float32)
    out["bbox_area_um2"] = (out["bbox_area"].astype(float) * (float(mpp) ** 2)).astype(np.float32)
    out["bbox_w_um"] = (out["bbox_w"].astype(float) * float(mpp)).astype(np.float32)
    out["bbox_h_um"] = (out["bbox_h"].astype(float) * float(mpp)).astype(np.float32)
    out["log_area"] = np.log1p(out["bbox_area"].astype(float)).astype(np.float32)
    poly_features = polygon_features_for_indices(polygon_payload, out["source_index"].to_numpy(dtype=np.int64), mpp=float(mpp)) if polygon_payload is not None else {}
    for k, v in poly_features.items():
        out[k] = v
    out["x_norm"] = (out["centroid_x"].astype(float) / max(slide_w, 1)).astype(np.float32)
    out["y_norm"] = (out["centroid_y"].astype(float) / max(slide_h, 1)).astype(np.float32)

    base_cols = [
        "x_norm", "y_norm", "bbox_w_um", "bbox_h_um", "bbox_area_um2", "log_area", "aspect",
        "he_r", "he_g", "he_b", "he_gray", "he_saturation", "he_darkness", "he_purple_proxy", "he_eosin_proxy",
    ]
    if polygon_payload is not None:
        for c in ["poly_area_um2", "poly_perimeter_um", "poly_vertices", "poly_compactness"]:
            if c in out.columns:
                out[c] = out[c].fillna(out[c].median() if np.isfinite(out[c]).any() else 0.0)
                base_cols.append(c)
    X_num = out[base_cols].astype(float).to_numpy()
    # Include class identity as one-hot features, so the embedding knows both morphology/color and HistoPLUS identity.
    class_dummies = pd.get_dummies(out["class_name"], prefix="class", dtype=float)
    feature_names = base_cols + class_dummies.columns.to_list()
    X = np.hstack([X_num, class_dummies.to_numpy(dtype=float)])
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    X = (X - mu) / np.where(sd > 1e-8, sd, 1.0)
    return out, X.astype(np.float32), feature_names


def compute_embedding(X: np.ndarray, args: argparse.Namespace) -> tuple[np.ndarray, str]:
    method = args.embedding_method
    if method in {"auto", "umap"}:
        try:
            import umap  # type: ignore
            reducer = umap.UMAP(
                n_neighbors=int(args.umap_n_neighbors),
                min_dist=float(args.umap_min_dist),
                n_components=2,
                metric="euclidean",
                random_state=int(args.seed),
                low_memory=True,
            )
            emb = reducer.fit_transform(X)
            return emb.astype(np.float32), "UMAP"
        except Exception as exc:
            if method == "umap":
                raise RuntimeError("UMAP requested but umap-learn could not be used. Install with: python -m pip install umap-learn scikit-learn") from exc
            log(f"UMAP unavailable or failed ({exc}); falling back to PCA.")
    # PCA fallback.
    try:
        from sklearn.decomposition import PCA  # type: ignore
        emb = PCA(n_components=2, random_state=int(args.seed)).fit_transform(X)
        return emb.astype(np.float32), "PCA fallback"
    except Exception:
        # Pure numpy PCA fallback.
        Xc = X - X.mean(axis=0, keepdims=True)
        _u, _s, vt = np.linalg.svd(Xc, full_matrices=False)
        emb = Xc @ vt[:2].T
        return emb.astype(np.float32), "PCA fallback (numpy)"


def annotate_embedding_class_counts(
    ax: Any,
    emb_df: pd.DataFrame,
    full_counts: pd.Series,
    palette: OrderedDict[str, str],
) -> None:
    """Place class-count labels near clusters without long off-panel arrows.

    Heuristic rules for this specific graph:
    - prefer label directions rotated about 30 degrees away from the radial line,
      so arrows do not run directly through the number boxes;
    - keep labels outside the local cluster core to avoid covering points;
    - keep arrows short and inside a controlled margin around the UMAP.
    """
    if emb_df.empty:
        return

    labels: list[dict[str, Any]] = []
    for cname, g in emb_df.groupby("class_name", sort=False):
        if g.empty:
            continue
        xvals = g["embed_1"].to_numpy(dtype=float)
        yvals = g["embed_2"].to_numpy(dtype=float)
        x = float(np.nanmedian(xvals))
        y = float(np.nanmedian(yvals))
        qx = np.nanpercentile(xvals, [10, 90])
        qy = np.nanpercentile(yvals, [10, 90])
        labels.append({
            "class_name": str(cname),
            "x": x,
            "y": y,
            "n": int(full_counts.get(str(cname), len(g))),
            "color": palette.get(str(cname), "#999999"),
            "spread_x": float(max(qx[1] - qx[0], 0.0)),
            "spread_y": float(max(qy[1] - qy[0], 0.0)),
            "core_x0": float(qx[0]),
            "core_x1": float(qx[1]),
            "core_y0": float(qy[0]),
            "core_y1": float(qy[1]),
        })
    if not labels:
        return

    xs_all = emb_df["embed_1"].to_numpy(dtype=float)
    ys_all = emb_df["embed_2"].to_numpy(dtype=float)
    xmin, xmax = float(np.nanmin(xs_all)), float(np.nanmax(xs_all))
    ymin, ymax = float(np.nanmin(ys_all)), float(np.nanmax(ys_all))
    xspan = max(xmax - xmin, 1e-6)
    yspan = max(ymax - ymin, 1e-6)
    diag = float(np.hypot(xspan, yspan))
    cx = float(np.nanmedian(xs_all))
    cy = float(np.nanmedian(ys_all))

    xpad = 0.10 * xspan
    ypad = 0.10 * yspan
    xmin_plot, xmax_plot = xmin - xpad, xmax + xpad
    ymin_plot, ymax_plot = ymin - ypad, ymax + ypad
    ax.set_xlim(xmin_plot, xmax_plot)
    ax.set_ylim(ymin_plot, ymax_plot)

    placed_boxes: list[tuple[float, float, float, float]] = []
    labels = sorted(labels, key=lambda d: (int(d["n"]), str(d["class_name"])))

    def overlap_count(box: tuple[float, float, float, float], others: list[tuple[float, float, float, float]]) -> int:
        x0, y0, x1, y1 = box
        n = 0
        for ox0, oy0, ox1, oy1 in others:
            if not (x1 < ox0 or x0 > ox1 or y1 < oy0 or y0 > oy1):
                n += 1
        return n

    def clamp(v: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, v))

    def rotate(vec: tuple[float, float], deg: float) -> tuple[float, float]:
        rad = np.deg2rad(deg)
        c = float(np.cos(rad))
        s = float(np.sin(rad))
        x, y = vec
        return (c * x - s * y, s * x + c * y)

    def box_intersects_rect(box: tuple[float, float, float, float], rect: tuple[float, float, float, float]) -> bool:
        x0, y0, x1, y1 = box
        rx0, ry0, rx1, ry1 = rect
        return not (x1 < rx0 or x0 > rx1 or y1 < ry0 or y0 > ry1)

    compass = [
        (1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0),
        (0.72, 0.72), (-0.72, 0.72), (0.72, -0.72), (-0.72, -0.72),
    ]

    for i, d in enumerate(labels):
        x = float(d["x"])
        y = float(d["y"])
        vx = x - cx
        vy = y - cy
        norm = float(np.hypot(vx, vy))
        if norm < 1e-6:
            angle = (2.0 * np.pi * i) / max(len(labels), 1)
            vx, vy = float(np.cos(angle)), float(np.sin(angle))
            norm = 1.0
        outward = (vx / norm, vy / norm)

        # Prefer label placements rotated ~30 degrees away from the direct radial path.
        directions: list[tuple[float, float]] = [
            rotate(outward, 30.0),
            rotate(outward, -30.0),
            rotate(outward, 55.0),
            rotate(outward, -55.0),
            outward,
        ]
        for dx, dy in compass:
            if all(abs(dx - ox) > 0.20 or abs(dy - oy) > 0.20 for ox, oy in directions):
                directions.append((dx, dy))

        nchars = len(f"{int(d['n']):,}")
        box_w = xspan * (0.034 + 0.0085 * nchars)
        box_h = yspan * 0.043
        cluster_spread = max(float(d["spread_x"]), float(d["spread_y"]), 0.0)
        base_r = max(0.060 * diag, min(0.135 * diag, 0.82 * cluster_spread + 0.040 * diag))
        radial_steps = [base_r, base_r * 1.20, base_r * 1.42]

        # Expanded local core rectangle: candidate labels should stay outside this region.
        core_rect = (
            d["core_x0"] - 0.25 * box_w,
            d["core_y0"] - 0.35 * box_h,
            d["core_x1"] + 0.25 * box_w,
            d["core_y1"] + 0.35 * box_h,
        )

        candidates: list[tuple[float, float, tuple[float, float, float, float], float, int, int]] = []
        for dx, dy in directions:
            dn = float(np.hypot(dx, dy)) or 1.0
            ux, uy = dx / dn, dy / dn
            for r in radial_steps:
                lx = x + ux * r
                ly = y + uy * r
                lx = clamp(lx, xmin_plot + box_w / 2.0, xmax_plot - box_w / 2.0)
                ly = clamp(ly, ymin_plot + box_h / 2.0, ymax_plot - box_h / 2.0)
                box = (lx - box_w / 2.0, ly - box_h / 2.0, lx + box_w / 2.0, ly + box_h / 2.0)
                dist_norm = float(np.hypot((lx - x) / xspan, (ly - y) / yspan))
                if dist_norm > 0.34:
                    continue
                box_hits_core = int(box_intersects_rect(box, core_rect))
                candidates.append((lx, ly, box, dist_norm, overlap_count(box, placed_boxes), box_hits_core))

        if candidates:
            # Prefer labels that do not overlap previous labels and do not cover the local cluster.
            candidates.sort(key=lambda z: (z[5], z[4], z[3]))
            chosen = candidates[0]
        else:
            # Safe local fallback with a 30-degree bias.
            ux, uy = rotate(outward, 30.0)
            dn = float(np.hypot(ux, uy)) or 1.0
            ux, uy = ux / dn, uy / dn
            lx = clamp(x + ux * (0.075 * diag), xmin_plot + box_w / 2.0, xmax_plot - box_w / 2.0)
            ly = clamp(y + uy * (0.075 * diag), ymin_plot + box_h / 2.0, ymax_plot - box_h / 2.0)
            box = (lx - box_w / 2.0, ly - box_h / 2.0, lx + box_w / 2.0, ly + box_h / 2.0)
            chosen = (lx, ly, box, 0.0, overlap_count(box, placed_boxes), int(box_intersects_rect(box, core_rect)))

        lx, ly, box, _dist, _ov, _hits_core = chosen
        placed_boxes.append(box)

        ax.annotate(
            f"{int(d['n']):,}",
            xy=(x, y),
            xytext=(lx, ly),
            textcoords="data",
            ha="center",
            va="center",
            fontsize=FONT_SMALL,
            fontweight="bold",
            color="black",
            bbox=dict(
                boxstyle="round,pad=0.22",
                facecolor="white",
                edgecolor=str(d["color"]),
                linewidth=max(0.9, LINE_THIN * 0.72),
                alpha=0.96,
            ),
            arrowprops=dict(
                arrowstyle="->",
                color="black",
                lw=max(0.9, LINE_THIN * 0.78),
                shrinkA=5,
                shrinkB=4,
                mutation_scale=9,
                alpha=0.94,
                connectionstyle="arc3,rad=0.0",
            ),
            zorder=20,
            clip_on=True,
        )


def scatter_embedding_by_class(
    ax: Any,
    emb_df: pd.DataFrame,
    palette: OrderedDict[str, str],
    args: argparse.Namespace,
    full_counts: Optional[pd.Series] = None,
) -> None:
    for cname, g in emb_df.groupby("class_name", sort=False):
        ax.scatter(g["embed_1"], g["embed_2"], s=float(args.embedding_point_size),
                   c=palette.get(str(cname), "#999999"), alpha=float(args.embedding_alpha), linewidths=0, rasterized=True)
    if bool(getattr(args, "label_umap_counts", True)) and full_counts is not None:
        annotate_embedding_class_counts(ax, emb_df, full_counts, palette)
    ax.set_xlabel("component 1")
    ax.set_ylabel("component 2")
    ax.set_title("Embedding colored by HistoPLUS cell type", fontsize=FONT_LARGE, fontweight="bold", pad=10)
    set_axis_style(ax)
    add_class_legend(ax, palette, emb_df["class_name"].drop_duplicates().tolist())


def make_embedding_report(sp: SlidePaths, df: pd.DataFrame, slide_w: int, slide_h: int, args: argparse.Namespace) -> None:
    outdir = sp.outdir
    outdir.mkdir(parents=True, exist_ok=True)
    palette = present_palette(df)
    sample = stratified_sample(df, int(args.embedding_max_cells), int(args.seed), min_per_class=1000)
    thumb = get_slide_thumbnail(sp.slide_path, slide_w, slide_h, int(args.thumbnail_max_dim))
    rgb = sample_rgb_from_thumbnail(sample, thumb, slide_w, slide_h)
    polygon_payload = load_npy_payload(sp.coords_npy) if bool(args.use_npy_polygons) else None
    emb_df, X, feature_names = prepare_embedding_features(sample, rgb, slide_w, slide_h, float(args.mpp), polygon_payload=polygon_payload)
    embedding, method = compute_embedding(X, args)
    emb_df["embed_1"] = embedding[:, 0]
    emb_df["embed_2"] = embedding[:, 1]
    emb_df["embedding_method"] = method
    full_class_counts = df["class_name"].value_counts()
    emb_df["class_total_count"] = emb_df["class_name"].map(full_class_counts).fillna(0).astype(np.int64)

    if args.save_embedding_csv:
        csv_path = outdir / "cell_embedding_features.csv"
        keep_cols = [
            "cell_id", "class_id", "class_name", "centroid_x", "centroid_y", "bbox_w_um", "bbox_h_um", "bbox_area_um2", "aspect",
            "poly_area_um2", "poly_perimeter_um", "poly_vertices", "poly_compactness",
            "he_r", "he_g", "he_b", "he_gray", "he_saturation", "he_darkness", "he_purple_proxy", "he_eosin_proxy",
            "embed_1", "embed_2", "embedding_method", "class_total_count",
        ]
        keep_cols = [c for c in keep_cols if c in emb_df.columns]
        emb_df[keep_cols].to_csv(csv_path, index=False)
        (outdir / "embedding_feature_columns.json").write_text(json.dumps({"method": method, "features": feature_names}, indent=2), encoding="utf-8")
        log(f"Embedding CSV: {csv_path}")

    pdf_path = outdir / "cell_embedding_umap_report.pdf"
    log(f"Writing embedding PDF: {pdf_path}")
    with PdfPages(pdf_path) as pdf:
        fig, ax = plt.subplots(figsize=(10.2, 7.4), constrained_layout=True)
        scatter_embedding_by_class(ax, emb_df, palette, args, full_counts=full_class_counts)
        pdf.savefig(fig, dpi=int(args.dpi), bbox_inches="tight")
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(9.8, 7.3), constrained_layout=True)
        he_colors = emb_df[["he_r", "he_g", "he_b"]].to_numpy(dtype=float) / 255.0
        ax.scatter(emb_df["embed_1"], emb_df["embed_2"], s=float(args.embedding_point_size) * 1.4,
                   c=he_colors, alpha=0.90, linewidths=0, rasterized=True)
        ax.set_xlabel("component 1"); ax.set_ylabel("component 2")
        ax.set_title("Embedding colored by sampled H&E RGB at each cell centroid", fontsize=FONT_LARGE, fontweight="bold", pad=10)
        set_axis_style(ax)
        pdf.savefig(fig, dpi=int(args.dpi), bbox_inches="tight")
        plt.close(fig)

        # Continuous feature views.
        feature_views = [
            ("bbox_area_um2", "Cell size proxy: bbox area (µm²)", "viridis"),
            ("aspect", "Cell shape proxy: bbox width / height", "magma"),
            ("he_darkness", "H&E optical darkness proxy", "inferno"),
            ("he_purple_proxy", "Purple/hematoxylin-like proxy", "coolwarm"),
        ]
        fig, axes = plt.subplots(2, 2, figsize=(12.2, 9.0), squeeze=False, constrained_layout=True)
        for ax, (col, title, cmap) in zip(axes.ravel(), feature_views):
            vals = emb_df[col].astype(float).to_numpy()
            vmin, vmax = np.nanpercentile(vals, [2, 98]) if len(vals) else (None, None)
            sc = ax.scatter(emb_df["embed_1"], emb_df["embed_2"], s=float(args.embedding_point_size),
                            c=vals, cmap=cmap, vmin=vmin, vmax=vmax, alpha=float(args.embedding_alpha), linewidths=0, rasterized=True)
            ax.set_title(title, fontsize=FONT_LARGE, fontweight="bold", pad=8)
            ax.set_xlabel("component 1"); ax.set_ylabel("component 2")
            set_axis_style(ax)
            fig.colorbar(sc, ax=ax, fraction=0.046, pad=0.04)
        pdf.savefig(fig, dpi=int(args.dpi), bbox_inches="tight")
        plt.close(fig)

        fig, axes = plt.subplots(1, 2, figsize=(12.0, 5.3), squeeze=False, constrained_layout=True)
        for ax, col, title in [(axes.ravel()[0], "x_norm", "Original slide X position"), (axes.ravel()[1], "y_norm", "Original slide Y position")]:
            vals = emb_df[col].astype(float).to_numpy()
            sc = ax.scatter(emb_df["embed_1"], emb_df["embed_2"], s=float(args.embedding_point_size),
                            c=vals, cmap="viridis", alpha=float(args.embedding_alpha), linewidths=0, rasterized=True)
            ax.set_title(title, fontsize=FONT_LARGE, fontweight="bold", pad=8)
            ax.set_xlabel("component 1"); ax.set_ylabel("component 2")
            set_axis_style(ax)
            fig.colorbar(sc, ax=ax, fraction=0.046, pad=0.04)
        pdf.savefig(fig, dpi=int(args.dpi), bbox_inches="tight")
        plt.close(fig)


# ----------------------------- main -----------------------------

def process_one(sp: SlidePaths, args: argparse.Namespace) -> None:
    sp.outdir.mkdir(parents=True, exist_ok=True)
    log("=" * 90)
    log(f"Slide output dir : {sp.slide_dir}")
    log(f"Coordinates CSV  : {sp.coords_csv}")
    log(f"Summary JSON     : {sp.summary_json}")
    log(f"Coordinates NPY  : {sp.coords_npy if sp.coords_npy else 'not found / not used'}")
    log(f"Slide TIFF       : {sp.slide_path if sp.slide_path else 'NOT FOUND - using blank backgrounds'}")
    log(f"Post outdir      : {sp.outdir}")

    df = read_cell_table(sp.coords_csv)
    slide_w, slide_h = get_slide_dimensions(sp.slide_path, df, sp.summary_json)
    log(f"Loaded cells={len(df):,}; slide dimensions={slide_w:,} x {slide_h:,} px")

    if not args.no_spatial_report:
        make_spatial_report(sp, df, slide_w, slide_h, args)
    if not args.no_embedding_report:
        make_embedding_report(sp, df, slide_w, slide_h, args)


def main() -> None:
    args = parse_args()
    np.random.seed(int(args.seed))
    if TiffSlide is None:
        warnings.warn("tiffslide is not importable. The script will still run, but H&E backgrounds/RGB features will be blank unless tiffslide is installed.")
    slides = discover_slide_dirs(args)
    if not slides:
        raise SystemExit("No slide output directories found.")
    log(f"Discovered {len(slides)} slide output directory/directories.")
    failed = []
    for sp in slides:
        try:
            process_one(sp, args)
        except Exception as exc:
            failed.append((sp.slide_dir.name, str(exc)))
            log(f"FAILED {sp.slide_dir.name}: {exc}")
            if args.slide_output_dir is not None:
                raise
    if failed:
        log("Failures:")
        for name, err in failed:
            log(f"  - {name}: {err}")
        raise SystemExit(1)
    log("Done.")


if __name__ == "__main__":
    main()
