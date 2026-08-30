"""CK20-guided CD3/CD8 quantification for serial colon-cancer WSIs.

The module produces a research proxy, not the proprietary or clinically
validated Immunoscore assay. Consensus Immunoscore requires pathologist-
validated tumour-core and invasive-margin regions plus an external reference
cohort. This implementation instead registers serial CD3 and CD8 sections to
CK20 and reports auditable cell-density proxies in CK20-positive epithelial
and CK20-negative tissue compartments.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import html
import json
import math
import os
import re
import stat
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from tumorquantai_cli import ihc
from tumorquantai_cli.mds_reader import (
    MdsLevel,
    MdsPixels,
    MdsReadError,
    digest_file,
)


IMMUNOSCORE_SCHEMA_VERSION = "tumorquantai_ck20_immunoscore_proxy_v1"
IMMUNOSCORE_ENGINE_VERSION = (
    "serial-wsi-registration-ck20-streamed-compartment-cd3-cd8-v2"
)
IMMUNOSCORE_QC_POLICY_VERSION = "colon-ihc-automatic-qc-v2"
IMMUNOSCORE_MARKERS = ("CD3", "CD8", "CK20")
IMMUNE_MARKERS = ("CD3", "CD8")
CASE_ALIAS_RE = re.compile(r"^TQA_CI_[A-Z2-7]{20}$")
SLIDE_ALIAS_RE = re.compile(r"^TQA_CIS_[A-Z2-7]{20}$")
SOURCE_BUNDLE_RE = re.compile(
    r"^(?P<case_id>.+)-(?P<marker>CD3|CD8|CK20)-(?P<suffix>.+)$",
    re.IGNORECASE,
)
PRIVATE_LINKAGE_FIELDS = (
    "case_alias",
    "slide_alias",
    "source_case_id",
    "source_slide_id",
    "marker",
    "source_mds_path",
    "source_mds_size_bytes",
    "source_mds_sha256",
)
PUBLIC_SLIDE_FIELDS = (
    "case_alias",
    "slide_alias",
    "marker",
    "source_format",
    "source_mpp",
    "source_mpp_provenance",
)
REGISTRATION_FIELDS = (
    "case_alias",
    "marker",
    "reference_marker",
    "method",
    "feature_matches",
    "inliers",
    "inlier_fraction",
    "tissue_dice",
    "registered_tissue_fraction",
    "qc_status",
    "matrix_00",
    "matrix_01",
    "matrix_02",
    "matrix_10",
    "matrix_11",
    "matrix_12",
)
COMPARTMENT_FIELDS = (
    "case_alias",
    "marker",
    "compartment",
    "positive_cell_count",
    "segmented_nucleus_count",
    "analyzed_area_mm2",
    "positive_cell_density_per_mm2",
    "mapped_positive_cell_fraction",
    "analysis_mpp",
    "registration_tissue_dice",
    "qc_status",
    "qc_flags",
)
CASE_VALUE_FIELDS = (
    "case_alias",
    "tumorquantai_cd3_ck20_epithelium_density_per_mm2",
    "tumorquantai_cd3_ck20_stroma_density_per_mm2",
    "tumorquantai_cd8_ck20_epithelium_density_per_mm2",
    "tumorquantai_cd8_ck20_stroma_density_per_mm2",
    "cd3_ck20_epithelium_internal_percentile",
    "cd3_ck20_stroma_internal_percentile",
    "cd8_ck20_epithelium_internal_percentile",
    "cd8_ck20_stroma_internal_percentile",
    "ck20_guided_internal_mean_percentile",
    "ck20_guided_internal_rank_group",
    "consensus_immunoscore",
    "consensus_immunoscore_status",
    "qc_status",
    "qc_flags",
)
CASE_DENSITY_FIELDS = CASE_VALUE_FIELDS[1:5]
COHORT_DENSITY_SUMMARY_FIELDS = (
    "analysis_population",
    "measurement",
    "unit",
    "n",
    "mean",
    "sample_standard_deviation",
    "median",
    "first_quartile",
    "third_quartile",
    "minimum",
    "maximum",
)
UNAVAILABLE_FIELDS = ("case_alias", "available_markers", "missing_markers", "reason")


class ImmunoscoreError(RuntimeError):
    """Expected, user-facing colon Immunoscore workflow error."""


@dataclass(frozen=True)
class ImmunoscoreConfig:
    """Versioned settings for one CK20-guided serial-section analysis."""

    target_analysis_mpp: float = 0.55
    overview_max_edge: int = 2048
    block_tiles: int = 4
    block_boundary_exclusion_um: float = 8.0
    weak_dab_od: float = 0.16
    moderate_dab_od: float = 0.32
    strong_dab_od: float = 0.52
    minimum_dab_color_margin_od: float = 0.02
    minimum_dab_color_ratio: float = 0.15
    positive_cell_dab_coverage: float = 0.08
    cell_expansion_um: float = 3.0
    ck20_target_analysis_mpp: float = 2.0
    ck20_minimum_dab_od: float = 0.08
    ck20_minimum_projected_fraction: float = 0.02
    ck20_minimum_component_um2: float = 1_000.0
    ck20_epithelium_expansion_um: float = 8.0
    minimum_registration_dice: float = 0.35
    minimum_tissue_area_mm2: float = 1.0

    def validate(self) -> None:
        for key, value in asdict(self).items():
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ImmunoscoreError(f"Invalid non-finite setting: {key}")
        if self.target_analysis_mpp <= 0:
            raise ImmunoscoreError("Target analysis MPP must be greater than zero")
        if self.overview_max_edge < 512:
            raise ImmunoscoreError("Overview maximum edge must be at least 512")
        if self.block_tiles < 1 or self.block_tiles > 16:
            raise ImmunoscoreError("Block tile count must be between 1 and 16")
        if not 0 < self.weak_dab_od < self.moderate_dab_od < self.strong_dab_od:
            raise ImmunoscoreError("Immune-cell DAB thresholds are invalid")
        if not 0 <= self.positive_cell_dab_coverage <= 1:
            raise ImmunoscoreError("DAB coverage must be in [0, 1]")
        if not 0 <= self.minimum_registration_dice <= 1:
            raise ImmunoscoreError("Minimum registration Dice must be in [0, 1]")
        if self.block_boundary_exclusion_um < 0:
            raise ImmunoscoreError("Block-boundary exclusion must not be negative")
        if self.minimum_dab_color_margin_od < 0:
            raise ImmunoscoreError("Minimum DAB colour margin must not be negative")
        if self.minimum_dab_color_ratio < 0:
            raise ImmunoscoreError("Minimum DAB colour ratio must not be negative")
        if self.cell_expansion_um < 0 or self.ck20_epithelium_expansion_um < 0:
            raise ImmunoscoreError("Cell and CK20 expansion must not be negative")
        if self.ck20_minimum_dab_od < 0:
            raise ImmunoscoreError("CK20 DAB threshold must not be negative")
        if self.ck20_target_analysis_mpp <= 0:
            raise ImmunoscoreError("CK20 analysis MPP must be greater than zero")
        if not 0 < self.ck20_minimum_projected_fraction <= 1:
            raise ImmunoscoreError("CK20 projected-positive fraction must be in (0, 1]")
        if self.ck20_minimum_component_um2 <= 0:
            raise ImmunoscoreError("CK20 component area must be greater than zero")
        if self.minimum_tissue_area_mm2 <= 0:
            raise ImmunoscoreError("Minimum tissue area must be greater than zero")

    def signature(self) -> str:
        payload = {
            "schema_version": IMMUNOSCORE_SCHEMA_VERSION,
            "engine_version": IMMUNOSCORE_ENGINE_VERSION,
            "settings": asdict(self),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True)
class ImmunoscoreSlide:
    case_alias: str
    slide_alias: str
    source_case_id: str
    source_slide_id: str
    marker: str
    source_path: Path
    source_mpp: float
    source_mpp_provenance: str
    source_size_bytes: int = 0
    source_sha256: str = ""

    def public_row(self) -> dict[str, Any]:
        return {
            "case_alias": self.case_alias,
            "slide_alias": self.slide_alias,
            "marker": self.marker,
            "source_format": "Motic MDS DSI0 pixel pyramid",
            "source_mpp": self.source_mpp,
            "source_mpp_provenance": self.source_mpp_provenance,
        }


@dataclass(frozen=True)
class Overview:
    rgb: np.ndarray
    level_index: int
    level_name: str
    level_width: int
    level_height: int
    source_width: int
    source_height: int
    overview_mpp_x: float
    overview_mpp_y: float


@dataclass(frozen=True)
class RegistrationResult:
    matrix: np.ndarray
    method: str
    feature_matches: int
    inliers: int
    inlier_fraction: float
    tissue_dice: float
    registered_tissue_fraction: float
    qc_status: str


def _overview_metadata(value: Overview) -> dict[str, Any]:
    return {
        "level_index": value.level_index,
        "level_name": value.level_name,
        "level_width": value.level_width,
        "level_height": value.level_height,
        "overview_width": int(value.rgb.shape[1]),
        "overview_height": int(value.rgb.shape[0]),
        "source_width": value.source_width,
        "source_height": value.source_height,
        "overview_mpp_x": value.overview_mpp_x,
        "overview_mpp_y": value.overview_mpp_y,
    }


def _atomic_csv(
    path: Path,
    fields: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    *,
    mode: int = 0o644,
) -> None:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink():
        raise ImmunoscoreError(f"Refusing symlink output: {candidate}")
    path = candidate.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=list(fields),
                extrasaction="ignore",
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _atomic_json(path: Path, payload: Mapping[str, Any], *, mode: int = 0o644) -> None:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink():
        raise ImmunoscoreError(f"Refusing symlink output: {candidate}")
    path = candidate.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_alias_secret(path: Path) -> bytes:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_file():
        raise ImmunoscoreError("Alias secret must be a regular file")
    path = candidate.resolve()
    status = path.stat()
    if (
        stat.S_IMODE(status.st_mode) != 0o600
        or status.st_uid != os.getuid()
        or status.st_nlink != 1
    ):
        raise ImmunoscoreError(
            "Alias secret must be owner-controlled, single-linked, and mode 0600"
        )
    secret = path.read_bytes()
    if len(secret) < 32:
        raise ImmunoscoreError("Alias secret must contain at least 32 random bytes")
    return secret


def _public_token(secret: bytes, domain: bytes, value: str) -> str:
    digest = hmac.new(
        secret,
        domain + b"\x00" + value.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b32encode(digest).decode("ascii").rstrip("=")[:20]


def _case_alias(secret: bytes, source_case_id: str) -> str:
    return "TQA_CI_" + _public_token(
        secret,
        b"TumorQuantAI colon immunoscore case alias v1",
        source_case_id,
    )


def _slide_alias(secret: bytes, source_slide_id: str) -> str:
    return "TQA_CIS_" + _public_token(
        secret,
        b"TumorQuantAI colon immunoscore slide alias v1",
        source_slide_id,
    )


def read_motic_source_mpp(slide_directory: Path) -> tuple[float, str]:
    """Read the scanner's physical scale from the private Motic sidecar."""
    path = slide_directory / "info.ini"
    if path.is_symlink() or not path.is_file():
        raise ImmunoscoreError("Motic slide bundle lacks a regular info.ini")
    scale: float | None = None
    for line in path.read_text(encoding="utf-8-sig", errors="strict").splitlines():
        key, separator, raw_value = line.partition("=")
        if separator and key.strip().casefold() == "scale":
            try:
                scale = float(raw_value.strip())
            except ValueError as exc:
                raise ImmunoscoreError("Motic info.ini has invalid scale") from exc
    if scale is None or not math.isfinite(scale) or scale <= 0:
        raise ImmunoscoreError("Motic info.ini has no valid physical scale")
    return scale, "private Motic info.ini scale"


