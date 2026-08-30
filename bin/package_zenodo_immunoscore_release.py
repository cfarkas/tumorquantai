#!/usr/bin/env python3
"""Build the reviewed public artifacts for the colon-IHC Zenodo draft."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bin"))

from mds_manifest import load_manifest  # noqa: E402
from tumorquantai_cli import immunoscore  # noqa: E402


ALIAS_RE = re.compile(r"^TQA_CIS_[A-Z2-7]{20}$")
EXPECTED_MDS_COUNT = 30
EXPECTED_MDS_BYTES = 40_580_793_856
MANIFEST_NAME = "tumorquantai_colon_immunoscore_mds_manifest.csv"
CATALOG_FIELDS = (
    "case_alias",
    "slide_alias",
    "marker",
    "zenodo_filename",
    "size_bytes",
    "sha256",
    "md5",
    "source_mpp",
    "source_format",
    "sanitization_profile",
)
FORBIDDEN_PUBLIC_TEXT = (
    "source_case_id",
    "source_slide_id",
    "source_mds_path",
    "/home/",
    "/media/",
    "private_source",
    "private_release",
    "alias_secret",
)


class PackageError(RuntimeError):
    """Raised when a release artifact is incomplete or privacy-unsafe."""


def _atomic_text(path: Path, value: str, mode: int = 0o644) -> None:
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


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _atomic_csv(
    path: Path,
    fields: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
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
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_csv(
    path: Path,
    expected_fields: Sequence[str],
    label: str,
) -> list[dict[str, str]]:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_file():
        raise PackageError(f"{label} is not a regular file")
    with candidate.resolve().open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != tuple(expected_fields):
            raise PackageError(f"{label} columns differ from the package schema")
        return [dict(row) for row in reader]


def _assert_public_text(label: str, value: str) -> None:
    lowered = value.casefold()
    hits = [item for item in FORBIDDEN_PUBLIC_TEXT if item.casefold() in lowered]
    if hits:
        raise PackageError(f"{label} contains a forbidden private-path/ID marker")


def _copy_public(source: Path, destination: Path) -> None:
    candidate = source.expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_file():
        raise PackageError(f"Public input is not a regular file: {candidate.name}")
    text = candidate.read_text(encoding="utf-8-sig")
    _assert_public_text(candidate.name, text)
    _atomic_text(destination, text)


def _digest(path: Path) -> tuple[int, str, str]:
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            size += len(chunk)
            sha256.update(chunk)
            md5.update(chunk)
    return size, sha256.hexdigest(), md5.hexdigest()


def _atomic_figure_zip(
    destination: Path,
    analysis_root: Path,
    figure_rows: Sequence[Mapping[str, str]],
) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        members: list[tuple[str, Path]] = []
        for row in figure_rows:
            for field in ("png_path", "pdf_path", "legend_path"):
                relative = Path(row[field])
                if relative.is_absolute() or ".." in relative.parts:
                    raise PackageError("Paper-figure manifest contains an unsafe path")
                candidate = analysis_root / relative
                if candidate.is_symlink():
                    raise PackageError(f"Paper-figure member is a symlink: {relative}")
                source = candidate.resolve()
                try:
                    source.relative_to(analysis_root)
                except ValueError as exc:
                    raise PackageError(
                        "Paper-figure path escapes the analysis root"
                    ) from exc
                if source.is_symlink() or not source.is_file():
                    raise PackageError(f"Missing paper-figure member: {relative}")
                if field == "legend_path":
                    _assert_public_text(source.name, source.read_text(encoding="utf-8"))
                members.append((relative.as_posix(), source))
        names = [name for name, _source in members]
        if len(names) != len(set(names)):
            raise PackageError("Paper-figure archive member names are duplicated")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, source in sorted(members):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_STORED
                info.external_attr = 0o100644 << 16
                with source.open("rb") as source_handle, archive.open(
                    info, "w"
                ) as archive_handle:
                    shutil.copyfileobj(
                        source_handle, archive_handle, length=8 * 1024 * 1024
                    )
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _readme(
    case_count: int,
    complete_count: int,
    incomplete_count: int,
) -> str:
    return f"""# TumorQuantAI colon CD3/CD8/CK20 whole-slide dataset

