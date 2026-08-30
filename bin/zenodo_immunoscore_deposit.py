#!/usr/bin/env python3
"""Create a new restricted Zenodo draft for anonymized colon-IHC MDS WSIs.

The depositor is intentionally draft-only. It accepts exactly 30 sanitized
MDS files with TumorQuantAI colon-IHC slide aliases, verifies every local
checksum and pixel fingerprint, uploads reviewed public documentation, and
refuses publication.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import zenodo_deposit as base
import zenodo_mds_deposit as mds


ALIAS_RE = re.compile(r"^TQA_CIS_[A-Z2-7]{20}$")
EXPECTED_MDS_COUNT = 30
EXPECTED_MDS_BYTES = 40_580_793_856
MANIFEST_NAME = "tumorquantai_colon_immunoscore_mds_manifest.csv"
DATASET_FORMAT = "sanitized-mds-colon-immunoscore-v1"
PUBLIC_SUFFIXES = {".csv", ".json", ".md", ".html", ".png", ".txt", ".zip"}
PUBLIC_EXTENSIONLESS_NAMES = {"SHA256SUMS", "MD5SUMS"}


def deposit_immunoscore(**arguments):
    return mds.deposit_mds(
        **arguments,
        alias_re=ALIAS_RE,
        expected_count=EXPECTED_MDS_COUNT,
        expected_bytes=EXPECTED_MDS_BYTES,
        manifest_name=MANIFEST_NAME,
        dataset_format=DATASET_FORMAT,
    )


def public_directory_files(
    public_dir: Path | None,
    public_manifest: Path,
    explicit: list[str],
) -> list[str]:
    values = list(explicit)
    if public_dir is None:
        return values
    candidate = public_dir.expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_dir():
        raise base.DepositError("--public-dir must be a regular directory")
    directory = candidate.resolve()
    manifest = public_manifest.expanduser().resolve()
    for path in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
        if path.resolve() == manifest:
            continue
        if path.name == manifest.name:
            if (
                path.is_symlink()
                or not path.is_file()
                or base.digest_file(path.resolve()) != base.digest_file(manifest)
            ):
                raise base.DepositError(
                    "Public directory manifest copy differs from --public-manifest"
                )
            continue
        if (
            path.is_symlink()
            or not path.is_file()
            or (
                path.suffix.casefold() not in PUBLIC_SUFFIXES
                and path.name not in PUBLIC_EXTENSIONLESS_NAMES
            )
            or not base.SAFE_REMOTE_NAME_RE.fullmatch(path.name)
        ):
            raise base.DepositError(
                f"Public directory contains an unsafe artifact: {path.name}"
            )
        if any(
            token in path.name.casefold()
            for token in ("private", "secret", "token", "state", "linkage")
        ):
            raise base.DepositError(
                f"Public directory contains a private-looking artifact: {path.name}"
            )
        values.append(str(path))
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-manifest", required=True, type=Path)
    parser.add_argument("--private-mapping", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument(
        "--public-dir",
        type=Path,
        help="flat reviewed public artifact directory; manifest is not duplicated",
    )
    parser.add_argument("--token-env", default=base.DEFAULT_TOKEN_ENV)
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--api-url", default=base.DEFAULT_API_URL)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--replace-mismatched", action="store_true")
    parser.add_argument(
        "--adopt-expanded-release",
        action="store_true",
        help=(
            "adopt a reviewed public-artifact expansion of this exact draft; "
            "requires --replace-mismatched and never replaces MDS files"
        ),
    )
    parser.add_argument(
        "--extra-file",
        action="append",
        default=[],
        help="reviewed public PATH or PATH=REMOTE_NAME to add to the draft",
    )
    parser.add_argument("--plan", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        extras = public_directory_files(
            args.public_dir,
            args.public_manifest,
            args.extra_file,
        )
        result = deposit_immunoscore(
            public_manifest=args.public_manifest,
            private_mapping=args.private_mapping,
            metadata_file=args.metadata,
            state_file=args.state,
            token_env=args.token_env,
            token_file=args.token_file,
            api_url=args.api_url,
            retries=args.retries,
            workers=args.workers,
            replace_mismatched=args.replace_mismatched,
            adopt_expanded_release=args.adopt_expanded_release,
            plan=args.plan,
            extra_files=extras,
        )
    except (base.DepositError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