def discover_mds_slides(
    input_root: Path,
    alias_secret: Path,
    *,
    source_mpp: float | None = None,
) -> list[ImmunoscoreSlide]:
    """Discover exact case/marker MDS bundles and replace private identifiers."""
    candidate = input_root.expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_dir():
        raise ImmunoscoreError("Immunoscore input must be a regular directory")
    input_root = candidate.resolve()
    secret = _read_alias_secret(alias_secret)
    paths = sorted(input_root.rglob("*.mds"), key=lambda item: str(item).casefold())
    if not paths:
        raise ImmunoscoreError("No MDS WSIs were found under the input directory")
    records: list[ImmunoscoreSlide] = []
    seen: set[tuple[str, str]] = set()
    seen_case_aliases: dict[str, str] = {}
    seen_slide_aliases: set[str] = set()
    for path in paths:
        if path.is_symlink() or not path.is_file() or path.name.casefold() != "1.mds":
            raise ImmunoscoreError(
                "Each discovered MDS must be a regular bundle file named 1.mds"
            )
        match = SOURCE_BUNDLE_RE.fullmatch(path.parent.name)
        if match is None:
            raise ImmunoscoreError(
                "An MDS bundle name does not contain an unambiguous CD3/CD8/CK20 token"
            )
        source_case_id = match.group("case_id").strip()
        marker = match.group("marker").upper()
        source_slide_id = path.parent.name
        key = (source_case_id.casefold(), marker)
        if key in seen:
            raise ImmunoscoreError("A source case has duplicate slides for one marker")
        seen.add(key)
        measured_mpp, provenance = read_motic_source_mpp(path.parent)
        if source_mpp is not None:
            if (
                not math.isfinite(source_mpp)
                or source_mpp <= 0
                or not math.isclose(
                    measured_mpp, source_mpp, rel_tol=1e-6, abs_tol=1e-6
                )
            ):
                raise ImmunoscoreError(
                    "Explicit source MPP differs from the Motic sidecar scale"
                )
        case_alias = _case_alias(secret, source_case_id)
        slide_alias = _slide_alias(secret, source_slide_id)
        prior_case = seen_case_aliases.setdefault(case_alias, source_case_id)
        if prior_case != source_case_id or slide_alias in seen_slide_aliases:
            raise ImmunoscoreError("Public alias collision detected")
        seen_slide_aliases.add(slide_alias)
        records.append(
            ImmunoscoreSlide(
                case_alias=case_alias,
                slide_alias=slide_alias,
                source_case_id=source_case_id,
                source_slide_id=source_slide_id,
                marker=marker,
                source_path=path.resolve(),
                source_mpp=measured_mpp,
                source_mpp_provenance=provenance,
            )
        )
    records.sort(
        key=lambda item: (
            item.case_alias,
            IMMUNOSCORE_MARKERS.index(item.marker),
        )
    )
    return records


def add_source_digests(
    records: Sequence[ImmunoscoreSlide],
) -> list[ImmunoscoreSlide]:
    digests: dict[Path, tuple[int, str]] = {}
    result: list[ImmunoscoreSlide] = []
    for record in records:
        try:
            size, sha256 = digests.setdefault(
                record.source_path, digest_file(record.source_path)
            )
        except MdsReadError as exc:
            raise ImmunoscoreError(str(exc)) from exc
        result.append(
            ImmunoscoreSlide(
                **{
                    **asdict(record),
                    "source_size_bytes": size,
                    "source_sha256": sha256,
                }
            )
        )
    return result


def _private_linkage_rows(
    records: Sequence[ImmunoscoreSlide],
) -> list[dict[str, Any]]:
    return [
        {
            "case_alias": row.case_alias,
            "slide_alias": row.slide_alias,
            "source_case_id": row.source_case_id,
            "source_slide_id": row.source_slide_id,
            "marker": row.marker,
            "source_mds_path": str(row.source_path),
            "source_mds_size_bytes": row.source_size_bytes,
            "source_mds_sha256": row.source_sha256,
        }
        for row in records
    ]


def write_or_verify_private_linkage(
    path: Path,
    records: Sequence[ImmunoscoreSlide],
    *,
    resume: bool,
) -> None:
    rows = _private_linkage_rows(records)
    candidate = path.expanduser().absolute()
    if candidate.exists():
        if not resume or candidate.is_symlink() or not candidate.is_file():
            raise ImmunoscoreError(
                "Private linkage already exists; use --resume to verify it"
            )
        status = candidate.stat()
        if (
            stat.S_IMODE(status.st_mode) != 0o600
            or status.st_uid != os.getuid()
            or status.st_nlink != 1
        ):
            raise ImmunoscoreError(
                "Existing private linkage must be owner-controlled, "
                "single-linked, and mode 0600"
            )
        with candidate.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            existing = [dict(row) for row in reader]
        expected = [
            {field: str(row.get(field, "")) for field in PRIVATE_LINKAGE_FIELDS}
            for row in rows
        ]
        if (
            tuple(reader.fieldnames or ()) != PRIVATE_LINKAGE_FIELDS
            or existing != expected
        ):
            raise ImmunoscoreError(
                "Existing private linkage differs from discovered source WSIs"
            )
        return
    _atomic_csv(path, PRIVATE_LINKAGE_FIELDS, rows, mode=0o600)


def group_case_slides(
    records: Sequence[ImmunoscoreSlide],
) -> tuple[
    dict[str, dict[str, ImmunoscoreSlide]],
    list[dict[str, str]],
]:
    grouped: dict[str, dict[str, ImmunoscoreSlide]] = defaultdict(dict)
    for record in records:
        if record.marker in grouped[record.case_alias]:
            raise ImmunoscoreError("Duplicate public case-marker slide")
        grouped[record.case_alias][record.marker] = record
    unavailable: list[dict[str, str]] = []
    expected = set(IMMUNOSCORE_MARKERS)
    for case_alias, markers in sorted(grouped.items()):
        available = set(markers)
        missing = expected - available
        if missing:
            unavailable.append(
                {
                    "case_alias": case_alias,
                    "available_markers": ";".join(sorted(available)),
                    "missing_markers": ";".join(sorted(missing)),
                    "reason": "incomplete_serial_marker_set",
                }
            )
    return dict(grouped), unavailable


def _choose_level_for_edge(levels: Sequence[MdsLevel], maximum_edge: int) -> MdsLevel:
    candidates = [
        level for level in levels if max(level.width, level.height) >= maximum_edge
    ]
    return candidates[-1] if candidates else levels[-1]


def _choose_level_for_mpp(
    levels: Sequence[MdsLevel], source_mpp: float, target_mpp: float
) -> tuple[MdsLevel, float]:
    base_scale = float(levels[0].name)
    choices = [
        (
            abs(math.log((source_mpp * base_scale / float(level.name)) / target_mpp)),
            level,
            source_mpp * base_scale / float(level.name),
        )
        for level in levels
    ]
    _difference, level, actual_mpp = min(choices, key=lambda item: item[0])
    return level, actual_mpp


def decode_overview(
    slide: MdsPixels,
    source_mpp: float,
    maximum_edge: int,
) -> Overview:
    cv2, *_rest = ihc.require_image_dependencies()
    level = _choose_level_for_edge(slide.levels, maximum_edge)
    try:
        rgb = slide.read_level_array(level)
    except MdsReadError as exc:
        raise ImmunoscoreError(str(exc)) from exc
    original_height, original_width = rgb.shape[:2]
    scale = min(1.0, maximum_edge / max(original_width, original_height))
    if scale < 1.0:
        width = max(1, int(round(original_width * scale)))
        height = max(1, int(round(original_height * scale)))
        rgb = cv2.resize(rgb, (width, height), interpolation=cv2.INTER_AREA)
    base = slide.levels[0]
    return Overview(
        rgb=np.ascontiguousarray(rgb),
        level_index=level.index,
        level_name=level.name,
        level_width=original_width,
        level_height=original_height,
        source_width=base.width,
        source_height=base.height,
        overview_mpp_x=source_mpp * base.width / rgb.shape[1],
        overview_mpp_y=source_mpp * base.height / rgb.shape[0],
    )