This restricted draft contains {EXPECTED_MDS_COUNT} pseudonymized and
pixel-sanitized Motic MDS whole-slide images from {case_count} anonymous case
aliases: CD3, CD8, and CK20.
Nine cases have complete CD3/CD8/CK20 serial-section sets; two cases are
retained for completeness but lack at least one marker
({complete_count} complete, {incomplete_count} incomplete).

## Files

- {MANIFEST_NAME}: authoritative MDS geometry, checksums, and pixel fingerprints.
- tumorquantai_colon_immunoscore_slide_catalog.csv: anonymous case/slide/marker map.
- tumorquantai_immunoscore_values.csv: four clear CK20-guided CD3/CD8 densities.
- cohort_density_summary.csv: QC-population-specific descriptive statistics.
- case_compartment_densities.csv: long counts, areas, densities, MPP, and QC.
- registration_qc.csv and registration_qc_*.png: numeric and visual registration QC.
- paper_figure_manifest.csv and tumorquantai_immunoscore_paper_figures.zip:
  300-dpi case/slide review sheets, PDF forms, and external legends.
- PATHOLOGIST_REVIEW.html, pathologist_review_template.csv, and
  pathologist_review_codebook.csv: offline accept/flag/exclude adjudication.
- unavailable_cases.csv: incomplete/failed audit; missing is never numerical zero.
- tumorquantai_immunoscore_run.json: versioned analysis settings and limitations.
- REPORT.html: portable summary of the computational values.
- SHA256SUMS and MD5SUMS: checksums for the complete draft payload.

## De-identification

Every public case and slide name is a non-semantic, HMAC-derived pseudonym.
Original archives, filenames, scanner sidecars, label/macro images, private case IDs,
alias secret, and linkage are excluded. Each MDS was cloned, every DSI0 pixel
stream was preserved byte-for-byte, and every non-pixel OLE stream was replaced
with deterministic same-size generic neutral content. Full DSI0 fingerprints,
structure, decodability, and multi-encoding source-name marker scans must pass
before upload. Tissue, embedded-label, and macro review panels accompany the
controlled pre-publication review; independent human review remains required
before publication.

## Analysis

TumorQuantAI registers CD3 and CD8 serial sections to CK20 and reports
positive-cell density in a CK20-positive epithelial proxy and CK20-negative
tissue/stromal proxy. CK20 is separated in streamed blocks near 2 µm/pixel and
its expected-brown positive fraction is area-projected into the bounded
registration overview. Pyramid coordinates use numeric level scale rather
than differently padded tile-canvas ratios. Values are deterministic research
measurements.

This is not the consensus clinical Immunoscore. No pathologist-validated tumour
core or invasive margin and no validated external 700-case reference
distribution were supplied. The consensus score is therefore blank and
explicitly unavailable. A separately named pI0-pI4 provisional analogue applies
the published five percentile bands to the mean of the four CK20-proxy density
percentiles, using only automatic-QC-pass cases in this run as the internal
reference. It is an exploratory within-cohort rank, not a validated score.
Pathologist accept/flag/exclude decisions are additive and never overwrite the
original algorithm values or QC. CK20 expression is differentiation-linked and
spatially variable, so it cannot define the entire invasive boundary. Every
registration and compartment mask
requires expert visual review. These data and outputs must not guide patient
care.

## Methods

Consensus context: Pages et al., Lancet 2018,
doi:10.1016/S0140-6736(18)30789-X. Analytical protocol context:
PMCID PMC7253006. Software and the complete English tutorial:
https://github.com/cfarkas/tumorquantai

