#!/usr/bin/env python3
"""Resolve direct runtime profiles and reject CPU/GPU container mismatches."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GPU_IMAGE = (
    "carlosfarkas/lazyslide-histoplus@sha256:"
    "c4b02485d4549a56348cd09995ce0788a6acc8a3e1e600e986b644231a95bd25"
)
PROCESS_SELECTOR = "DISCOVER_SLIDES|PROCESS_SLIDE|AGGREGATE_COUNTS"
GPU_PROFILES = {
    "docker_gpu": "docker",
    "singularity_gpu": "singularity",
    "apptainer_gpu": "apptainer",
}


def resolved_profile(profile: str) -> str:
    nextflow = shutil.which("nextflow")
    if nextflow is None:
        raise RuntimeError("nextflow is required to resolve runtime profiles")
    completed = subprocess.run(
        [nextflow, "config", ".", "-profile", profile, "-flat"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"cannot resolve profile {profile}: {detail}")
    return completed.stdout


def profile_failures(profile: str, engine: str, resolved: str) -> list[str]:
    expected = {
        f"{engine}.enabled = true",
        "params.device = 'cuda'",
        f"params.container_image = '{GPU_IMAGE}'",
        (
            "process.'withName:"
            f"{PROCESS_SELECTOR}'.container = '{GPU_IMAGE}'"
        ),
    }
    return [
        f"{profile}: missing resolved setting {line}"
        for line in sorted(expected)
        if line not in resolved
    ]


def main() -> int:
    failures: list[str] = []
    for profile, engine in GPU_PROFILES.items():
        try:
            failures.extend(
                profile_failures(profile, engine, resolved_profile(profile))
            )
        except RuntimeError as exc:
            failures.append(str(exc))
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    print("Resolved GPU profiles: docker, singularity, apptainer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