def _registration_signal(rgb: np.ndarray) -> np.ndarray:
    cv2, *_rest = ihc.require_image_dependencies()
    hematoxylin, _unconstrained = ihc.separate_hematoxylin_dab(rgb)
    finite = hematoxylin[np.isfinite(hematoxylin)]
    if finite.size < 64:
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    low, high = np.percentile(finite, (2.0, 99.5))
    if high <= low:
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    normalized = np.clip((hematoxylin - low) * (255.0 / (high - low)), 0, 255)
    return normalized.astype(np.uint8)


def _tissue_dice(reference: np.ndarray, moving_warped: np.ndarray) -> float:
    intersection = int(np.count_nonzero(reference & moving_warped))
    denominator = int(np.count_nonzero(reference)) + int(
        np.count_nonzero(moving_warped)
    )
    return 2.0 * intersection / denominator if denominator else 0.0


def _bbox_affine(moving_mask: np.ndarray, reference_mask: np.ndarray) -> np.ndarray:
    def bounds(mask: np.ndarray) -> tuple[float, float, float, float]:
        y, x = np.nonzero(mask)
        if not len(x):
            raise ImmunoscoreError("Registration tissue mask is empty")
        return float(x.min()), float(y.min()), float(x.max()), float(y.max())

    mx0, my0, mx1, my1 = bounds(moving_mask)
    rx0, ry0, rx1, ry1 = bounds(reference_mask)
    sx = max(rx1 - rx0, 1.0) / max(mx1 - mx0, 1.0)
    sy = max(ry1 - ry0, 1.0) / max(my1 - my0, 1.0)
    return np.asarray(
        [[sx, 0.0, rx0 - sx * mx0], [0.0, sy, ry0 - sy * my0]],
        dtype=np.float64,
    )


def register_overviews(
    moving: Overview,
    reference: Overview,
    config: ImmunoscoreConfig,
) -> tuple[RegistrationResult, np.ndarray, np.ndarray]:
    """Register a CD3/CD8 overview onto the CK20 reference coordinate system."""
    cv2, *_rest = ihc.require_image_dependencies()
    moving_mpp = math.sqrt(moving.overview_mpp_x * moving.overview_mpp_y)
    reference_mpp = math.sqrt(reference.overview_mpp_x * reference.overview_mpp_y)
    moving_tissue = ihc.tissue_mask(moving.rgb, moving_mpp)
    reference_tissue = ihc.tissue_mask(reference.rgb, reference_mpp)
    moving_signal = _registration_signal(moving.rgb)
    reference_signal = _registration_signal(reference.rgb)
    candidates: list[tuple[np.ndarray, str, int, int]] = []

    for detector_name in ("SIFT", "ORB"):
        if detector_name == "SIFT" and hasattr(cv2, "SIFT_create"):
            detector = cv2.SIFT_create(nfeatures=5000)
            norm = cv2.NORM_L2
        elif detector_name == "ORB":
            detector = cv2.ORB_create(nfeatures=7000, fastThreshold=8)
            norm = cv2.NORM_HAMMING
        else:
            continue
        moving_keypoints, moving_descriptors = detector.detectAndCompute(
            moving_signal, moving_tissue.astype(np.uint8)
        )
        reference_keypoints, reference_descriptors = detector.detectAndCompute(
            reference_signal, reference_tissue.astype(np.uint8)
        )
        if (
            moving_descriptors is None
            or reference_descriptors is None
            or len(moving_keypoints) < 8
            or len(reference_keypoints) < 8
        ):
            continue
        matcher = cv2.BFMatcher(norm)
        raw_matches = matcher.knnMatch(moving_descriptors, reference_descriptors, k=2)
        matches = [
            pair[0]
            for pair in raw_matches
            if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance
        ]
        if len(matches) < 8:
            continue
        source_points = np.float32(
            [moving_keypoints[item.queryIdx].pt for item in matches]
        )
        target_points = np.float32(
            [reference_keypoints[item.trainIdx].pt for item in matches]
        )
        partial, partial_inliers = cv2.estimateAffinePartial2D(
            source_points,
            target_points,
            method=cv2.RANSAC,
            ransacReprojThreshold=6.0,
            maxIters=5000,
            confidence=0.995,
            refineIters=20,
        )
        full, full_inliers = cv2.estimateAffine2D(
            source_points,
            target_points,
            method=cv2.RANSAC,
            ransacReprojThreshold=6.0,
            maxIters=5000,
            confidence=0.995,
            refineIters=20,
        )
        for matrix, inlier_mask, suffix in (
            (partial, partial_inliers, "partial-affine"),
            (full, full_inliers, "affine"),
        ):
            if matrix is None or inlier_mask is None:
                continue
            inliers = int(np.count_nonzero(inlier_mask))
            candidates.append(
                (
                    np.asarray(matrix, dtype=np.float64),
                    f"{detector_name.casefold()}-{suffix}",
                    len(matches),
                    inliers,
                )
            )
    candidates.append(
        (_bbox_affine(moving_tissue, reference_tissue), "tissue-bbox", 0, 0)
    )

    scored: list[tuple[float, np.ndarray, str, int, int, float, np.ndarray]] = []
    output_size = (reference.rgb.shape[1], reference.rgb.shape[0])
    for matrix, method, matches, inliers in candidates:
        linear = matrix[:, :2]
        determinant = float(np.linalg.det(linear))
        if (
            not np.all(np.isfinite(matrix))
            or abs(determinant) < 0.05
            or abs(determinant) > 20.0
        ):
            continue
        warped = cv2.warpAffine(
            moving_tissue.astype(np.uint8),
            matrix,
            output_size,
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        ).astype(bool)
        dice = _tissue_dice(reference_tissue, warped)
        inlier_fraction = inliers / matches if matches else 0.0
        scored.append((dice, matrix, method, matches, inliers, inlier_fraction, warped))
    if not scored:
        raise ImmunoscoreError("No geometrically valid registration was found")
    dice, matrix, method, matches, inliers, inlier_fraction, warped = max(
        scored, key=lambda item: (item[0], item[5])
    )
    registered_fraction = float(np.count_nonzero(reference_tissue & warped)) / max(
        float(np.count_nonzero(reference_tissue)), 1.0
    )
    status = "pass" if dice >= config.minimum_registration_dice else "review"
    return (
        RegistrationResult(
            matrix=matrix,
            method=method,
            feature_matches=matches,
            inliers=inliers,
            inlier_fraction=inlier_fraction,
            tissue_dice=dice,
            registered_tissue_fraction=registered_fraction,
            qc_status=status,
        ),
        reference_tissue,
        warped,
    )


def _project_block_to_overview(
    block_x0: int,
    block_y0: int,
    block_width: int,
    block_height: int,
    level: MdsLevel,
    overview: Overview,
) -> tuple[int, int, int, int]:
    """Return a clipped half-open overview box for one streamed level block."""
    overview_height, overview_width = overview.rgb.shape[:2]
    scale_x, scale_y = _level_to_overview_scale(level, overview)
    x0 = max(0, int(math.floor(block_x0 * scale_x)))
    y0 = max(0, int(math.floor(block_y0 * scale_y)))
    x1 = min(
        overview_width,
        int(math.ceil((block_x0 + block_width) * scale_x)),
    )
    y1 = min(
        overview_height,
        int(math.ceil((block_y0 + block_height) * scale_y)),
    )
    return x0, y0, x1, y1


def _level_to_overview_scale(
    level: MdsLevel,
    overview: Overview,
) -> tuple[float, float]:
    """Map pyramid-level pixels to an overview without using padded extents."""
    try:
        pyramid_scale = float(overview.level_name) / float(level.name)
    except ValueError as exc:
        raise ImmunoscoreError("MDS pyramid levels must have numeric names") from exc
    if pyramid_scale <= 0:
        raise ImmunoscoreError("MDS pyramid level scale must be positive")
    resize_x = overview.rgb.shape[1] / overview.level_width
    resize_y = overview.rgb.shape[0] / overview.level_height
    return pyramid_scale * resize_x, pyramid_scale * resize_y