Access remains restricted while the custodian completes independent pixel
privacy, redistribution-rights, licensing, and metadata review. A draft is not
authorization for redistribution.
"""


def _report_html(
    values: Sequence[Mapping[str, str]],
    density_summary: Sequence[Mapping[str, str]],
    qc_names: Sequence[str],
) -> str:
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(row.get(field, '')))}</td>"
            for field in immunoscore.CASE_VALUE_FIELDS
        )
        + "</tr>"
        for row in values
    )
    summary_rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(row.get(field, '')))}</td>"
            for field in immunoscore.COHORT_DENSITY_SUMMARY_FIELDS
        )
        + "</tr>"
        for row in density_summary
    )
    qc = "".join(
        f'<li><a href="{html.escape(name)}">{html.escape(name)}</a></li>'
        for name in qc_names
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TumorQuantAI colon IHC dataset report</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:1500px;margin:auto;padding:28px;color:#17202a}}
.warning{{border-left:6px solid #b33b2e;background:#fff0ed;padding:14px}}
.scroll{{overflow:auto}}table{{border-collapse:collapse;font-size:12px}}th,td{{border:1px solid #ccd5dc;padding:6px;white-space:nowrap}}</style>
</head><body><h1>CK20-guided CD3/CD8 WSI quantification</h1>
<p class="warning"><strong>Research proxy—not clinical Immunoscore.</strong>
The official score is unavailable because reviewed CT/IM regions and the
validated external reference distribution were not supplied. The separately
named pI0-pI4 value is a provisional within-cohort CK20-proxy rank only.</p>
<p>Open <a href="{MANIFEST_NAME}">the MDS manifest</a>,
<a href="tumorquantai_colon_immunoscore_slide_catalog.csv">the anonymous slide
catalog</a>, and <a href="case_compartment_densities.csv">the long density
table</a>. Use the offline <a href="PATHOLOGIST_REVIEW.html">pathologist review
dashboard</a> to export accept/flag/exclude decisions, and download the
<a href="tumorquantai_immunoscore_paper_figures.zip">paper-figure bundle</a>.
Review every registration image before interpreting values.</p>
<h2>Cohort density summary</h2>
<p><code>automatic_qc_pass</code> excludes review-status cases;
<code>all_numerically_available</code> includes them. Both exclude failed and
incomplete cases. Standard deviation is the sample SD.</p>
<div class="scroll"><table><thead><tr>
{''.join(f'<th>{html.escape(field)}</th>' for field in immunoscore.COHORT_DENSITY_SUMMARY_FIELDS)}
</tr></thead><tbody>{summary_rows}</tbody></table></div>
<h2>Case values</h2>
<div class="scroll"><table><thead><tr>
{''.join(f'<th>{html.escape(field)}</th>' for field in immunoscore.CASE_VALUE_FIELDS)}
</tr></thead><tbody>{rows}</tbody></table></div>
<h2>Registration composites</h2><ul>{qc}</ul>
<h2>Boundaries</h2><ul><li>Serial sections are not cell-for-cell identical.</li>
<li>CK20 is a differentiation-linked epithelial proxy, not a complete invasive-boundary marker.</li>
<li>Internal percentiles describe only automatic-QC-pass cases in this cohort.</li>
<li>pI0-pI4 is provisional and must never be reported as consensus Immunoscore.</li>
<li>Pathologist decisions do not overwrite algorithm values or automatic QC.</li>
<li>Outputs must not guide diagnosis or treatment.</li></ul></body></html>
"""


