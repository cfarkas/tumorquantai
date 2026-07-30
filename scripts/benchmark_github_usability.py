#!/usr/bin/env python3
"""Collect a reproducible GitHub usability benchmark for TumorQuantAI.

The collector intentionally uses the authenticated ``gh api`` command instead of
scraping GitHub HTML. It stores only repository metadata, path-derived signals,
and short, paraphrased assessments; README bodies are never written to the
snapshot. Cached API responses default to /tmp so they cannot be committed by
accident.

Examples:
    python scripts/benchmark_github_usability.py \
      --output docs/maintainers/benchmark_data/2026-07-30.json \
      --markdown-output docs/maintainers/USABILITY_BENCHMARK.md

    python scripts/benchmark_github_usability.py --offline --cache-dir /tmp/tq-cache
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


REQUIRED_REPOSITORIES = (
    "lh3/minimap2",
    "nf-core/rnaseq",
    "nf-core/tools",
    "nextflow-io/nextflow",
    "mahmoodlab/TRIDENT",
    "mahmoodlab/CLAM",
    "TissueImageAnalytics/tiatoolbox",
    "SBU-BMI/wsinfer",
    "qupath/qupath",
    "Project-MONAI/MONAI",
    "rendeirolab/LazySlide",
    "slideflow/slideflow",
    "openslide/openslide",
    "computationalpathologygroup/ASAP",
)

# These projects were selected from the dated topic searches below because they
# are active, clearly relevant user-facing computational-pathology toolkits, and
# add teaching/sample-data patterns not already represented by the required set.
ADDITIONAL_REPOSITORIES = (
    "histolab/histolab",
    "Dana-Farber-AIOS/pathml",
)

DISCOVERY_QUERIES = (
    "topic:digital-pathology archived:false",
    "topic:whole-slide-imaging archived:false",
    "topic:computational-pathology archived:false",
    "topic:histopathology archived:false",
    "topic:nextflow archived:false",
    "topic:scientific-workflow archived:false",
)

# Producing a "first result" is not reliably machine-detectable from arbitrary
# README prose. These conservative manual counts are reviewed against the README
# and linked docs at snapshot time. ``None`` means that there is no single,
# defensible command sequence rather than silently treating it as zero.
FIRST_RESULT_COMMANDS: Mapping[str, int | None] = {
    "lh3/minimap2": 2,
    "nf-core/rnaseq": 2,
    "nf-core/tools": 2,
    "nextflow-io/nextflow": 3,
    "mahmoodlab/TRIDENT": 3,
    "mahmoodlab/CLAM": 4,
    "TissueImageAnalytics/tiatoolbox": 3,
    "SBU-BMI/wsinfer": 1,
    "qupath/qupath": None,
    "Project-MONAI/MONAI": 3,
    "rendeirolab/LazySlide": 3,
    "slideflow/slideflow": 3,
    "openslide/openslide": None,
    "computationalpathologygroup/ASAP": None,
    "histolab/histolab": 3,
    "Dana-Farber-AIOS/pathml": 3,
}

# Manual review supplements, rather than replaces, reproducible path/README
# heuristics. Values describe what a new visitor can find from the repository's
# landing page or its directly linked documentation on the snapshot date.
MANUAL_USABILITY: Mapping[str, Mapping[str, bool]] = {
    "lh3/minimap2": {
        "zero_credential_demo": True,
        "one_sample_path": True,
        "doctor_or_preflight": False,
        "expected_output_visual_or_tree": True,
        "troubleshooting_guide": False,
        "output_reference": True,
        "research_use_limitations": False,
        "model_or_data_license_guidance": False,
    },
    "nf-core/rnaseq": {
        "zero_credential_demo": True,
        "one_sample_path": True,
        "doctor_or_preflight": True,
        "expected_output_visual_or_tree": True,
        "troubleshooting_guide": True,
        "output_reference": True,
        "research_use_limitations": False,
        "model_or_data_license_guidance": True,
    },
    "nf-core/tools": {
        "zero_credential_demo": True,
        "one_sample_path": False,
        "doctor_or_preflight": True,
        "expected_output_visual_or_tree": True,
        "troubleshooting_guide": True,
        "output_reference": True,
        "research_use_limitations": False,
        "model_or_data_license_guidance": False,
    },
    "nextflow-io/nextflow": {
        "zero_credential_demo": True,
        "one_sample_path": True,
        "doctor_or_preflight": True,
        "expected_output_visual_or_tree": True,
        "troubleshooting_guide": True,
        "output_reference": True,
        "research_use_limitations": False,
        "model_or_data_license_guidance": False,
    },
    "mahmoodlab/TRIDENT": {
        "zero_credential_demo": False,
        "one_sample_path": True,
        "doctor_or_preflight": True,
        "expected_output_visual_or_tree": True,
        "troubleshooting_guide": True,
        "output_reference": True,
        "research_use_limitations": True,
        "model_or_data_license_guidance": True,
    },
    "mahmoodlab/CLAM": {
        "zero_credential_demo": False,
        "one_sample_path": True,
        "doctor_or_preflight": False,
        "expected_output_visual_or_tree": True,
        "troubleshooting_guide": True,
        "output_reference": True,
        "research_use_limitations": True,
        "model_or_data_license_guidance": True,
    },
    "TissueImageAnalytics/tiatoolbox": {
        "zero_credential_demo": True,
        "one_sample_path": True,
        "doctor_or_preflight": False,
        "expected_output_visual_or_tree": True,
        "troubleshooting_guide": True,
        "output_reference": True,
        "research_use_limitations": True,
        "model_or_data_license_guidance": True,
    },
    "SBU-BMI/wsinfer": {
        "zero_credential_demo": False,
        "one_sample_path": True,
        "doctor_or_preflight": False,
        "expected_output_visual_or_tree": True,
        "troubleshooting_guide": False,
        "output_reference": True,
        "research_use_limitations": True,
        "model_or_data_license_guidance": True,
    },
    "qupath/qupath": {
        "zero_credential_demo": True,
        "one_sample_path": True,
        "doctor_or_preflight": False,
        "expected_output_visual_or_tree": True,
        "troubleshooting_guide": True,
        "output_reference": True,
        "research_use_limitations": True,
        "model_or_data_license_guidance": True,
    },
    "Project-MONAI/MONAI": {
        "zero_credential_demo": True,
        "one_sample_path": True,
        "doctor_or_preflight": True,
        "expected_output_visual_or_tree": True,
        "troubleshooting_guide": True,
        "output_reference": True,
        "research_use_limitations": True,
        "model_or_data_license_guidance": True,
    },
    "rendeirolab/LazySlide": {
        "zero_credential_demo": True,
        "one_sample_path": True,
        "doctor_or_preflight": False,
        "expected_output_visual_or_tree": True,
        "troubleshooting_guide": False,
        "output_reference": True,
        "research_use_limitations": True,
        "model_or_data_license_guidance": True,
    },
    "slideflow/slideflow": {
        "zero_credential_demo": True,
        "one_sample_path": True,
        "doctor_or_preflight": True,
        "expected_output_visual_or_tree": True,
        "troubleshooting_guide": True,
        "output_reference": True,
        "research_use_limitations": True,
        "model_or_data_license_guidance": True,
    },
    "openslide/openslide": {
        "zero_credential_demo": False,
        "one_sample_path": False,
        "doctor_or_preflight": False,
        "expected_output_visual_or_tree": False,
        "troubleshooting_guide": True,
        "output_reference": True,
        "research_use_limitations": False,
        "model_or_data_license_guidance": False,
    },
    "computationalpathologygroup/ASAP": {
        "zero_credential_demo": False,
        "one_sample_path": True,
        "doctor_or_preflight": False,
        "expected_output_visual_or_tree": True,
        "troubleshooting_guide": True,
        "output_reference": True,
        "research_use_limitations": True,
        "model_or_data_license_guidance": True,
    },
    "histolab/histolab": {
        "zero_credential_demo": True,
        "one_sample_path": True,
        "doctor_or_preflight": False,
        "expected_output_visual_or_tree": True,
        "troubleshooting_guide": True,
        "output_reference": True,
        "research_use_limitations": True,
        "model_or_data_license_guidance": True,
    },
    "Dana-Farber-AIOS/pathml": {
        "zero_credential_demo": True,
        "one_sample_path": True,
        "doctor_or_preflight": False,
        "expected_output_visual_or_tree": True,
        "troubleshooting_guide": True,
        "output_reference": True,
        "research_use_limitations": True,
        "model_or_data_license_guidance": True,
    },
}


# Conservative corrections from the dated manual review. Keeping them separate
# makes judgments easy to audit without obscuring the raw path heuristics.
MANUAL_REVIEW_CORRECTIONS: Mapping[str, Mapping[str, bool | None]] = {
    "lh3/minimap2": {
        "sample_data": True,
        "expected_output_visual_or_tree": False,
        "troubleshooting_guide": True,
        "research_use_limitations": None,
        "model_or_data_license_guidance": None,
    },
    "nf-core/rnaseq": {
        "sample_data": True,
        "research_use_limitations": None,
        "model_or_data_license_guidance": None,
    },
    "nf-core/tools": {
        "sample_data": True,
        "doctor_or_preflight": False,
        "expected_output_visual_or_tree": False,
        "research_use_limitations": None,
        "model_or_data_license_guidance": None,
    },
    "nextflow-io/nextflow": {
        "sample_data": True,
        "research_use_limitations": None,
        "model_or_data_license_guidance": None,
    },
    "mahmoodlab/TRIDENT": {"sample_data": False},
    "mahmoodlab/CLAM": {
        "sample_data": True,
        "zero_credential_demo": True,
        "troubleshooting_guide": False,
    },
    "TissueImageAnalytics/tiatoolbox": {
        "sample_data": True,
        "troubleshooting_guide": False,
        "research_use_limitations": False,
    },
    "SBU-BMI/wsinfer": {"sample_data": False},
    "qupath/qupath": {"sample_data": True, "model_or_data_license_guidance": None},
    "Project-MONAI/MONAI": {
        "sample_data": True,
        "doctor_or_preflight": False,
        "research_use_limitations": False,
    },
    "rendeirolab/LazySlide": {
        "sample_data": True,
        "troubleshooting_guide": True,
        "research_use_limitations": False,
    },
    "slideflow/slideflow": {
        "sample_data": True,
        "doctor_or_preflight": False,
        "research_use_limitations": False,
    },
    "openslide/openslide": {
        "sample_data": False,
        "troubleshooting_guide": False,
        "research_use_limitations": None,
        "model_or_data_license_guidance": None,
    },
    "computationalpathologygroup/ASAP": {
        "sample_data": False,
        "troubleshooting_guide": False,
        "research_use_limitations": False,
        "model_or_data_license_guidance": None,
    },
    "histolab/histolab": {
        "sample_data": True,
        "troubleshooting_guide": False,
        "research_use_limitations": False,
    },
    "Dana-Farber-AIOS/pathml": {
        "sample_data": True,
        "troubleshooting_guide": False,
        "research_use_limitations": False,
        "model_or_data_license_guidance": False,
    },
}


DECLARED_LICENSE_IDENTIFIERS: Mapping[str, str] = {
    "lh3/minimap2": "MIT",
    "mahmoodlab/TRIDENT": "CC-BY-NC-ND-4.0",
    "TissueImageAnalytics/tiatoolbox": "BSD-3-Clause",
}


DOCUMENTATION_URLS: Mapping[str, str] = {
    "lh3/minimap2": "https://lh3.github.io/minimap2",
    "nf-core/rnaseq": "https://nf-co.re/rnaseq",
    "nf-core/tools": "https://nf-co.re/docs/nf-core-tools/",
    "nextflow-io/nextflow": "https://docs.seqera.io/nextflow/",
    "mahmoodlab/TRIDENT": "https://trident-docs.readthedocs.io/en/latest/",
    "mahmoodlab/CLAM": "http://clam.mahmoodlab.org",
    "TissueImageAnalytics/tiatoolbox": "https://tia-toolbox.readthedocs.io/en/stable/",
    "SBU-BMI/wsinfer": "https://wsinfer.readthedocs.io/",
    "qupath/qupath": "https://qupath.readthedocs.io/",
    "Project-MONAI/MONAI": "https://monai.readthedocs.io/en/latest/",
    "rendeirolab/LazySlide": "https://lazyslide.readthedocs.io/en/stable/",
    "slideflow/slideflow": "https://slideflow.dev/",
    "openslide/openslide": "https://openslide.org/#documentation",
    "computationalpathologygroup/ASAP": "https://computationalpathologygroup.github.io/ASAP/",
    "histolab/histolab": "https://histolab.readthedocs.io/en/latest/",
    "Dana-Farber-AIOS/pathml": "https://pathml.readthedocs.io/en/latest/",
}


class BenchmarkError(RuntimeError):
    """A collection error safe to show without command stderr or credentials."""


class GitHubClient:
    """Minimal cached wrapper around authenticated ``gh api`` requests."""

    def __init__(self, cache_dir: Path, *, offline: bool, refresh: bool) -> None:
        self.cache_dir = cache_dir
        self.offline = offline
        self.refresh = refresh
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, endpoint: str, fields: Mapping[str, str] | None) -> Path:
        canonical = json.dumps([endpoint, sorted((fields or {}).items())])
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def get(
        self,
        endpoint: str,
        *,
        fields: Mapping[str, str] | None = None,
        allow_missing: bool = False,
    ) -> Any:
        cache_path = self._cache_path(endpoint, fields)
        if cache_path.exists() and (self.offline or not self.refresh):
            return json.loads(cache_path.read_text(encoding="utf-8"))
        if self.offline:
            raise BenchmarkError(f"offline cache entry missing for {endpoint}")

        command = ["gh", "api", "-X", "GET", endpoint]
        for key, value in (fields or {}).items():
            command.extend(["-f", f"{key}={value}"])
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )
        if completed.returncode != 0:
            if allow_missing:
                return None
            raise BenchmarkError(f"GitHub API request failed for {endpoint}")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise BenchmarkError(
                f"GitHub API returned invalid JSON for {endpoint}"
            ) from exc
        cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        return payload


def utc_timestamp(value: str | None) -> str:
    if value:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return (
            parsed.astimezone(dt.timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
    return (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def decode_readme(payload: Mapping[str, Any] | None) -> str:
    if not payload or payload.get("encoding") != "base64":
        return ""
    try:
        raw = base64.b64decode(str(payload.get("content", "")), validate=False)
        return raw.decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def paths_from_tree(payload: Mapping[str, Any]) -> list[str]:
    paths = []
    for entry in payload.get("tree", []):
        if entry.get("type") == "blob" and isinstance(entry.get("path"), str):
            paths.append(entry["path"])
    return paths


def any_path(paths: Iterable[str], patterns: Sequence[str]) -> bool:
    lowered = [path.casefold() for path in paths]
    return any(
        re.search(pattern, path, flags=re.IGNORECASE)
        for path in lowered
        for pattern in patterns
    )


def first_100_has_command(readme: str) -> bool:
    lines = readme.splitlines()[:100]
    command_patterns = (
        r"^\s*(?:\$\s*)?(?:git clone|pipx? install|conda install|mamba install|docker run)\b",
        r"^\s*(?:\$\s*)?(?:nextflow run|java -jar|cargo install|brew install)\b",
        r"^\s*(?:\$\s*)?(?:python(?:3)?\s+-m|python(?:3)?\s+\S+\.py|\.\/\S+)\b",
    )
    return any(
        any(re.search(pattern, line) for pattern in command_patterns) for line in lines
    )


def repository_signals(paths: Sequence[str], readme: str) -> dict[str, bool]:
    return {
        "ci": any_path(
            paths,
            (
                r"^\.github/workflows/.+\.ya?ml$",
                r"^\.circleci/",
                r"^\.travis\.ya?ml$",
                r"^azure-pipelines\.ya?ml$",
                r"^\.?appveyor\.ya?ml$",
            ),
        ),
        "tests": any_path(
            paths,
            (
                r"(^|/)(tests?|testing)/.+",
                r"(^|/)(unit[-_]?tests?|unittest)/.+",
                r"(^|/)test_[^/]+\.py$",
                r"(^|/)[^/]+_test\.(py|go|java|cpp|c|rs)$",
            ),
        ),
        "issue_templates": any_path(paths, (r"^\.github/issue_template/",)),
        "citation_metadata": any_path(
            paths,
            (
                r"(^|/)citation\.cff$",
                r"(^|/)citation\.bib$",
                r"(^|/)codemeta\.json$",
                r"(^|/)zenodo\.json$",
            ),
        ),
        "sample_data": any_path(
            paths,
            (
                r"(^|/)(examples?|demos?|tutorials?)/.+\.(svs|tif|tiff|png|jpg|jpeg|csv|json|npy|npz)$",
                r"(^|/)sample[-_]?data/",
                r"(^|/)data/(sample|example|demo|test)",
            ),
        ),
        "first_100_readme_lines_have_install_or_quickstart_command": first_100_has_command(
            readme
        ),
    }


def collect_repository(client: GitHubClient, full_name: str) -> dict[str, Any]:
    info = client.get(f"repos/{full_name}")
    branch = str(info["default_branch"])
    encoded_branch = urllib.parse.quote(branch, safe="")
    tree_payload = client.get(
        f"repos/{full_name}/git/trees/{encoded_branch}", fields={"recursive": "1"}
    )
    readme_payload = client.get(f"repos/{full_name}/readme", allow_missing=True)
    releases = client.get(f"repos/{full_name}/releases", fields={"per_page": "10"})
    readme = decode_readme(readme_payload)
    paths = paths_from_tree(tree_payload)
    published_releases = [
        item
        for item in releases
        if not item.get("draft") and item.get("published_at") is not None
    ]
    latest_release = max(
        published_releases,
        key=lambda item: str(item["published_at"]),
        default=None,
    )
    homepage = (info.get("homepage") or "").strip() or None
    license_data = info.get("license") or {}
    api_license = license_data.get("spdx_id")
    declared_license = DECLARED_LICENSE_IDENTIFIERS.get(full_name)
    manual_review = {
        **MANUAL_USABILITY[full_name],
        **MANUAL_REVIEW_CORRECTIONS.get(full_name, {}),
    }

    return {
        "repository": full_name,
        "url": info.get("html_url"),
        "description": info.get("description"),
        "required_set": full_name in REQUIRED_REPOSITORIES,
        "selection": (
            "required benchmark set"
            if full_name in REQUIRED_REPOSITORIES
            else "active computational-pathology toolkit found in topic search"
        ),
        "visibility": {
            "stars": info.get("stargazers_count"),
            "forks": info.get("forks_count"),
            # GitHub's watchers_count mirrors stars for repositories. The API's
            # subscribers_count is the distinct notification-subscriber metric.
            "watchers_api": info.get("watchers_count"),
            "subscribers": info.get("subscribers_count"),
        },
        "activity": {
            "archived": bool(info.get("archived")),
            "pushed_at": info.get("pushed_at"),
            "latest_release_date": (
                latest_release.get("published_at") if latest_release else None
            ),
            "latest_release_tag": (
                latest_release.get("tag_name") if latest_release else None
            ),
        },
        "metadata": {
            "license_spdx_api": api_license,
            "license_identifier": declared_license or api_license,
            "license_basis": (
                "repository license or terms notice"
                if declared_license
                else "GitHub repository API"
            ),
            "primary_language": info.get("language"),
            "repository_homepage": homepage,
            "documentation_url": DOCUMENTATION_URLS[full_name],
            "documentation_url_basis": "landing README or official repository homepage",
            "default_branch": branch,
            "has_pages": bool(info.get("has_pages")),
        },
        "repository_signals": {
            "releases": bool(published_releases),
            **repository_signals(paths, readme),
        },
        "usability_assessment": {
            "first_result_command_count": FIRST_RESULT_COMMANDS[full_name],
            "first_result_command_count_basis": (
                "manual conservative count from landing-page or directly linked quickstart; "
                "null means no single comparable CLI path"
            ),
            **manual_review,
            "review_basis": "manual landing-page/direct-doc review at snapshot date",
        },
    }


def collect_discovery(client: GitHubClient) -> list[dict[str, Any]]:
    collected = []
    for query in DISCOVERY_QUERIES:
        payload = client.get(
            "search/repositories",
            fields={
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": "10",
            },
        )
        results = [
            {
                "repository": item.get("full_name"),
                "stars": item.get("stargazers_count"),
                "archived": bool(item.get("archived")),
            }
            for item in payload.get("items", [])
        ]
        collected.append({"query": query, "top_results": results})
    return collected


def rate_limit_summary(client: GitHubClient) -> dict[str, Any] | None:
    payload = client.get("rate_limit", allow_missing=True)
    if not payload:
        return None
    resources = payload.get("resources", {})
    return {
        name: {
            "limit": data.get("limit"),
            "remaining": data.get("remaining"),
            "reset_epoch": data.get("reset"),
        }
        for name, data in resources.items()
        if name in {"core", "search"}
    }


def collect_snapshot(client: GitHubClient, timestamp: str) -> dict[str, Any]:
    discovery = collect_discovery(client)
    repositories = [
        collect_repository(client, full_name)
        for full_name in (*REQUIRED_REPOSITORIES, *ADDITIONAL_REPOSITORIES)
    ]
    return {
        "schema_version": 1,
        "collected_at": timestamp,
        "source": "GitHub REST API v3 via authenticated gh api",
        "method": {
            "required_repository_count": len(REQUIRED_REPOSITORIES),
            "additional_repository_count": len(ADDITIONAL_REPOSITORIES),
            "tree_scan": "default branch recursive Git tree at collection time",
            "readme_window": "first approximately 100 source lines",
            "manual_review": "landing README and directly linked documentation",
            "discovery_result_limit_per_query": 10,
        },
        "discovery": discovery,
        "repositories": repositories,
        "github_rate_limit_after_collection": rate_limit_summary(client),
        "limitations": [
            "Stars, forks, subscribers, releases, and recent pushes are imperfect visibility and activity proxies; they are not usage or quality measurements.",
            "GitHub watchers_count currently aliases stargazers_count; subscribers is the distinct notification-watch metric.",
            "Path and README heuristics can miss documentation hosted elsewhere or classify fixture assets as sample data.",
            "First-result command counts are conservative manual comparisons and are not meaningful for GUI-first projects or low-level libraries.",
            "Feature presence records discoverability, not correctness, accessibility, scientific validity, or clinical fitness.",
            "Repository contents and metrics change after the timestamp; this compact snapshot intentionally excludes README bodies and personal data.",
        ],
    }


def yes_no(value: Any) -> str:
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return "—"


def command_count(value: Any) -> str:
    return str(value) if isinstance(value, int) else "N/A"


def date_only(value: Any) -> str:
    return str(value)[:10] if value else "—"


def render_markdown(snapshot: Mapping[str, Any], snapshot_path: Path) -> str:
    repos = snapshot["repositories"]
    collected_at = str(snapshot["collected_at"])
    lines = [
        "# GitHub usability benchmark",
        "",
        f"**Snapshot:** {collected_at}  ",
        "**Purpose:** identify transferable onboarding patterns for TumorQuantAI; this is not a project ranking.",
        "",
        "## Methodology",
        "",
        "The benchmark uses the GitHub REST API through the authenticated `gh api` CLI. It covers the 14 requested repositories plus two active computational-pathology toolkits selected from six topic searches. For each default branch, the collector records repository metadata, a recursive path inventory, release metadata, and whether the first approximately 100 README source lines contain an install or quickstart command. It never stores README bodies.",
        "",
        "Path-derived signals cover CI, tests, issue templates, citation metadata, and bundled sample-data candidates. The higher-level onboarding fields and conservative count of shell commands needed to reach a first result were reviewed from each landing page and directly linked documentation. `N/A` means a GUI-first project or library has no defensible comparable first-result CLI sequence.",
        "",
        f"The compact machine-readable evidence is [`{snapshot_path.name}`](benchmark_data/{snapshot_path.name}). The collector is [`scripts/benchmark_github_usability.py`](https://github.com/cfarkas/tumorquantai/blob/main/scripts/benchmark_github_usability.py).",
        "",
        "### Sources and limitations",
        "",
        "Primary sources are each project's GitHub repository, GitHub API metadata, release API, and documentation URL reported by the repository. The six discovery queries were `digital-pathology`, `whole-slide-imaging`, `computational-pathology`, `histopathology`, `nextflow`, and `scientific-workflow`, each constrained to non-archived repositories and sorted by stars.",
        "",
        "Stars, forks, notification subscribers, releases, and recent pushes are visibility or activity proxies—not measures of real-world usage, quality, scientific validity, or clinical fitness. GitHub's `watchers_count` currently duplicates the star count, so the report shows the distinct `subscribers_count`. Path heuristics can miss external documentation or treat fixture assets as sample data. Manual feature review measures whether guidance was discoverable, not whether every documented path still executes. Values will change after the snapshot date.",
        "",
        "## Comparison",
        "",
        "| Repository | Stars | Forks | Subscribers | Last push | Latest release | License | Language | Docs |",
        "|---|---:|---:|---:|---|---|---|---|---|",
    ]
    for repo in repos:
        visibility = repo["visibility"]
        activity = repo["activity"]
        metadata = repo["metadata"]
        docs = (
            "[docs]({})".format(metadata["documentation_url"])
            if metadata["documentation_url"]
            else "—"
        )
        lines.append(
            "| [{name}]({url}) | {stars} | {forks} | {subscribers} | {push} | {release} | {license} | {language} | {docs} |".format(
                name=repo["repository"],
                url=repo["url"],
                stars=visibility["stars"],
                forks=visibility["forks"],
                subscribers=visibility["subscribers"],
                push=date_only(activity["pushed_at"]),
                release=date_only(activity["latest_release_date"]),
                license=metadata["license_identifier"] or "None detected",
                language=metadata["primary_language"] or "—",
                docs=docs,
            )
        )
    lines.extend(
        [
            "",
            "Archived state was also checked: every repository included in this dated comparison was active (not archived). License identifiers come from the GitHub API except for minimap2, TRIDENT, and TIAToolbox, whose repository license or terms notice was used because the API returned `NOASSERTION`. `None detected` is not legal advice and not evidence that reuse is permitted.",
            "",
            "### Repository and onboarding signals",
            "",
            "| Repository | CI | Tests | Issues | Citation | Sample data | Command near top | Commands to result | Demo | One sample | Doctor | Output example | Troubleshooting | Output reference | Research limits | Model/data license |",
            "|---|:---:|:---:|:---:|:---:|:---:|:---:|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
        ]
    )
    for repo in repos:
        signals = repo["repository_signals"]
        ux = repo["usability_assessment"]
        lines.append(
            "| {name} | {ci} | {tests} | {issues} | {citation} | {sample} | {top} | {count} | {demo} | {one} | {doctor} | {output} | {trouble} | {reference} | {limits} | {licenses} |".format(
                name=repo["repository"],
                ci=yes_no(signals["ci"]),
                tests=yes_no(signals["tests"]),
                issues=yes_no(signals["issue_templates"]),
                citation=yes_no(signals["citation_metadata"]),
                sample=yes_no(ux["sample_data"]),
                top=yes_no(
                    signals["first_100_readme_lines_have_install_or_quickstart_command"]
                ),
                count=command_count(ux["first_result_command_count"]),
                demo=yes_no(ux["zero_credential_demo"]),
                one=yes_no(ux["one_sample_path"]),
                doctor=yes_no(ux["doctor_or_preflight"]),
                output=yes_no(ux["expected_output_visual_or_tree"]),
                trouble=yes_no(ux["troubleshooting_guide"]),
                reference=yes_no(ux["output_reference"]),
                limits=yes_no(ux["research_use_limitations"]),
                licenses=yes_no(ux["model_or_data_license_guidance"]),
            )
        )
    lines.extend(
        [
            "",
            "Feature labels are deliberately narrow: a demo must run without private credentials; a one-sample path must be visible to a newcomer; a doctor/preflight item must perform environment checks rather than merely list prerequisites; and an output reference must explain produced artifacts, not only show a screenshot. An em dash means the item is not applicable to that project type.",
            "",
            "## Patterns adopted for TumorQuantAI",
            "",
            "- **Command-first landing page:** minimap2 demonstrates that useful commands can precede long conceptual material. TumorQuantAI should show the structural demo immediately, followed by the real one-slide and inspect-only paths.",
            "- **Test before expensive work:** nf-core's test profiles and Nextflow's reproducible execution model support a credential-free fixture workflow before model access, GPU use, or WSI downloads.",
            "- **One cautious slide plus preflight:** TRIDENT's environment checks, single-slide progression, resume guidance, and explicit run state are a strong model for `doctor`, `status`, and a 1% smoke preset.",
            "- **One high-level command:** WSInfer shows the value of a compact inference entry point. TumorQuantAI can expose a short wrapper while printing its expanded legacy/Nextflow command for auditability.",
            "- **Teaching examples for several skill levels:** TIAToolbox, LazySlide, MONAI, histolab, and PathML use runnable examples or notebooks to bridge first use and API-level reference. TumorQuantAI should separate a synthetic structural demo, public one-slide tutorial, and expert reference.",
            "- **Visible outputs and support routes:** nf-core, QuPath, CLAM, Slideflow, and TIAToolbox make output interpretation, limitations, and troubleshooting discoverable. TumorQuantAI should link the audit, matrices, overlays, and per-slide summary from one local start page.",
            "- **Research and license boundaries:** pathology/ML projects commonly distinguish software terms from model or dataset conditions. TumorQuantAI should state research-only scope and keep software, HistoPLUS, and Zenodo dataset citations and permissions separate.",
            "",
            "## Patterns deliberately rejected",
            "",
            "- **Popularity as a quality score:** stars and forks are retained only as dated visibility proxies; they do not justify scientific or UX claims.",
            "- **Badge-only evidence of readiness:** badges cannot replace a local, actionable doctor check and a fixture-based demo.",
            "- **Network, GPU, or gated weights in the first success path:** those dependencies make normal CI and beginner diagnosis fragile, so the first result must be structural and offline-capable.",
            "- **A magic wrapper that hides execution details:** a beginner façade is useful only if it preserves direct Nextflow/run-script access, prints the expanded command with secrets redacted, and records provenance.",
            "- **GUI or notebook as the only reproducible interface:** both can be valuable teaching surfaces, but the canonical workflow must remain scriptable, resumable, and testable headlessly.",
            "- **Implicit permission from public source code:** a visible repository without a declared license does not grant broad reuse permission. TumorQuantAI's license remains an explicit owner decision.",
            "- **Copied project prose or visual branding:** this benchmark adopts interaction patterns only; labels are short categorical summaries and no README body is retained.",
            "",
            "## Reproduce or refresh",
            "",
            "```bash",
            f"python scripts/benchmark_github_usability.py --output docs/maintainers/benchmark_data/{snapshot_path.name} --markdown-output docs/maintainers/USABILITY_BENCHMARK.md",
            "```",
            "",
            "The command requires an authenticated GitHub CLI. Use `--offline` only after populating the specified cache; the default cache is under `/tmp` and is not part of the repository. Review the manual first-result counts and onboarding classifications whenever refreshing the snapshot.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="dated JSON snapshot"
    )
    parser.add_argument(
        "--markdown-output", type=Path, help="optional generated Markdown report"
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(
            os.environ.get(
                "TUMORQUANTAI_BENCHMARK_CACHE",
                "/tmp/tumorquantai-github-benchmark-cache",
            )
        ),
        help="API cache outside Git (default: /tmp/tumorquantai-github-benchmark-cache)",
    )
    parser.add_argument("--timestamp", help="ISO-8601 collection timestamp override")
    parser.add_argument("--offline", action="store_true", help="read cache only")
    parser.add_argument("--refresh", action="store_true", help="ignore existing cache")
    args = parser.parse_args(argv)
    if args.offline and args.refresh:
        parser.error("--offline and --refresh cannot be combined")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    timestamp = utc_timestamp(args.timestamp)
    client = GitHubClient(args.cache_dir, offline=args.offline, refresh=args.refresh)
    try:
        snapshot = collect_snapshot(client, timestamp)
    except BenchmarkError as exc:
        print(f"benchmark collection failed: {exc}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(
            render_markdown(snapshot, args.output), encoding="utf-8"
        )
    print(
        f"wrote {len(snapshot['repositories'])} repositories to {args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