def ck20_compartment_masks(
    slide: MdsPixels,
    record: ImmunoscoreSlide,
    reference: Overview,
    config: ImmunoscoreConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """Stream CK20 pixels and return overview-space tissue compartments.

    Direct stain separation on a bounded WSI overview can erase focal CK20
    signal through area averaging. CK20 is therefore separated block-wise at
    a substantially finer pyramid level. The fraction of colour-checked DAB
    positive pixels in each streamed block is area-resampled into the bounded
    registration overview before morphology is applied.
    """
    cv2, _tifffile, _Image, _ImageDraw, _ndimage, _feature, sk = (
        ihc.require_image_dependencies()
    )
    _measure, morphology, _segmentation = sk
    overview_mpp = math.sqrt(reference.overview_mpp_x * reference.overview_mpp_y)
    tissue = ihc.tissue_mask(reference.rgb, overview_mpp)
    level, analysis_mpp = _choose_level_for_mpp(
        slide.levels,
        record.source_mpp,
        config.ck20_target_analysis_mpp,
    )
    projected_positive_fraction = np.zeros(tissue.shape, dtype=np.float32)
    blocks_total = 0
    blocks_with_tissue = 0
    streamed_tissue_pixels = 0
    streamed_positive_pixels = 0

    for row_start in range(0, level.rows, config.block_tiles):
        row_stop = min(level.rows, row_start + config.block_tiles)
        for column_start in range(0, level.columns, config.block_tiles):
            column_stop = min(level.columns, column_start + config.block_tiles)
            blocks_total += 1
            try:
                rgb = slide.read_tile_block(
                    level, row_start, row_stop, column_start, column_stop
                )
            except MdsReadError as exc:
                raise ImmunoscoreError(str(exc)) from exc
            streamed_tissue = ihc.tissue_mask(rgb, analysis_mpp)
            tissue_pixels = int(np.count_nonzero(streamed_tissue))
            if tissue_pixels == 0:
                continue
            blocks_with_tissue += 1
            streamed_tissue_pixels += tissue_pixels
            _h, _unconstrained, dab = ihc.separate_hematoxylin_dab_color_checked(
                rgb,
                config.minimum_dab_color_margin_od,
                config.minimum_dab_color_ratio,
            )
            positive = (dab >= config.ck20_minimum_dab_od) & streamed_tissue
            streamed_positive_pixels += int(np.count_nonzero(positive))
            block_x0 = column_start * level.tile_width
            block_y0 = row_start * level.tile_height
            height, width = rgb.shape[:2]
            overview_x0, overview_y0, overview_x1, overview_y1 = (
                _project_block_to_overview(
                    block_x0,
                    block_y0,
                    width,
                    height,
                    level,
                    reference,
                )
            )
            if overview_x1 <= overview_x0 or overview_y1 <= overview_y0:
                continue
            projected = cv2.resize(
                positive.astype(np.float32),
                (overview_x1 - overview_x0, overview_y1 - overview_y0),
                interpolation=cv2.INTER_AREA,
            )
            destination = projected_positive_fraction[
                overview_y0:overview_y1, overview_x0:overview_x1
            ]
            np.maximum(destination, projected, out=destination)

    raw_epithelium = (
        projected_positive_fraction >= config.ck20_minimum_projected_fraction
    ) & tissue
    epithelium = raw_epithelium
    minimum_pixels = max(
        4,
        int(
            round(
                config.ck20_minimum_component_um2
                / (reference.overview_mpp_x * reference.overview_mpp_y)
            )
        ),
    )
    epithelium = morphology.remove_small_objects(epithelium, minimum_pixels)
    epithelium = morphology.remove_small_holes(epithelium, max(4, minimum_pixels // 2))
    close_radius = max(1, int(round(24.0 / overview_mpp)))
    close_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * close_radius + 1,) * 2
    )
    epithelium = cv2.morphologyEx(
        epithelium.astype(np.uint8), cv2.MORPH_CLOSE, close_kernel
    ).astype(bool)
    expansion = max(
        0,
        int(round(config.ck20_epithelium_expansion_um / overview_mpp)),
    )
    if expansion:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * expansion + 1,) * 2)
        epithelium = cv2.dilate(
            epithelium.astype(np.uint8), kernel, iterations=1
        ).astype(bool)
    epithelium &= tissue
    stroma = tissue & ~epithelium
    tissue_projected = projected_positive_fraction[tissue]
    metrics = {
        "ck20_detection_method": "streamed-color-checked-dab-area-projection",
        "ck20_stream_level_index": level.index,
        "ck20_stream_level_name": level.name,
        "ck20_stream_level_width": level.width,
        "ck20_stream_level_height": level.height,
        "ck20_stream_analysis_mpp": analysis_mpp,
        "ck20_stream_blocks_total": blocks_total,
        "ck20_stream_blocks_with_tissue": blocks_with_tissue,
        "ck20_stream_tissue_pixel_count": streamed_tissue_pixels,
        "ck20_stream_dab_positive_pixel_count": streamed_positive_pixels,
        "ck20_stream_dab_positive_fraction_of_tissue": (
            streamed_positive_pixels / max(float(streamed_tissue_pixels), 1.0)
        ),
        "ck20_projected_positive_fraction_threshold": (
            config.ck20_minimum_projected_fraction
        ),
        "ck20_projected_positive_fraction_99th_percentile": (
            float(np.percentile(tissue_projected, 99.0))
            if tissue_projected.size
            else 0.0
        ),
        "ck20_projected_positive_fraction_maximum": (
            float(np.max(tissue_projected)) if tissue_projected.size else 0.0
        ),
        "ck20_raw_positive_fraction_of_tissue": (
            float(np.count_nonzero(raw_epithelium))
            / max(float(np.count_nonzero(tissue)), 1.0)
        ),
        "ck20_overview_mpp": overview_mpp,
        "ck20_minimum_component_pixels": minimum_pixels,
        "ck20_closing_radius_pixels": close_radius,
        "ck20_epithelium_expansion_pixels": expansion,
        "ck20_effective_epithelium_expansion_um_approx": expansion * overview_mpp,
        "tissue_fraction": float(np.mean(tissue)),
        "ck20_epithelium_fraction_of_tissue": (
            float(np.count_nonzero(epithelium))
            / max(float(np.count_nonzero(tissue)), 1.0)
        ),
        "ck20_stroma_fraction_of_tissue": (
            float(np.count_nonzero(stroma)) / max(float(np.count_nonzero(tissue)), 1.0)
        ),
    }
    return tissue, epithelium, stroma, metrics


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _atomic_text(path: Path, value: str, *, mode: int = 0o644) -> None:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink():
        raise ImmunoscoreError(f"Refusing symlink output: {candidate}")
    path = candidate.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _immune_segmentation_config(config: ImmunoscoreConfig) -> ihc.IHCConfig:
    """Translate the WSI settings onto the audited package IHC segmenter."""
    return ihc.IHCConfig(
        weak_dab_od=config.weak_dab_od,
        moderate_dab_od=config.moderate_dab_od,
        strong_dab_od=config.strong_dab_od,
        constrain_dab_to_expected_color=True,
        minimum_dab_color_margin_od=config.minimum_dab_color_margin_od,
        minimum_dab_color_ratio=config.minimum_dab_color_ratio,
        minimum_nucleus_area_um2=8.0,
        maximum_nucleus_area_um2=180.0,
        maximum_nucleus_eccentricity=0.995,
        minimum_peak_distance_um=2.0,
        minimum_nuclear_signal_od=0.08,
        maximum_nuclear_signal_od=0.48,
        cell_expansion_um=config.cell_expansion_um,
        minimum_tissue_fraction=0.005,
        minimum_cells_for_score=1,
    )


