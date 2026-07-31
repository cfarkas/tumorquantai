#!/usr/bin/env python3
"""Generate standard Zenodo URL and SHA-256 lists from the public manifest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BIN_DIRECTORY = REPOSITORY_ROOT / "bin"
sys.path.insert(0, str(BIN_DIRECTORY))

from mds_manifest import MdsManifestRow, load_manifest  # noqa: E402


RECORD_ID = "21466410"
MANIFEST_PATH = (
    REPOSITORY_ROOT
    / "examples"
    / "lymphoma"
    / "tumorquantai_lymphoma_mds_manifest.csv"
)
OUTPUT_DIRECTORY = REPOSITORY_ROOT / "examples" / "lymphoma"
ONE_SAMPLE = ("TumorQuantAI_LymphomaWSI_022",)
FIRST_FOUR_SAMPLES = (
    "TumorQuantAI_LymphomaWSI_022",
    "TumorQuantAI_LymphomaWSI_002",
    "TumorQuantAI_LymphomaWSI_006",
    "TumorQuantAI_LymphomaWSI_016",
)


def select_rows(
    rows: list[MdsManifestRow], aliases: tuple[str, ...] | None
) -> list[MdsManifestRow]:
    by_alias = {row.alias: row for row in rows}
    if aliases is None:
        return sorted(rows, key=lambda row: row.alias)
    missing = set(aliases) - set(by_alias)
    if missing:
        raise ValueError(
            "Public manifest lacks required aliases: " + ", ".join(sorted(missing))
        )
    return [by_alias[alias] for alias in aliases]


def url_text(rows: list[MdsManifestRow]) -> str:
    return "".join(
        f"https://zenodo.org/records/{RECORD_ID}/files/"
        f"{row.zenodo_filename}?download=1\n"
        for row in rows
    )


def checksum_text(rows: list[MdsManifestRow]) -> str:
    return "".join(f"{row.sha256}  {row.zenodo_filename}\n" for row in rows)


def generated_artifacts(
    manifest_path: Path = MANIFEST_PATH,
    output_directory: Path = OUTPUT_DIRECTORY,
) -> dict[Path, str]:
    rows, _ = load_manifest(manifest_path)
    subsets = {
        "one": select_rows(rows, ONE_SAMPLE),
        "first_four": select_rows(rows, FIRST_FOUR_SAMPLES),
        "all_21": select_rows(rows, None),
    }
    artifacts: dict[Path, str] = {}
    for name, selected in subsets.items():
        artifacts[output_directory / f"zenodo_{name}.urls.txt"] = url_text(selected)
        artifacts[output_directory / f"checksums_{name}.sha256"] = checksum_text(
            selected
        )
    return artifacts


def synchronize(
    *,
    check: bool,
    manifest_path: Path = MANIFEST_PATH,
    output_directory: Path = OUTPUT_DIRECTORY,
) -> list[Path]:
    mismatches: list[Path] = []
    for path, expected in generated_artifacts(manifest_path, output_directory).items():
        actual = path.read_text(encoding="utf-8") if path.is_file() else None
        if actual == expected:
            continue
        mismatches.append(path)
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8", newline="\n")
    return mismatches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail instead of updating files when generated content differs",
    )
    args = parser.parse_args(argv)
    mismatches = synchronize(check=args.check)
    if args.check and mismatches:
        for path in mismatches:
            print(f"out of date: {path.relative_to(REPOSITORY_ROOT)}", file=sys.stderr)
        return 1
    action = "updated" if mismatches else "verified"
    print(f"{action} {len(generated_artifacts())} Zenodo download artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
