#!/usr/bin/env python3
"""Offline repository, documentation, metadata, and artifact quality gate."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import urllib.parse
from pathlib import Path

import yaml
from jsonschema.validators import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
STALE_PATTERNS = {
    "pre-publication claim": re.compile(r"pre[ -]?publication", re.IGNORECASE),
    "unpublished claim": re.compile(r"\bunpublished\b", re.IGNORECASE),
    "published-record placeholder": re.compile(r"<PUBLISHED_", re.IGNORECASE),
    "immutable-release placeholder": re.compile(r"<IMMUTABLE_", re.IGNORECASE),
    "non-public record claim": re.compile(r"record is not public|restricted and unpublished", re.IGNORECASE),
}
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
SECRET_VALUE = re.compile(r"\bhf_[A-Za-z0-9]{20,}\b")
LOCAL_SERVER_PATH = re.compile(r"/(?:media|home)/server/")
LOCAL_PATH_PATTERN_ALLOWLIST = {
    Path("scripts/check_docs_language.py"),
}

# These are the only binary image/data assets intentionally kept in the
# repository. Keep this allowlist literal: a broad tests/ or docs/assets/
# exemption could silently admit a real slide, patient overlay, or coordinate
# export under a reassuring directory name.
ALLOWED_SYNTHETIC_ASSETS = {
    Path("docs/assets/tumorquantai-hero.svg"),
    Path("tests/fixtures/case_a/1_L0_rgb.tif"),
    Path("tests/fixtures/case_a/1_L2_rgb.tif"),
    Path("tests/fixtures/case_fail/1_L0_rgb.tif"),
    Path("tests/fixtures/case_fail/1_L2_rgb.tif"),
}

WSI_SUFFIXES = {".mds", ".svs", ".ndpi", ".mrxs", ".scn", ".bif", ".czi", ".dcm", ".tif", ".tiff"}
WEIGHT_SUFFIXES = {".pt", ".pth", ".ckpt", ".safetensors"}
PATIENT_TABLE_SUFFIXES = {".xlsx", ".parquet", ".h5ad"}

# Directory names emitted by the workflow and worker. They are sufficiently
# specific to reject wherever a user happened to choose their output root.
OUTPUT_LAYOUT_DIRS = {
    "aggregated_celltypes",
    "cell_types",
    "overlays",
    "paper_figures",
    "plotting_metadata",
    "pyramidal_input",
    "qc_patches",
    "sampled_patch_mosaic",
    "sampled_patches",
    "workflow_metadata",
}
ROOT_GENERATED_DIRS = {
    "clinical_ml_results",
    "data",
    "outputs",
    "results",
    "site",
    "work",
}

# Canonical outputs are forbidden independently of their parent directory so
# a renamed/copy-only results directory cannot evade the guard.
GENERATED_OUTPUT_NAMES = {
    "START_HERE.html",
    "RUN_SUMMARY.txt",
    "aggregation_summary.json",
    "analysis_cohort.csv",
    "cell_type_coordinates.csv",
    "cell_type_coordinates.csv.gz",
    "cell_type_coordinates.json",
    "cell_type_coordinates.json.integrity.json",
    "cell_type_coordinates.npy",
    "cell_type_palette.json",
    "cell_types_qupath.json",
    "cell_types_qupath.json.integrity.json",
    "celltype_counts_barplot.pdf",
    "celltype_counts_barplot.png",
    "celltype_counts_by_sample.csv",
    "celltype_counts_long.csv",
    "celltype_fractions_by_sample.csv",
    "celltypes_overview_and_zoom.pdf",
    "celltypes_overview_and_zoom.png",
    "celltypes_paper_figure.pdf",
    "celltypes_paper_figure.png",
    "class_counts.csv",
    "clinical_missingness.csv",
    "detected_cell_types.csv",
    "detected_cell_types.json",
    "feature_manifest.csv",
    "fold_assignments.csv",
    "fold_metrics.csv",
    "heldout_permutation_importance.csv",
    "incremental_value.csv",
    "inspection.json",
    "inspection_manifest.csv",
    "inspection_manifest.tsv",
    "INSPECTION.html",
    "linkage_audit.csv",
    "linked_clinical_histoplus_all.csv",
    "linked_clinical_histoplus_full.csv",
    "model_selection.csv",
    "nextflow.log",
    "overview_with_zoom_box.png",
    "patch_manifest.csv",
    "patch_mosaic_mapping.csv",
    "patch_mosaic_summary.json",
    "patch_summary.json",
    "run_manifest.json",
    "run_metadata.json",
    "sample_aggregation_audit.csv",
    "slide.log",
    "slides.json",
    "slides.tsv",
    "summary.json",
    "summary_metrics.csv",
    "tumorquantai_report.json",
    "tumorquantai_run.json",
    "univariate_stratification.csv",
    "workflow_aggregation_manifest.csv",
    "zoom_overlay_celltypes.png",
}
GENERATED_OUTPUT_PATTERNS = (
    re.compile(r"^nextflow_(?:dag|report|timeline|trace)(?:_[^.]+)?\.(?:html|tsv)$", re.IGNORECASE),
    re.compile(r"^oof_predictions(?:_[^.]+)?\.csv$", re.IGNORECASE),
    re.compile(r"^patch_\d+_(?:l0|l2)\.(?:png|tif|tiff)$", re.IGNORECASE),
)

CANONICAL_OUTPUTS = {
    "overview_with_zoom_box.png": "lazyslide_histoplus_wsi_celltype.py",
    "zoom_overlay_celltypes.png": "lazyslide_histoplus_wsi_celltype.py",
    "celltypes_overview_and_zoom.png": "lazyslide_histoplus_wsi_celltype.py",
    "celltypes_overview_and_zoom.pdf": "lazyslide_histoplus_wsi_celltype.py",
    "summary.json": "lazyslide_histoplus_wsi_celltype.py",
    "class_counts.csv": "lazyslide_histoplus_wsi_celltype.py",
    "celltype_counts_by_sample.csv": "bin/aggregate_histoplus_celltypes.py",
    "celltype_fractions_by_sample.csv": "bin/aggregate_histoplus_celltypes.py",
    "celltype_counts_long.csv": "bin/aggregate_histoplus_celltypes.py",
    "sample_aggregation_audit.csv": "bin/aggregate_histoplus_celltypes.py",
    "aggregation_summary.json": "bin/aggregate_histoplus_celltypes.py",
    "START_HERE.html": "bin/tumorquantai_core.py",
    "tumorquantai_report.json": "bin/tumorquantai_core.py",
    "nextflow.log": "tumorquantai",
}

EXPECTED_HELP = {
    "install": ("--docker", "--singularity", "--poetry", "--conda", "--system"),
    "doctor": ("--online", "--json", "--output", "--work-dir"),
    "demo": ("--output",),
    "convert": (
        "--output", "--manifest", "--levels", "--sample-id",
        "--expected-count", "--source-mpp", "--resume", "--overwrite", "--dry-run",
    ),
    "inspect": ("--output", "--source-mpp", "--sample-sheet", "--pattern", "--include", "--exclude"),
    "run": (
        "--output", "--preset", "--source-mpp", "--sample", "--profile", "--seed",
        "--sample-sheet", "--pattern", "--include", "--exclude", "--work-dir",
        "--dry-run", "--no-resume", "--token-file", "--local-weight",
    ),
    "status": ("--json",),
    "report": ("--json",),
    "quickstart": ("--output", "--dry-run", "--download-only", "--convert-only", "--no-inference", "--profile", "--seed", "--local-weight"),
}


def repository_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    return [ROOT / value.decode("utf-8") for value in result.stdout.split(b"\0") if value]


def check_stale_text(files: list[Path], errors: list[str]) -> None:
    scopes = [ROOT / "README.md", ROOT / "CITATIONS.md", ROOT / "CHANGELOG.md"]
    scopes.extend(path for path in files if path.suffix.lower() == ".md" and (ROOT / "docs") in path.parents)
    scopes.extend(path for path in files if path.suffix.lower() == ".md" and (ROOT / "examples") in path.parents)
    for path in sorted(set(scopes)):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for label, pattern in STALE_PATTERNS.items():
            match = pattern.search(text)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                errors.append(f"{path.relative_to(ROOT)}:{line}: {label}: {match.group(0)!r}")


def markdown_target(source: Path, raw_target: str) -> Path | None:
    target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
    if not target or target.startswith("#"):
        return None
    parsed = urllib.parse.urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return None
    path_text = urllib.parse.unquote(parsed.path)
    if not path_text:
        return None
    return (source.parent / path_text).resolve()


def check_internal_links(files: list[Path], errors: list[str]) -> None:
    markdown = [ROOT / "README.md", *(path for path in files if path.suffix.lower() == ".md" and (ROOT / "docs") in path.parents)]
    for source in sorted(set(markdown)):
        if not source.is_file():
            continue
        text = source.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            target = markdown_target(source, match.group(1))
            if target is None:
                continue
            try:
                target.relative_to(ROOT)
            except ValueError:
                errors.append(f"{source.relative_to(ROOT)}: internal link escapes repository: {match.group(1)}")
                continue
            if not target.exists():
                line = text.count("\n", 0, match.start()) + 1
                errors.append(f"{source.relative_to(ROOT)}:{line}: broken internal link: {match.group(1)}")


def check_forbidden_artifacts(files: list[Path], errors: list[str]) -> None:
    for path in files:
        relative = path.relative_to(ROOT)
        allowed_asset = relative in ALLOWED_SYNTHETIC_ASSETS
        lower_parts = {part.casefold() for part in relative.parts}
        suffix = path.suffix.lower()
        lower_name = relative.name.casefold()
        if suffix in WSI_SUFFIXES and not allowed_asset:
            errors.append(f"forbidden WSI/tutorial data is tracked or unignored: {relative}")
        if suffix in WEIGHT_SUFFIXES:
            errors.append(f"forbidden model weight is tracked or unignored: {relative}")
        if suffix in PATIENT_TABLE_SUFFIXES or any(part.casefold().endswith((".zarr", ".zarr.zip")) for part in relative.parts):
            errors.append(f"forbidden patient-level/bulk data artifact is tracked or unignored: {relative}")
        if not allowed_asset and (
            relative.name in GENERATED_OUTPUT_NAMES
            or any(pattern.fullmatch(relative.name) for pattern in GENERATED_OUTPUT_PATTERNS)
        ):
            errors.append(f"generated patient/workflow output is tracked or unignored: {relative}")
        if lower_parts.intersection(OUTPUT_LAYOUT_DIRS):
            errors.append(f"generated patient output layout is tracked or unignored: {relative}")
        if relative.parts and relative.parts[0].casefold() in ROOT_GENERATED_DIRS:
            errors.append(f"generated/private directory is tracked or unignored: {relative}")
        if "token" in lower_name and relative.name not in {"test_tumorquantai_cli.py"}:
            errors.append(f"token-like file is tracked or unignored: {relative}")
        if path.is_file() and path.stat().st_size <= 4 * 1024 * 1024 and suffix in {".py", ".sh", ".md", ".yml", ".yaml", ".json", ".cff", ".csv", ".svg", ".txt", ""}:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if SECRET_VALUE.search(text) and relative.parts[0] != "tests":
                errors.append(f"possible Hugging Face token value in {relative}")
            if (
                LOCAL_SERVER_PATH.search(text)
                and relative.parts[0] != "tests"
                and relative not in LOCAL_PATH_PATTERN_ALLOWLIST
            ):
                errors.append(f"server-specific absolute path is tracked or unignored: {relative}")


def check_metadata(files: list[Path], errors: list[str]) -> None:
    schema_path = ROOT / "nextflow_schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except Exception as exc:  # jsonschema gives several useful exception types
        errors.append(f"nextflow_schema.json is not a valid Draft 2020-12 schema: {exc}")
    for path in files:
        if path.suffix.lower() not in {".yml", ".yaml"}:
            continue
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid YAML in {path.relative_to(ROOT)}: {exc}")
    try:
        cff = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
        required = {"cff-version", "message", "title", "type", "authors", "version", "date-released", "repository-code"}
        missing = required.difference(cff or {})
        if missing:
            errors.append("CITATION.cff missing required project fields: " + ", ".join(sorted(missing)))
        if str(cff.get("cff-version")) != "1.2.0" or cff.get("type") != "software":
            errors.append("CITATION.cff must describe CFF 1.2.0 software")
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        package_version = str(pyproject["tool"]["poetry"]["version"])
        version_sources = {
            "CITATION.cff": str(cff.get("version")),
            "pyproject.toml": package_version,
        }
        text_sources = (
            (
                "bin/tumorquantai_core.py",
                r'^VERSION = "([^"]+)"$',
            ),
            (
                "nextflow.config",
                r"^\s*version = '([^']+)'\s*$",
            ),
            (
                "build_and_push.sh",
                r'^TAG="\$\{TAG:-([^}]+)\}"$',
            ),
            (
                "scripts/check_external_resources.py",
                r'^SOFTWARE_RELEASE = "v([^"]+)"$',
            ),
        )
        for relative, pattern in text_sources:
            text = (ROOT / relative).read_text(encoding="utf-8")
            match = re.search(pattern, text, re.MULTILINE)
            if match is None:
                errors.append(f"cannot determine software version from {relative}")
            else:
                version_sources[relative] = match.group(1)
        if not re.fullmatch(r"[1-9][0-9]*\.[0-9]+\.[0-9]+", package_version):
            errors.append(
                "software release version must be a stable semantic version"
            )
        for source, observed in version_sources.items():
            if observed != package_version:
                errors.append(
                    f"{source} version {observed!r} does not match "
                    f"pyproject.toml {package_version!r}"
                )
        release_date = str(cff.get("date-released"))
        changelog_heading = f"## {package_version} — {release_date}"
        if changelog_heading not in (ROOT / "CHANGELOG.md").read_text(
            encoding="utf-8"
        ):
            errors.append(
                "CHANGELOG.md has no heading matching the software version "
                "and CITATION.cff release date"
            )
        for relative in ("CITATIONS.md", "docs/reference/citations.md"):
            citation = (ROOT / relative).read_text(encoding="utf-8")
            if f"Version {package_version}." not in citation:
                errors.append(
                    f"{relative} software citation does not match "
                    f"pyproject.toml {package_version!r}"
                )
        if "10.5281/zenodo.21466410" in (ROOT / "CITATION.cff").read_text(encoding="utf-8"):
            errors.append("dataset DOI must not be assigned as the TumorQuantAI software DOI in CITATION.cff")
    except Exception as exc:
        errors.append(f"invalid CITATION.cff: {exc}")


def check_output_names(errors: list[str]) -> None:
    reference = (ROOT / "docs/reference/outputs.md").read_text(encoding="utf-8")
    for filename, writer_name in CANONICAL_OUTPUTS.items():
        writer = (ROOT / writer_name).read_text(encoding="utf-8")
        if filename not in writer:
            errors.append(f"canonical output {filename} is absent from writer {writer_name}")
        if filename not in reference:
            errors.append(f"canonical output {filename} is absent from docs/reference/outputs.md")


def check_cli_reference(errors: list[str]) -> None:
    reference = (ROOT / "docs/reference/cli.md").read_text(encoding="utf-8")
    for command, expected_options in EXPECTED_HELP.items():
        completed = subprocess.run(
            [str(ROOT / "tumorquantai"), command, "--help"], cwd=ROOT,
            text=True, capture_output=True, check=False,
        )
        if completed.returncode != 0:
            errors.append(f"./tumorquantai {command} --help failed: {completed.stderr.strip()}")
            continue
        for option in expected_options:
            if option not in completed.stdout:
                errors.append(f"{command} help is missing expected option {option}")
            if option not in reference:
                errors.append(f"docs/reference/cli.md is missing {command} option {option}")


def check_readme_quickstart(errors: list[str]) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required_snippets = {
        "repository clone": "git clone https://github.com/cfarkas/tumorquantai.git",
        "Docker installer": "./tumorquantai install --docker",
        "Singularity installer": "./tumorquantai install --singularity",
        "Poetry installer": "./tumorquantai install --poetry",
        "Conda installer": "./tumorquantai install --conda",
        "global QuickStart": "tumorquantai quickstart --no-inference",
        "fixed public sample": "TumorQuantAI_LymphomaWSI_022",
        "preparation verifier": "examples/quickstart/verify_outputs.py --preparation-only",
    }
    for label, snippet in required_snippets.items():
        if snippet not in readme:
            errors.append(f"README is missing {label}: {snippet}")
    if "TQA_ROOT=/path/to/mounted/storage/tumorquantai-quickstart" in readme:
        errors.append("README QuickStart must not require an edited TQA_ROOT path")
    line_count = len(readme.splitlines())
    if not 100 <= line_count <= 350:
        errors.append(f"README should stay concise (100-350 lines); observed {line_count}")
    if not os.access(ROOT / "tumorquantai", os.X_OK):
        errors.append("root tumorquantai command is not executable")
        return
    with tempfile.TemporaryDirectory(prefix="tqa-readme-demo-") as temporary:
        output = Path(temporary) / "demo"
        environment = os.environ.copy()
        environment["HOME"] = str(Path(temporary) / "home")
        completed = subprocess.run(
            [str(ROOT / "tumorquantai"), "demo", "--output", str(output)],
            cwd=ROOT, text=True, capture_output=True, env=environment, check=False,
        )
        if completed.returncode != 0 or not (output / "START_HERE.html").is_file():
            errors.append("synthetic demo failed to create START_HERE.html")
        if "TumorQuantAI structural demo complete." not in completed.stdout:
            errors.append("synthetic demo success text drifted from executable output")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-demo", action="store_true", help="skip only the README end-to-end demo")
    args = parser.parse_args(argv)
    errors: list[str] = []
    files = repository_files()
    check_stale_text(files, errors)
    check_internal_links(files, errors)
    check_forbidden_artifacts(files, errors)
    check_metadata(files, errors)
    check_output_names(errors)
    check_cli_reference(errors)
    if not args.skip_demo:
        check_readme_quickstart(errors)
    if errors:
        print("Repository hygiene checks failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Repository hygiene checks passed ({len(files)} source paths checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