def _immune_positive_cells(
    nuclei: ihc.SegmentedNuclei,
    dab: np.ndarray,
    mpp: float,
    config: ImmunoscoreConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Classify expanded-nucleus objects for cytoplasmic/membranous DAB."""
    *_head, sk = ihc.require_image_dependencies()
    _measure, _morphology, segmentation = sk
    count = len(nuclei.label_ids)
    if count == 0:
        empty = np.empty(0, dtype=np.float64)
        return np.empty(0, dtype=bool), empty, empty
    expansion = max(1, int(round(config.cell_expansion_um / mpp)))
    expanded = segmentation.expand_labels(nuclei.labels, distance=expansion)
    flattened = expanded.ravel().astype(np.int64, copy=False)
    denominator = np.maximum(
        np.bincount(flattened, minlength=count + 1)[1:].astype(np.float64),
        1.0,
    )
    values = dab.ravel().astype(np.float64, copy=False)
    means = (
        np.bincount(flattened, weights=values, minlength=count + 1)[1:] / denominator
    )
    coverage = (
        np.bincount(
            flattened,
            weights=(values >= config.weak_dab_od).astype(np.float64),
            minlength=count + 1,
        )[1:]
        / denominator
    )
    positive = (means >= config.weak_dab_od) | (
        coverage >= config.positive_cell_dab_coverage
    )
    return positive, means, coverage


def _registration_row(
    case_alias: str,
    marker: str,
    result: RegistrationResult,
) -> dict[str, Any]:
    matrix = result.matrix
    return {
        "case_alias": case_alias,
        "marker": marker,
        "reference_marker": "CK20",
        "method": result.method,
        "feature_matches": result.feature_matches,
        "inliers": result.inliers,
        "inlier_fraction": result.inlier_fraction,
        "tissue_dice": result.tissue_dice,
        "registered_tissue_fraction": result.registered_tissue_fraction,
        "qc_status": result.qc_status,
        "matrix_00": matrix[0, 0],
        "matrix_01": matrix[0, 1],
        "matrix_02": matrix[0, 2],
        "matrix_10": matrix[1, 0],
        "matrix_11": matrix[1, 1],
        "matrix_12": matrix[1, 2],
    }


def apply_case_qc_policy(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Apply conservative, aggregation-safe QC to a completed case payload."""
    result = dict(payload)
    registration_rows = [dict(row) for row in payload.get("registration_rows", [])]
    compartment_rows = [dict(row) for row in payload.get("compartment_rows", [])]
    marker_details = payload.get("marker_details", {})
    fallback_markers: set[str] = set()
    zero_nucleus_markers: set[str] = set()
    ck20_compartment_degenerate = False
    ck20_metrics = payload.get("ck20_metrics", {})
    if isinstance(ck20_metrics, Mapping) and {
        "ck20_epithelium_fraction_of_tissue",
        "ck20_stroma_fraction_of_tissue",
    }.issubset(ck20_metrics):
        try:
            epithelium_fraction = float(
                ck20_metrics.get("ck20_epithelium_fraction_of_tissue", 0.0)
            )
            stroma_fraction = float(
                ck20_metrics.get("ck20_stroma_fraction_of_tissue", 0.0)
            )
            ck20_compartment_degenerate = (
                epithelium_fraction <= 0.0 or stroma_fraction <= 0.0
            )
        except (TypeError, ValueError):
            ck20_compartment_degenerate = True
    for row in registration_rows:
        marker = str(row.get("marker", ""))
        if str(row.get("method", "")) == "tissue-bbox":
            fallback_markers.add(marker)
            row["qc_status"] = "review"
    if isinstance(marker_details, Mapping):
        for marker, details in marker_details.items():
            if not isinstance(details, Mapping):
                continue
            try:
                nucleus_count = int(
                    details.get("segmented_nucleus_count_before_mapping", -1)
                )
            except (TypeError, ValueError):
                continue
            if nucleus_count == 0:
                zero_nucleus_markers.add(str(marker))
    for row in compartment_rows:
        marker = str(row.get("marker", ""))
        prior_status = str(row.get("qc_status", "review"))
        flags = {flag for flag in str(row.get("qc_flags", "")).split(";") if flag}
        if marker in fallback_markers:
            flags.add("registration_fallback_requires_review")
        if marker in zero_nucleus_markers:
            flags.add("no_segmented_nuclei")
        if ck20_compartment_degenerate:
            flags.add("degenerate_ck20_compartment")
        row["qc_flags"] = ";".join(sorted(flags))
        row["qc_status"] = "review" if flags or prior_status != "pass" else "pass"
    statuses = {
        str(row.get("qc_status", "review"))
        for row in [*registration_rows, *compartment_rows]
    }
    result["registration_rows"] = registration_rows
    result["compartment_rows"] = compartment_rows
    result["qc_status"] = "pass" if statuses == {"pass"} else "review"
    result["qc_flags"] = sorted(
        {
            flag
            for row in compartment_rows
            for flag in str(row.get("qc_flags", "")).split(";")
            if flag
        }
    )
    result["qc_policy_version"] = IMMUNOSCORE_QC_POLICY_VERSION
    return result


def quantify_immune_slide(
    slide: MdsPixels,
    record: ImmunoscoreSlide,
    moving_overview: Overview,
    reference_overview: Overview,
    registration: RegistrationResult,
    reference_tissue: np.ndarray,
    epithelium: np.ndarray,
    stroma: np.ndarray,
    warped_moving_tissue: np.ndarray,
    config: ImmunoscoreConfig,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Stream one CD3/CD8 WSI and map positive-cell centroids onto CK20."""
    cv2, *_head, sk = ihc.require_image_dependencies()
    _measure, _morphology, _segmentation = sk
    level, analysis_mpp = _choose_level_for_mpp(
        slide.levels, record.source_mpp, config.target_analysis_mpp
    )
    segmentation_config = _immune_segmentation_config(config)
    margin = max(1, int(round(config.block_boundary_exclusion_um / analysis_mpp)))
    level_to_overview_x, level_to_overview_y = _level_to_overview_scale(
        level, moving_overview
    )
    moving_valid_overview = np.zeros(moving_overview.rgb.shape[:2], dtype=bool)
    all_nucleus_x: list[np.ndarray] = []
    all_nucleus_y: list[np.ndarray] = []
    positive_x: list[np.ndarray] = []
    positive_y: list[np.ndarray] = []
    blocks_total = 0
    blocks_with_tissue = 0
    total_nuclei = 0
    total_positive = 0
    dab_means: list[float] = []
    dab_coverages: list[float] = []

    for row_start in range(0, level.rows, config.block_tiles):
        row_stop = min(level.rows, row_start + config.block_tiles)
        for column_start in range(0, level.columns, config.block_tiles):
            column_stop = min(level.columns, column_start + config.block_tiles)
            blocks_total += 1
            try:
                rgb = slide.read_tile_block(
                    level, row_start, row_stop, column_start, column_stop
                )
            except MdsReadError as exc:
                raise ImmunoscoreError(str(exc)) from exc
            block_x0 = column_start * level.tile_width
            block_y0 = row_start * level.tile_height
            height, width = rgb.shape[:2]
            analysis_x0 = block_x0 + margin
            analysis_y0 = block_y0 + margin
            analysis_x1 = block_x0 + width - margin
            analysis_y1 = block_y0 + height - margin
            overview_x0 = max(
                0,
                int(math.floor(analysis_x0 * level_to_overview_x)),
            )
            overview_y0 = max(
                0,
                int(math.floor(analysis_y0 * level_to_overview_y)),
            )
            overview_x1 = min(
                moving_overview.rgb.shape[1],
                int(math.ceil(analysis_x1 * level_to_overview_x)),
            )
            overview_y1 = min(
                moving_overview.rgb.shape[0],
                int(math.ceil(analysis_y1 * level_to_overview_y)),
            )
            if overview_x1 > overview_x0 and overview_y1 > overview_y0:
                moving_valid_overview[
                    overview_y0:overview_y1, overview_x0:overview_x1
                ] = True
            tissue = ihc.tissue_mask(rgb, analysis_mpp)
            if float(np.mean(tissue)) < segmentation_config.minimum_tissue_fraction:
                continue
            blocks_with_tissue += 1
            hematoxylin, _unconstrained, dab = (
                ihc.separate_hematoxylin_dab_color_checked(
                    rgb,
                    config.minimum_dab_color_margin_od,
                    config.minimum_dab_color_ratio,
                )
            )
            nuclei = ihc.segment_nuclei(
                hematoxylin,
                dab,
                tissue,
                record.marker,
                analysis_mpp,
                segmentation_config,
            )
            if len(nuclei.label_ids) == 0:
                continue
            positive, means, coverage = _immune_positive_cells(
                nuclei, dab, analysis_mpp, config
            )
            keep = (
                (nuclei.centroid_x >= margin)
                & (nuclei.centroid_y >= margin)
                & (nuclei.centroid_x < width - margin)
                & (nuclei.centroid_y < height - margin)
            )
            if not np.any(keep):
                continue
            global_x = nuclei.centroid_x[keep] + block_x0
            global_y = nuclei.centroid_y[keep] + block_y0
            kept_positive = positive[keep]
            all_nucleus_x.append(global_x)
            all_nucleus_y.append(global_y)
            positive_x.append(global_x[kept_positive])
            positive_y.append(global_y[kept_positive])
            total_nuclei += int(np.count_nonzero(keep))
            total_positive += int(np.count_nonzero(kept_positive))
            if np.any(kept_positive):
                dab_means.extend(means[keep][kept_positive].tolist())
                dab_coverages.extend(coverage[keep][kept_positive].tolist())

    output_size = (
        reference_overview.rgb.shape[1],
        reference_overview.rgb.shape[0],
    )
    warped_valid = cv2.warpAffine(
        moving_valid_overview.astype(np.uint8),
        registration.matrix,
        output_size,
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    ).astype(bool)
    common_tissue = reference_tissue & warped_moving_tissue & warped_valid
    compartment_masks = {
        "ck20_epithelium_proxy": common_tissue & epithelium,
        "ck20_stroma_proxy": common_tissue & stroma,
        "common_tissue": common_tissue,
    }
    reference_pixel_area_mm2 = (
        reference_overview.overview_mpp_x
        * reference_overview.overview_mpp_y
        / 1_000_000.0
    )

    def mapped_coordinates(
        x_parts: Sequence[np.ndarray], y_parts: Sequence[np.ndarray]
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if not x_parts:
            empty = np.empty(0, dtype=np.int64)
            return empty, empty, np.empty(0, dtype=bool)
        x = np.concatenate(x_parts)
        y = np.concatenate(y_parts)
        overview_x = x * level_to_overview_x
        overview_y = y * level_to_overview_y
        mapped_x = (
            registration.matrix[0, 0] * overview_x
            + registration.matrix[0, 1] * overview_y
            + registration.matrix[0, 2]
        )
        mapped_y = (
            registration.matrix[1, 0] * overview_x
            + registration.matrix[1, 1] * overview_y
            + registration.matrix[1, 2]
        )
        pixel_x = np.rint(mapped_x).astype(np.int64)
        pixel_y = np.rint(mapped_y).astype(np.int64)
        inside = (
            (pixel_x >= 0)
            & (pixel_y >= 0)
            & (pixel_x < output_size[0])
            & (pixel_y < output_size[1])
        )
        return pixel_x, pixel_y, inside

    nuclei_x, nuclei_y, nuclei_inside = mapped_coordinates(all_nucleus_x, all_nucleus_y)
    pos_x, pos_y, pos_inside = mapped_coordinates(positive_x, positive_y)
    mapped_positive = 0
    if np.any(pos_inside):
        mapped_positive = int(
            np.count_nonzero(common_tissue[pos_y[pos_inside], pos_x[pos_inside]])
        )
    mapped_fraction = mapped_positive / total_positive if total_positive else 1.0
    base_flags: list[str] = []
    if registration.qc_status != "pass":
        base_flags.append("registration_requires_review")
    if mapped_fraction < 0.50:
        base_flags.append("low_positive_cell_mapping_fraction")

    rows: list[dict[str, Any]] = []
    for name, mask in compartment_masks.items():
        area = float(np.count_nonzero(mask)) * reference_pixel_area_mm2
        nucleus_count = 0
        positive_count = 0
        if np.any(nuclei_inside):
            nucleus_count = int(
                np.count_nonzero(mask[nuclei_y[nuclei_inside], nuclei_x[nuclei_inside]])
            )
        if np.any(pos_inside):
            positive_count = int(
                np.count_nonzero(mask[pos_y[pos_inside], pos_x[pos_inside]])
            )
        flags = list(base_flags)
        if area < config.minimum_tissue_area_mm2:
            flags.append("analyzed_area_below_minimum")
        status = "pass" if not flags else "review"
        rows.append(
            {
                "case_alias": record.case_alias,
                "marker": record.marker,
                "compartment": name,
                "positive_cell_count": positive_count,
                "segmented_nucleus_count": nucleus_count,
                "analyzed_area_mm2": area,
                "positive_cell_density_per_mm2": (
                    positive_count / area if area > 0 else ""
                ),
                "mapped_positive_cell_fraction": mapped_fraction,
                "analysis_mpp": analysis_mpp,
                "registration_tissue_dice": registration.tissue_dice,
                "qc_status": status,
                "qc_flags": ";".join(sorted(set(flags))),
            }
        )
    details = {
        "analysis_level_index": level.index,
        "analysis_level_name": level.name,
        "analysis_level_width": level.width,
        "analysis_level_height": level.height,
        "analysis_mpp": analysis_mpp,
        "blocks_total": blocks_total,
        "blocks_with_tissue": blocks_with_tissue,
        "segmented_nucleus_count_before_mapping": total_nuclei,
        "positive_cell_count_before_mapping": total_positive,
        "mapped_positive_cell_count": mapped_positive,
        "mapped_positive_cell_fraction": mapped_fraction,
        "positive_cell_mean_expanded_dab_od": (
            float(np.mean(dab_means)) if dab_means else ""
        ),
        "positive_cell_mean_dab_coverage": (
            float(np.mean(dab_coverages)) if dab_coverages else ""
        ),
        "positive_rule": (
            "expanded-cell mean DAB >= weak_dab_od OR fraction of expanded-cell "
            "pixels >= weak_dab_od is at least positive_cell_dab_coverage"
        ),
        "block_boundary_exclusion_um": config.block_boundary_exclusion_um,
    }
    return rows, details


def write_registration_qc(
    path: Path,
    reference: Overview,
    epithelium: np.ndarray,
    stroma: np.ndarray,
    moving: Mapping[str, tuple[Overview, RegistrationResult]],
    case_alias: str,
) -> None:
    """Write a PHI-free four-panel overview registration audit image."""
    cv2, _tifffile, Image, ImageDraw, *_rest = ihc.require_image_dependencies()
    output_size = (reference.rgb.shape[1], reference.rgb.shape[0])
    compartments = reference.rgb.astype(np.float32)
    epi_color = np.asarray([30, 170, 75], dtype=np.float32)
    stroma_color = np.asarray([230, 145, 40], dtype=np.float32)
    compartments[epithelium] = 0.45 * compartments[epithelium] + 0.55 * epi_color
    compartments[stroma] = 0.72 * compartments[stroma] + 0.28 * stroma_color
    panels: list[tuple[str, np.ndarray]] = [
        ("CK20 reference", reference.rgb),
        (
            "CK20 green=epithelium proxy; orange=stroma proxy",
            compartments.astype(np.uint8),
        ),
    ]
    for marker in IMMUNE_MARKERS:
        overview, registration = moving[marker]
        warped = cv2.warpAffine(
            overview.rgb,
            registration.matrix,
            output_size,
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(255, 255, 255),
        )
        blend = cv2.addWeighted(reference.rgb, 0.50, warped, 0.50, 0)
        panels.append(
            (
                f"{marker}→CK20 | {registration.method} | "
                f"tissue Dice={registration.tissue_dice:.3f} | "
                f"{registration.qc_status}",
                blend,
            )
        )

    rendered: list[Any] = []
    for title, array in panels:
        scale = min(1.0, 900.0 / max(array.shape[:2]))
        width = max(1, int(round(array.shape[1] * scale)))
        height = max(1, int(round(array.shape[0] * scale)))
        resized = cv2.resize(array, (width, height), interpolation=cv2.INTER_AREA)
        panel = Image.new("RGB", (900, 950), "white")
        image = Image.fromarray(resized, mode="RGB")
        panel.paste(image, ((900 - width) // 2, 42 + (900 - height) // 2))
        draw = ImageDraw.Draw(panel)
        draw.text((12, 12), title, fill=(20, 20, 20))
        rendered.append(panel)
    canvas = Image.new("RGB", (1800, 1940), "white")
    for index, panel in enumerate(rendered):
        canvas.paste(panel, ((index % 2) * 900, (index // 2) * 950))
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (12, 1910),
        f"{case_alias} | research-use serial-section QC; visual review required",
        fill=(20, 20, 20),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".png", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        canvas.save(temporary, format="PNG", optimize=True)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def process_case(
    case_alias: str,
    slides: Mapping[str, ImmunoscoreSlide],
    output_root: Path,
    config: ImmunoscoreConfig,
    *,
    save_qc: bool,
    resume: bool,
) -> dict[str, Any]:
    """Process one complete CK20/CD3/CD8 serial-section case."""
    case_directory = output_root / "cases" / case_alias
    result_path = case_directory / "measurement.json"
    qc_path = case_directory / "registration_qc.png"
    ck20_record = slides["CK20"]
    if resume and result_path.is_file():
        try:
            existing = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        if (
            existing.get("completion_status") == "completed"
            and existing.get("analysis_signature") == config.signature()
            and (not save_qc or qc_path.is_file())
        ):
            if not isinstance(existing.get("reference_overview"), Mapping):
                with MdsPixels(ck20_record.source_path) as ck20_slide:
                    reference = decode_overview(
                        ck20_slide,
                        ck20_record.source_mpp,
                        config.overview_max_edge,
                    )
                existing["reference_overview"] = _overview_metadata(reference)
            reference_metadata = existing["reference_overview"]
            ck20_metrics = existing.get("ck20_metrics")
            if isinstance(reference_metadata, Mapping) and isinstance(
                ck20_metrics, Mapping
            ):
                ck20_metrics = dict(ck20_metrics)
                mpp = math.sqrt(
                    float(reference_metadata["overview_mpp_x"])
                    * float(reference_metadata["overview_mpp_y"])
                )
                minimum_pixels = max(
                    4,
                    int(round(config.ck20_minimum_component_um2 / (mpp * mpp))),
                )
                expansion = max(
                    0,
                    int(round(config.ck20_epithelium_expansion_um / mpp)),
                )
                ck20_metrics.update(
                    {
                        "ck20_overview_mpp": mpp,
                        "ck20_minimum_component_pixels": minimum_pixels,
                        "ck20_closing_radius_pixels": max(1, int(round(24.0 / mpp))),
                        "ck20_epithelium_expansion_pixels": expansion,
                        "ck20_effective_epithelium_expansion_um_approx": (
                            expansion * mpp
                        ),
                    }
                )
                existing["ck20_metrics"] = ck20_metrics
            details = existing.get("marker_details")
            if isinstance(details, Mapping):
                details = {
                    key: dict(value) if isinstance(value, Mapping) else {}
                    for key, value in details.items()
                }
                for marker in IMMUNE_MARKERS:
                    marker_detail = details.get(marker, {})
                    if not isinstance(marker_detail, Mapping):
                        marker_detail = {}
                    marker_detail = dict(marker_detail)
                    if not isinstance(
                        marker_detail.get("registration_overview"), Mapping
                    ):
                        record = slides[marker]
                        with MdsPixels(record.source_path) as immune_slide:
                            overview = decode_overview(
                                immune_slide,
                                record.source_mpp,
                                config.overview_max_edge,
                            )
                        marker_detail["registration_overview"] = _overview_metadata(
                            overview
                        )
                    details[marker] = marker_detail
                existing["marker_details"] = details
            reviewed = apply_case_qc_policy(existing)
            if reviewed != existing:
                _atomic_json(result_path, reviewed)
            return {**reviewed, "resume_reused": True}

    with MdsPixels(ck20_record.source_path) as ck20_slide:
        reference = decode_overview(
            ck20_slide, ck20_record.source_mpp, config.overview_max_edge
        )
        reference_tissue, epithelium, stroma, ck20_metrics = ck20_compartment_masks(
            ck20_slide,
            ck20_record,
            reference,
            config,
        )
    registration_rows: list[dict[str, Any]] = []
    compartment_rows: list[dict[str, Any]] = []
    marker_details: dict[str, Any] = {}
    moving_qc: dict[str, tuple[Overview, RegistrationResult]] = {}
    for marker in IMMUNE_MARKERS:
        record = slides[marker]
        with MdsPixels(record.source_path) as immune_slide:
            moving_overview = decode_overview(
                immune_slide, record.source_mpp, config.overview_max_edge
            )
            registration, registered_reference_tissue, warped_tissue = (
                register_overviews(moving_overview, reference, config)
            )
            rows, details = quantify_immune_slide(
                immune_slide,
                record,
                moving_overview,
                reference,
                registration,
                registered_reference_tissue,
                epithelium,
                stroma,
                warped_tissue,
                config,
            )
        registration_rows.append(_registration_row(case_alias, marker, registration))
        compartment_rows.extend(rows)
        details["registration_overview"] = _overview_metadata(moving_overview)
        marker_details[marker] = details
        moving_qc[marker] = (moving_overview, registration)

    statuses = {
        str(row["qc_status"]) for row in [*registration_rows, *compartment_rows]
    }
    case_status = "pass" if statuses == {"pass"} else "review"
    flags = sorted(
        {
            flag
            for row in compartment_rows
            for flag in str(row.get("qc_flags", "")).split(";")
            if flag
        }
    )
    if save_qc:
        write_registration_qc(
            qc_path,
            reference,
            epithelium,
            stroma,
            moving_qc,
            case_alias,
        )
    payload = {
        "schema_version": IMMUNOSCORE_SCHEMA_VERSION,
        "engine_version": IMMUNOSCORE_ENGINE_VERSION,
        "analysis_signature": config.signature(),
        "completion_status": "completed",
        "case_alias": case_alias,
        "reference_marker": "CK20",
        "compartment_definition": (
            "CK20-positive epithelial proxy versus CK20-negative tissue/stromal "
            "proxy on the registered CK20 serial section"
        ),
        "ck20_metrics": ck20_metrics,
        "reference_overview": _overview_metadata(reference),
        "registration_rows": registration_rows,
        "compartment_rows": compartment_rows,
        "marker_details": marker_details,
        "qc_status": case_status,
        "qc_flags": flags,
        "registration_qc_image": (
            str(qc_path.relative_to(output_root)) if save_qc else ""
        ),
        "consensus_immunoscore": None,
        "consensus_immunoscore_status": (
            "unavailable_requires_pathologist_validated_CT_IM_and_external_reference"
        ),
    }
    payload = apply_case_qc_policy(payload)
    _atomic_json(result_path, payload)
    return payload


def _process_case_task(task: tuple[Any, ...]) -> dict[str, Any]:
    case_alias, slides, output_root, config, save_qc, resume = task
    return process_case(
        case_alias,
        slides,
        output_root,
        config,
        save_qc=save_qc,
        resume=resume,
    )


def _empirical_percentiles(values: Mapping[str, float]) -> dict[str, float]:
    """Return deterministic mid-rank percentiles within this analysis cohort."""
    result: dict[str, float] = {}
    count = len(values)
    if not count:
        return result
    for case_alias, value in values.items():
        less = sum(candidate < value for candidate in values.values())
        equal = sum(candidate == value for candidate in values.values())
        result[case_alias] = 100.0 * (less + 0.5 * equal) / count
    return result


def _cohort_density_summary(
    value_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Summarize numeric research densities under explicit QC populations."""
    populations = (
        ("automatic_qc_pass", {"pass"}),
        ("all_numerically_available", {"pass", "review"}),
    )
    rows: list[dict[str, Any]] = []
    for population, statuses in populations:
        for field in CASE_DENSITY_FIELDS:
            values: list[float] = []
            for row in value_rows:
                if str(row.get("qc_status", "")) not in statuses:
                    continue
                raw = row.get(field, "")
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(value):
                    values.append(value)
            array = np.asarray(values, dtype=np.float64)
            rows.append(
                {
                    "analysis_population": population,
                    "measurement": field,
                    "unit": "positive cells/mm2",
                    "n": len(values),
                    "mean": float(np.mean(array)) if len(array) else "",
                    "sample_standard_deviation": (
                        float(np.std(array, ddof=1)) if len(array) > 1 else ""
                    ),
                    "median": float(np.median(array)) if len(array) else "",
                    "first_quartile": (
                        float(np.quantile(array, 0.25)) if len(array) else ""
                    ),
                    "third_quartile": (
                        float(np.quantile(array, 0.75)) if len(array) else ""
                    ),
                    "minimum": float(np.min(array)) if len(array) else "",
                    "maximum": float(np.max(array)) if len(array) else "",
                }
            )
    return rows


def _write_report(
    output_root: Path,
    value_rows: Sequence[Mapping[str, Any]],
    density_summary_rows: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> Path:
    table_rows = []
    for row in value_rows:
        table_rows.append(
            "<tr>"
            + "".join(
                f"<td>{html.escape(str(row.get(field, '')))}</td>"
                for field in CASE_VALUE_FIELDS
            )
            + "</tr>"
        )
    summary_table_rows = []
    for row in density_summary_rows:
        summary_table_rows.append(
            "<tr>"
            + "".join(
                f"<td>{html.escape(str(row.get(field, '')))}</td>"
                for field in COHORT_DENSITY_SUMMARY_FIELDS
            )
            + "</tr>"
        )
    report = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TumorQuantAI CK20-guided CD3/CD8 report</title>
<style>
body{{font:16px/1.55 system-ui,sans-serif;color:#19222d;background:#f4f6f8;margin:0}}
main{{max-width:1500px;margin:auto;padding:28px}} h1,h2{{line-height:1.15}}
.warning{{border-left:6px solid #b33b2e;background:#fff0ed;padding:14px 18px}}
.panel{{background:white;border:1px solid #d9e0e6;border-radius:10px;padding:18px;margin:18px 0}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}}
.metric{{background:#edf4f7;border-radius:8px;padding:12px}} table{{border-collapse:collapse;font-size:12px}}
th,td{{border:1px solid #ccd5dc;padding:6px;text-align:right;white-space:nowrap}} th:first-child,td:first-child{{text-align:left}}
.scroll{{overflow:auto}} code{{background:#edf0f2;padding:2px 4px}}
</style></head><body><main>
<h1>CK20-guided CD3/CD8 WSI quantification</h1>
<p class="warning"><strong>Research proxy—not clinical Immunoscore.</strong>
TumorQuantAI registered serial CD3 and CD8 sections to CK20, then measured
DAB-positive cell densities in a CK20-positive epithelial proxy and a
CK20-negative tissue/stromal proxy. CK20 expression is differentiation-linked
and spatially variable, so it cannot define the entire invasive boundary. No
pathologist-validated tumour core (CT), invasive margin (IM),
or validated external reference distribution was supplied; therefore the
consensus Immunoscore is deliberately reported as unavailable.</p>
<section class="panel"><h2>Run summary</h2><div class="metrics">
<div class="metric"><strong>{summary['discovered_case_count']}</strong><br>source cases</div>
<div class="metric"><strong>{summary['complete_case_count']}</strong><br>complete CD3/CD8/CK20 sets</div>
<div class="metric"><strong>{summary['completed_case_count']}</strong><br>processed cases</div>
<div class="metric"><strong>{summary['pass_case_count']}</strong><br>automatic QC pass</div>
<div class="metric"><strong>{summary['review_case_count']}</strong><br>require review</div>
<div class="metric"><strong>{summary['failed_case_count']}</strong><br>failed</div>
</div></section>
<section class="panel"><h2>Open these first</h2>
<p><a href="tables/tumorquantai_immunoscore_values.csv">Clear case values</a> ·
<a href="tables/cohort_density_summary.csv">Cohort density summary</a> ·
<a href="tables/case_compartment_densities.csv">Long compartment densities</a> ·
<a href="tables/registration_qc.csv">Registration QC</a> ·
<a href="tables/unavailable_cases.csv">Unavailable cases</a> ·
<a href="workflow_metadata/immunoscore_run.json">Methods and provenance</a></p>
<p>Each completed case also has a registration composite under
<code>cases/CASE_ALIAS/registration_qc.png</code>. Review those images before
interpreting any density.</p></section>
<section class="panel"><h2>Cohort density summary</h2>
<p><code>automatic_qc_pass</code> excludes every review, failed, and incomplete
case. <code>all_numerically_available</code> adds review-status cases but still
excludes failed and incomplete cases. Standard deviation is the sample SD.</p>
<div class="scroll"><table><thead><tr>
{''.join(f'<th>{html.escape(field)}</th>' for field in COHORT_DENSITY_SUMMARY_FIELDS)}
</tr></thead><tbody>{''.join(summary_table_rows)}</tbody></table></div></section>
<section class="panel"><h2>Case values</h2><div class="scroll"><table>
<thead><tr>{''.join(f'<th>{html.escape(field)}</th>' for field in CASE_VALUE_FIELDS)}</tr></thead>
<tbody>{''.join(table_rows)}</tbody></table></div></section>
<section class="panel"><h2>Interpretation boundaries</h2>
<ul><li>The four reported density variables are TumorQuantAI research outputs.</li>
<li>Internal percentiles rank only automatic-QC-pass cases in this cohort and
must not be substituted for the validated 700-case reference population.</li>
<li>The low/intermediate/high internal rank label uses 25/70 cut points only to
summarize this cohort; it is not the consensus clinical classification.</li>
<li>Serial-section registration and CK20 compartment masks require pathologist
review. A low count may represent biology, staining, registration, or segmentation.</li>
</ul></section>
</main></body></html>
"""
    path = output_root / "START_HERE.html"
    _atomic_text(path, report)
    return path


def aggregate_results(
    output_root: Path,
    grouped: Mapping[str, Mapping[str, ImmunoscoreSlide]],
    complete: Mapping[str, Mapping[str, ImmunoscoreSlide]],
    unavailable: Sequence[Mapping[str, str]],
    case_results: Sequence[Mapping[str, Any]],
    failures: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    case_results = [apply_case_qc_policy(result) for result in case_results]
    tables = output_root / "tables"
    registration_rows = [
        dict(row)
        for result in case_results
        for row in result.get("registration_rows", [])
    ]
    compartment_rows = [
        dict(row)
        for result in case_results
        for row in result.get("compartment_rows", [])
    ]
    _atomic_csv(tables / "registration_qc.csv", REGISTRATION_FIELDS, registration_rows)
    _atomic_csv(
        tables / "case_compartment_densities.csv",
        COMPARTMENT_FIELDS,
        compartment_rows,
    )

    result_by_case = {str(result["case_alias"]): result for result in case_results}
    density_keys = {
        (
            "CD3",
            "ck20_epithelium_proxy",
        ): "tumorquantai_cd3_ck20_epithelium_density_per_mm2",
        ("CD3", "ck20_stroma_proxy"): "tumorquantai_cd3_ck20_stroma_density_per_mm2",
        (
            "CD8",
            "ck20_epithelium_proxy",
        ): "tumorquantai_cd8_ck20_epithelium_density_per_mm2",
        ("CD8", "ck20_stroma_proxy"): "tumorquantai_cd8_ck20_stroma_density_per_mm2",
    }
    densities_by_case: dict[str, dict[str, Any]] = defaultdict(dict)
    for row in compartment_rows:
        key = density_keys.get((str(row["marker"]), str(row["compartment"])))
        if key is not None:
            densities_by_case[str(row["case_alias"])][key] = row[
                "positive_cell_density_per_mm2"
            ]

    passing = {
        case_alias
        for case_alias, result in result_by_case.items()
        if result.get("qc_status") == "pass"
        and all(key in densities_by_case[case_alias] for key in density_keys.values())
    }
    percentile_fields = {
        "tumorquantai_cd3_ck20_epithelium_density_per_mm2": "cd3_ck20_epithelium_internal_percentile",
        "tumorquantai_cd3_ck20_stroma_density_per_mm2": "cd3_ck20_stroma_internal_percentile",
        "tumorquantai_cd8_ck20_epithelium_density_per_mm2": "cd8_ck20_epithelium_internal_percentile",
        "tumorquantai_cd8_ck20_stroma_density_per_mm2": "cd8_ck20_stroma_internal_percentile",
    }
    percentile_maps: dict[str, dict[str, float]] = {}
    for density_field, percentile_field in percentile_fields.items():
        percentile_maps[percentile_field] = _empirical_percentiles(
            {
                case_alias: float(densities_by_case[case_alias][density_field])
                for case_alias in passing
            }
        )

    failed_aliases = {str(row["case_alias"]) for row in failures}
    incomplete_aliases = set(grouped) - set(complete)
    value_rows: list[dict[str, Any]] = []
    for case_alias in sorted(grouped):
        result = result_by_case.get(case_alias, {})
        row: dict[str, Any] = {field: "" for field in CASE_VALUE_FIELDS}
        row["case_alias"] = case_alias
        row.update(densities_by_case.get(case_alias, {}))
        row["consensus_immunoscore"] = ""
        row["consensus_immunoscore_status"] = (
            "unavailable_requires_pathologist_validated_CT_IM_and_external_reference"
        )
        if case_alias in incomplete_aliases:
            row["qc_status"] = "unavailable"
            row["qc_flags"] = "incomplete_serial_marker_set"
        elif case_alias in failed_aliases:
            row["qc_status"] = "failed"
            row["qc_flags"] = "analysis_failed"
        else:
            row["qc_status"] = result.get("qc_status", "failed")
            row["qc_flags"] = ";".join(result.get("qc_flags", []))
        if case_alias in passing:
            percentiles = [
                percentile_maps[field][case_alias]
                for field in percentile_fields.values()
            ]
            for field, value in zip(percentile_fields.values(), percentiles):
                row[field] = value
            mean_percentile = float(np.mean(percentiles))
            row["ck20_guided_internal_mean_percentile"] = mean_percentile
            row["ck20_guided_internal_rank_group"] = (
                "low"
                if mean_percentile <= 25.0
                else "intermediate" if mean_percentile <= 70.0 else "high"
            )
        elif case_alias not in incomplete_aliases and case_alias not in failed_aliases:
            row["ck20_guided_internal_rank_group"] = "not_ranked_due_to_qc"
        value_rows.append(row)
    _atomic_csv(
        tables / "tumorquantai_immunoscore_values.csv",
        CASE_VALUE_FIELDS,
        value_rows,
    )
    density_summary_rows = _cohort_density_summary(value_rows)
    _atomic_csv(
        tables / "cohort_density_summary.csv",
        COHORT_DENSITY_SUMMARY_FIELDS,
        density_summary_rows,
    )

    unavailable_rows = [dict(row) for row in unavailable]
    unavailable_rows.extend(
        {
            "case_alias": str(row["case_alias"]),
            "available_markers": "CD3;CD8;CK20",
            "missing_markers": "",
            "reason": "analysis_failed",
        }
        for row in failures
    )
    _atomic_csv(
        tables / "unavailable_cases.csv",
        UNAVAILABLE_FIELDS,
        sorted(unavailable_rows, key=lambda row: str(row["case_alias"])),
    )
    statuses = Counter(
        str(result.get("qc_status", "failed")) for result in case_results
    )
    summary = {
        "discovered_case_count": len(grouped),
        "complete_case_count": len(complete),
        "incomplete_case_count": len(grouped) - len(complete),
        "completed_case_count": len(case_results),
        "pass_case_count": statuses["pass"],
        "review_case_count": statuses["review"],
        "failed_case_count": len(failures),
    }
    report = _write_report(output_root, value_rows, density_summary_rows, summary)
    return {
        **summary,
        "report_path": str(report.relative_to(output_root)),
    }


def run_immunoscore(
    input_root: Path,
    output_root: Path,
    alias_secret: Path,
    private_linkage: Path,
    config: ImmunoscoreConfig,
    *,
    workers: int = 1,
    source_mpp: float | None = None,
    save_qc: bool = True,
    resume: bool = True,
    fail_fast: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Discover, anonymize, quantify, aggregate, and report a colon WSI cohort."""
    config.validate()
    if workers < 1 or workers > 8:
        raise ImmunoscoreError("Workers must be between 1 and 8")
    input_candidate = input_root.expanduser().absolute()
    if input_candidate.is_symlink():
        raise ImmunoscoreError("Immunoscore input must not be a symlink")
    input_root = input_candidate.resolve()
    output_candidate = output_root.expanduser().absolute()
    if output_candidate.is_symlink():
        raise ImmunoscoreError("Immunoscore output must not be a symlink")
    output_root = output_candidate.resolve()
    alias_secret_candidate = alias_secret.expanduser().absolute()
    if alias_secret_candidate.is_symlink():
        raise ImmunoscoreError("Alias secret must not be a symlink")
    alias_secret = alias_secret_candidate.resolve()
    private_linkage = private_linkage.expanduser().absolute()
    if private_linkage.is_symlink():
        raise ImmunoscoreError("Private linkage must not be a symlink")
    if (
        output_root == input_root
        or input_root in output_root.parents
        or output_root in input_root.parents
    ):
        raise ImmunoscoreError("Input and output directories must be disjoint")
    if output_root == alias_secret or output_root in alias_secret.parents:
        raise ImmunoscoreError("Alias secret must remain outside the result directory")
    try:
        private_linkage.relative_to(output_root)
    except ValueError:
        pass
    else:
        raise ImmunoscoreError(
            "Private linkage must remain outside the result directory"
        )

    records = discover_mds_slides(input_root, alias_secret, source_mpp=source_mpp)
    grouped, unavailable = group_case_slides(records)
    complete = {
        case_alias: markers
        for case_alias, markers in grouped.items()
        if set(markers) == set(IMMUNOSCORE_MARKERS)
    }
    plan = {
        "schema_version": IMMUNOSCORE_SCHEMA_VERSION,
        "mode": "dry_run" if dry_run else "analysis",
        "discovered_slide_count": len(records),
        "discovered_case_count": len(grouped),
        "complete_case_count": len(complete),
        "incomplete_case_count": len(grouped) - len(complete),
        "marker_slide_counts": dict(
            sorted(Counter(record.marker for record in records).items())
        ),
        "source_mpp_values": sorted({record.source_mpp for record in records}),
        "target_analysis_mpp": config.target_analysis_mpp,
        "consensus_immunoscore_status": (
            "unavailable_requires_pathologist_validated_CT_IM_and_external_reference"
        ),
    }
    if dry_run:
        return plan

    if output_root.exists() and not output_root.is_dir():
        raise ImmunoscoreError("Output exists but is not a directory")
    if output_root.is_dir() and any(output_root.iterdir()):
        manifest = output_root / "workflow_metadata/immunoscore_run.json"
        if not resume or not manifest.is_file():
            raise ImmunoscoreError(
                "Non-empty output is not a resumable Immunoscore result directory"
            )
    records = add_source_digests(records)
    grouped, unavailable = group_case_slides(records)
    complete = {
        case_alias: markers
        for case_alias, markers in grouped.items()
        if set(markers) == set(IMMUNOSCORE_MARKERS)
    }
    write_or_verify_private_linkage(private_linkage, records, resume=resume)
    output_root.mkdir(parents=True, exist_ok=True)
    _atomic_csv(
        output_root / "tables/public_slide_inventory.csv",
        PUBLIC_SLIDE_FIELDS,
        [record.public_row() for record in records],
    )

    tasks = [
        (
            case_alias,
            markers,
            output_root,
            config,
            save_qc,
            resume,
        )
        for case_alias, markers in sorted(complete.items())
    ]
    case_results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    def collect(
        case_alias: str, result: dict[str, Any] | None, error: Exception | None
    ) -> None:
        if error is None and result is not None:
            case_results.append(result)
            print(
                f"Immunoscore proxy case {case_alias}: "
                f"{result.get('qc_status', 'completed')}",
                flush=True,
            )
            return
        failures.append(
            {
                "case_alias": case_alias,
                "error_type": type(error).__name__ if error else "UnknownError",
                "error_message": (
                    "Case analysis failed; no clinical interpretation is available."
                ),
            }
        )
        print(f"Immunoscore proxy case {case_alias}: failed", flush=True)

    if workers == 1:
        for task in tasks:
            case_alias = str(task[0])
            try:
                collect(case_alias, _process_case_task(task), None)
            except Exception as exc:
                collect(case_alias, None, exc)
                if fail_fast:
                    raise
    else:
        with ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as executor:
            futures = {
                executor.submit(_process_case_task, task): str(task[0])
                for task in tasks
            }
            for future in as_completed(futures):
                case_alias = futures[future]
                try:
                    collect(case_alias, future.result(), None)
                except Exception as exc:
                    collect(case_alias, None, exc)
                    if fail_fast:
                        for pending in futures:
                            pending.cancel()
                        raise
    case_results.sort(key=lambda row: str(row["case_alias"]))
    summary = aggregate_results(
        output_root,
        grouped,
        complete,
        unavailable,
        case_results,
        failures,
    )
    metadata = {
        **plan,
        **summary,
        "created_utc": _utc_now(),
        "engine_version": IMMUNOSCORE_ENGINE_VERSION,
        "qc_policy_version": IMMUNOSCORE_QC_POLICY_VERSION,
        "analysis_signature": config.signature(),
        "settings": asdict(config),
        "workers": workers,
        "source_format": "Motic MDS; DSI0 pixel streams only",
        "source_mpp_provenance": "private Motic info.ini scale",
        "anonymization": (
            "Public results contain HMAC-derived aliases only. The alias secret "
            "and source linkage are separately controlled files and are not "
            "part of this result directory."
        ),
        "immune_positive_cell_rule": (
            "Hematoxylin/DAB object segmentation followed by 3-um expanded-cell "
            "expected-brown DAB mean/coverage classification"
        ),
        "compartments": {
            "ck20_epithelium_proxy": (
                "CK20 expected-brown DAB-positive tissue after morphological "
                "cleanup and 8-um expansion"
            ),
            "ck20_stroma_proxy": ("tissue minus the CK20-positive epithelial proxy"),
        },
        "scientific_limitations": [
            "Research-use proxy; not a clinical or consensus Immunoscore.",
            "No pathologist-validated tumour-core or invasive-margin ROIs.",
            "Internal cohort percentiles are not the validated 700-case reference.",
            (
                "CK20 expression is differentiation-linked and spatially variable; "
                "it cannot define the entire invasive tumour boundary."
            ),
            "Serial-section registration and compartment masks require visual review.",
        ],
        "method_references": [
            {
                "citation": (
                    "Pages et al. International validation of the consensus "
                    "Immunoscore for colon cancer. Lancet. 2018."
                ),
                "doi": "10.1016/S0140-6736(18)30789-X",
            },
            {
                "citation": (
                    "Marliot et al. Analytical validation of the Immunoscore "
                    "and its associated prognostic value in patients with colon cancer."
                ),
                "pmcid": "PMC7253006",
            },
            {
                "citation": (
                    "Gatenbee et al. Virtual alignment of pathology image series "
                    "for multi-gigapixel whole slide images. Nature Communications. "
                    "2023."
                ),
                "doi": "10.1038/s41467-023-40218-9",
                "pmcid": "PMC10372014",
            },
            {
                "citation": (
                    "Cernat et al. Colorectal cancers mimic structural "
                    "organization of normal colonic crypts. PLoS ONE. 2014."
                ),
                "doi": "10.1371/journal.pone.0104284",
                "pmcid": "PMC4128715",
            },
        ],
        "private_linkage_included": False,
        "source_identifiers_included": False,
        "consensus_immunoscore": None,
        "consensus_immunoscore_status": (
            "unavailable_requires_pathologist_validated_CT_IM_and_external_reference"
        ),
    }
    _atomic_json(
        output_root / "workflow_metadata/immunoscore_run.json",
        metadata,
    )
    if failures:
        _atomic_json(
            output_root / "workflow_metadata/failures.json",
            {"failures": failures},
        )
    return {
        **metadata,
        "output": str(output_root),
        "private_linkage": str(private_linkage),
    }