def package_release(
    public_manifest: Path,
    public_inventory: Path,
    analysis_root: Path,
    output_dir: Path,
    *,
    resume: bool = False,
) -> dict[str, Any]:
    manifest_rows, _text = load_manifest(public_manifest, alias_re=ALIAS_RE)
    if len(manifest_rows) != EXPECTED_MDS_COUNT:
        raise PackageError("Public MDS manifest does not contain exactly 30 slides")
    if sum(row.size_bytes for row in manifest_rows) != EXPECTED_MDS_BYTES:
        raise PackageError("Public MDS byte total differs from the reviewed cohort")
    inventory = _read_csv(
        public_inventory,
        immunoscore.PUBLIC_SLIDE_FIELDS,
        "Public slide inventory",
    )
    if len(inventory) != EXPECTED_MDS_COUNT:
        raise PackageError("Public slide inventory does not contain exactly 30 rows")
    inventory_by_slide: dict[str, dict[str, str]] = {}
    for row in inventory:
        case_alias = row["case_alias"]
        slide_alias = row["slide_alias"]
        marker = row["marker"]
        if (
            not immunoscore.CASE_ALIAS_RE.fullmatch(case_alias)
            or not immunoscore.SLIDE_ALIAS_RE.fullmatch(slide_alias)
            or marker not in immunoscore.IMMUNOSCORE_MARKERS
            or slide_alias in inventory_by_slide
        ):
            raise PackageError("Public inventory has an invalid/duplicate row")
        inventory_by_slide[slide_alias] = row
    if set(inventory_by_slide) != {row.alias for row in manifest_rows}:
        raise PackageError("MDS manifest and public slide inventory aliases differ")
    marker_counts = Counter(row["marker"] for row in inventory)
    if marker_counts != Counter({"CD3": 10, "CD8": 10, "CK20": 10}):
        raise PackageError("Marker roster differs from the reviewed 10/10/10 set")

    analysis_root = analysis_root.expanduser().resolve()
    values = _read_csv(
        analysis_root / "tables/tumorquantai_immunoscore_values.csv",
        immunoscore.CASE_VALUE_FIELDS,
        "TumorQuantAI case values",
    )
    density_summary = _read_csv(
        analysis_root / "tables/cohort_density_summary.csv",
        immunoscore.COHORT_DENSITY_SUMMARY_FIELDS,
        "TumorQuantAI cohort density summary",
    )
    review_template = _read_csv(
        analysis_root / "tables/pathologist_review_template.csv",
        immunoscore.PATHOLOGIST_REVIEW_FIELDS,
        "Pathologist review template",
    )
    review_codebook = _read_csv(
        analysis_root / "tables/pathologist_review_codebook.csv",
        immunoscore.PATHOLOGIST_REVIEW_CODEBOOK_FIELDS,
        "Pathologist review codebook",
    )
    paper_figures = _read_csv(
        analysis_root / "tables/paper_figure_manifest.csv",
        immunoscore.PAPER_FIGURE_FIELDS,
        "Paper-figure manifest",
    )
    case_aliases = {row["case_alias"] for row in inventory}
    if (
        len(values) != len(case_aliases)
        or {row["case_alias"] for row in values} != case_aliases
        or any(
            not immunoscore.CASE_ALIAS_RE.fullmatch(row["case_alias"]) for row in values
        )
    ):
        raise PackageError("Case values do not exactly cover the anonymous cohort")
    if (
        len(review_template) != len(values)
        or {row["case_alias"] for row in review_template} != case_aliases
        or any(
            row["pathologist_decision"]
            or row["pathologist_flag_reasons"]
            or row["pathologist_notes"]
            or row["reviewer_code"]
            or row["reviewed_at_iso8601"]
            for row in review_template
        )
    ):
        raise PackageError(
            "Public pathologist review template is populated or incomplete"
        )
    if {
        row["allowed_value"]
        for row in review_codebook
        if row["field"] == "pathologist_decision"
    } != set(immunoscore.PATHOLOGIST_DECISIONS):
        raise PackageError("Pathologist review decision codebook differs")
    complete_case_aliases = {
        row["case_alias"] for row in values if row["qc_status"] in {"pass", "review"}
    }
    if (
        len(paper_figures) != 4 * len(complete_case_aliases)
        or {row["case_alias"] for row in paper_figures} != complete_case_aliases
        or sum(row["figure_scope"] == "case_summary" for row in paper_figures)
        != len(complete_case_aliases)
        or sum(row["figure_scope"] == "slide_review" for row in paper_figures)
        != 3 * len(complete_case_aliases)
        or any(
            row["dpi"] != "300"
            or row["layout_version"] != immunoscore.PAPER_FIGURE_LAYOUT_VERSION
            for row in paper_figures
        )
    ):
        raise PackageError(
            "Paper-figure manifest does not cover every complete case/slide"
        )
    for row in paper_figures:
        if row["figure_scope"] == "case_summary":
            if row["slide_alias"] or row["marker"] != "CK20+CD3+CD8":
                raise PackageError("Case-summary paper-figure row is invalid")
            continue
        if row["figure_scope"] != "slide_review":
            raise PackageError("Paper-figure scope is invalid")
        inventory_row = inventory_by_slide.get(row["slide_alias"])
        if (
            inventory_row is None
            or inventory_row["case_alias"] != row["case_alias"]
            or inventory_row["marker"] != row["marker"]
        ):
            raise PackageError("Slide paper figure does not match the public inventory")

    output_candidate = output_dir.expanduser().absolute()
    if output_candidate.is_symlink():
        raise PackageError("Release output must not be a symlink")
    output_dir = output_candidate.resolve()
    if output_dir.is_dir() and any(output_dir.iterdir()) and not resume:
        raise PackageError("Release output is non-empty; use --resume to rebuild")
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output_dir, 0o700)

    manifest_destination = output_dir / MANIFEST_NAME
    _copy_public(public_manifest, manifest_destination)
    manifest_by_alias = {row.alias: row for row in manifest_rows}
    catalog: list[dict[str, Any]] = []
    for slide_alias, inventory_row in sorted(inventory_by_slide.items()):
        manifest = manifest_by_alias[slide_alias]
        catalog.append(
            {
                "case_alias": inventory_row["case_alias"],
                "slide_alias": slide_alias,
                "marker": inventory_row["marker"],
                "zenodo_filename": manifest.zenodo_filename,
                "size_bytes": manifest.size_bytes,
                "sha256": manifest.sha256,
                "md5": manifest.md5,
                "source_mpp": manifest.source_mpp,
                "source_format": inventory_row["source_format"],
                "sanitization_profile": manifest.sanitization_profile,
            }
        )
    _atomic_csv(
        output_dir / "tumorquantai_colon_immunoscore_slide_catalog.csv",
        CATALOG_FIELDS,
        catalog,
    )

    public_tables = (
        "tumorquantai_immunoscore_values.csv",
        "cohort_density_summary.csv",
        "case_compartment_densities.csv",
        "registration_qc.csv",
        "unavailable_cases.csv",
        "pathologist_review_template.csv",
        "pathologist_review_codebook.csv",
        "paper_figure_manifest.csv",
    )
    for name in public_tables:
        _copy_public(analysis_root / "tables" / name, output_dir / name)
    _copy_public(
        analysis_root / "workflow_metadata/immunoscore_run.json",
        output_dir / "tumorquantai_immunoscore_run.json",
    )
    _copy_public(
        analysis_root / "PATHOLOGIST_REVIEW.html",
        output_dir / "PATHOLOGIST_REVIEW.html",
    )
    _atomic_figure_zip(
        output_dir / "tumorquantai_immunoscore_paper_figures.zip",
        analysis_root,
        paper_figures,
    )
    _atomic_text(
        output_dir / "README.md",
        _readme(
            len(case_aliases),
            sum(
                {row["marker"] for row in inventory if row["case_alias"] == case_alias}
                == set(immunoscore.IMMUNOSCORE_MARKERS)
                for case_alias in case_aliases
            ),
            sum(
                {row["marker"] for row in inventory if row["case_alias"] == case_alias}
                != set(immunoscore.IMMUNOSCORE_MARKERS)
                for case_alias in case_aliases
            ),
        ),
    )

    qc_names: list[str] = []
    for case_alias in sorted(
        row["case_alias"] for row in values if row["qc_status"] in {"pass", "review"}
    ):
        source = analysis_root / "cases" / case_alias / "registration_qc.png"
        if source.is_symlink() or not source.is_file():
            raise PackageError(f"Missing registration QC for {case_alias}")
        name = f"registration_qc_{case_alias}.png"
        destination = output_dir / name
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{name}.", dir=output_dir
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, destination)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        qc_names.append(name)
    _atomic_text(
        output_dir / "REPORT.html",
        _report_html(values, density_summary, qc_names),
    )

    validation = {
        "schema_version": 1,
        "status": "passed_requires_independent_visual_and_rights_review",
        "mds_file_count": len(manifest_rows),
        "mds_total_size_bytes": sum(row.size_bytes for row in manifest_rows),
        "case_count": len(case_aliases),
        "complete_case_count": sum(
            1 for row in values if row["qc_status"] not in {"unavailable", "failed"}
        ),
        "incomplete_or_failed_case_count": sum(
            1 for row in values if row["qc_status"] in {"unavailable", "failed"}
        ),
        "marker_slide_counts": dict(sorted(marker_counts.items())),
        "registration_qc_image_count": len(qc_names),
        "paper_figure_count": len(paper_figures),
        "paper_figure_archive": "tumorquantai_immunoscore_paper_figures.zip",
        "pathologist_review_template_is_blank": True,
        "pathologist_review_schema_version": (
            immunoscore.PATHOLOGIST_REVIEW_SCHEMA_VERSION
        ),
        "source_identifiers_included": False,
        "private_linkage_included": False,
        "original_label_or_macro_content_included": False,
        "neutral_label_macro_streams_included": True,
        "pixel_stream_policy": "DSI0 preserved byte-for-byte",
        "nonpixel_stream_policy": (
            "deterministic same-size generic neutral replacement"
        ),
        "consensus_immunoscore_included": False,
        "provisional_immunoscore_included": True,
        "provisional_immunoscore_schema_version": (
            immunoscore.PROVISIONAL_SCORE_SCHEMA_VERSION
        ),
        "provisional_immunoscore_clinical_status": (
            "exploratory_cohort_internal_proxy_not_consensus_immunoscore"
        ),
    }
    _atomic_json(output_dir / "release_validation_report.json", validation)

    small_files = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name not in {"SHA256SUMS", "MD5SUMS"}
    )
    sha_rows = {row.zenodo_filename: row.sha256 for row in manifest_rows}
    md5_rows = {row.zenodo_filename: row.md5 for row in manifest_rows}
    for path in small_files:
        _size, sha256, md5 = _digest(path)
        sha_rows[path.name] = sha256
        md5_rows[path.name] = md5
    _atomic_text(
        output_dir / "SHA256SUMS",
        "".join(f"{digest}  {name}\n" for name, digest in sorted(sha_rows.items())),
    )
    _atomic_text(
        output_dir / "MD5SUMS",
        "".join(f"{digest}  {name}\n" for name, digest in sorted(md5_rows.items())),
    )
    for path in output_dir.iterdir():
        if path.is_file():
            _assert_public_text(
                path.name,
                (
                    path.read_text(encoding="utf-8", errors="ignore")
                    if path.suffix.casefold() not in {".png", ".pdf", ".zip"}
                    else ""
                ),
            )
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    return {
        "status": "packaged",
        "output_dir": str(output_dir),
        "mds_file_count": len(manifest_rows),
        "mds_total_size_bytes": sum(row.size_bytes for row in manifest_rows),
        "public_artifact_count": len(
            [path for path in output_dir.iterdir() if path.is_file()]
        ),
        "registration_qc_image_count": len(qc_names),
        "paper_figure_count": len(paper_figures),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-manifest", required=True, type=Path)
    parser.add_argument("--public-slide-inventory", required=True, type=Path)
    parser.add_argument("--analysis-results", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = package_release(
            args.public_manifest,
            args.public_slide_inventory,
            args.analysis_results,
            args.output_dir,
            resume=args.resume,
        )
    except (PackageError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
