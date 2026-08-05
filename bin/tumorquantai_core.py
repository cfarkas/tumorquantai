#!/usr/bin/env python3
"""Standard-library helpers for the TumorQuantAI command.

This module deliberately contains orchestration and reporting only.  Scientific
image processing remains in the existing worker and Nextflow workflow.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0.0"
RELEASE_TAG = f"v{VERSION}"
DATASET_RECORD = "21466410"
DATASET_DOI = "10.5281/zenodo.21466410"
DATASET_RELEASE = "v0.4.0"
TUTORIAL_SAMPLE = "TumorQuantAI_LymphomaWSI_022"
TUTORIAL_FILE = f"{TUTORIAL_SAMPLE}.mds"
TUTORIAL_SIZE = 125_350_400
TUTORIAL_MD5 = "94bb5b08ccf1957f8c42a579e8b33cfb"
TUTORIAL_SHA256 = "db2988b5c6bc791510cec4127106509e604e577feafdb15b94c149043ed7067a"
TUTORIAL_SOURCE_MPP = 0.261780
DEFAULT_SEED = 20260709
TARGET_MPP = 0.5
MODEL_REVISION = "cde2eee81af9e39b03802fc33d4f284733b5ee5e"
CPU_CONTAINER = "carlosfarkas/lazyslide-histoplus@sha256:413bed6b55bc86923321c61453c18ece678da3c125ae44dcbd5f6c3bce7115d4"
GPU_CONTAINER = "carlosfarkas/lazyslide-histoplus@sha256:c4b02485d4549a56348cd09995ce0788a6acc8a3e1e600e986b644231a95bd25"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_PREFLIGHT = 3
EXIT_INPUT = 4
EXIT_DATA = 5
EXIT_MODEL = 6
EXIT_WORKFLOW = 10

RUN_MANIFEST = Path("workflow_metadata/tumorquantai_run.json")
REPORT_JSON = "tumorquantai_report.json"
START_HERE = "START_HERE.html"
RUN_SUMMARY = "RUN_SUMMARY.txt"
CANONICAL_TOKEN = Path("~/.config/tumorquantai/hf_token").expanduser()
LEGACY_TOKEN = Path("~/.config/lazyslide-histoplus/hf_token").expanduser()
OVERLAY_FILES = (
    "overlays/overview_with_zoom_box.png",
    "overlays/zoom_overlay_celltypes.png",
    "overlays/celltypes_overview_and_zoom.png",
    "overlays/celltypes_overview_and_zoom.pdf",
)

_TOKEN_RE = re.compile(r"(?i)(?:hf|api|access)[_-]?token\s*[=:]\s*\S+")
_HF_VALUE_RE = re.compile(r"\bhf_[A-Za-z0-9]{8,}\b")
_QUOTED_ABSOLUTE_PATH_RE = re.compile(r"'/(?:[^']*)'|\"/(?:[^\"]*)\"")
_ABSOLUTE_PATH_RE = re.compile(r"(?<![A-Za-z0-9_:/~>.])/(?!/)[^\s'\"<>]*")


class TumorQuantAIError(RuntimeError):
    """Expected user-facing error with a stable CLI exit code."""

    def __init__(self, message: str, exit_code: int = EXIT_INPUT) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_text(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def write_json(path: Path, payload: Any, mode: int = 0o644) -> None:
    atomic_text(path, json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", mode)


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TumorQuantAIError(f"Cannot read JSON file {path}: {exc}", EXIT_DATA) from exc
    if not isinstance(payload, dict):
        raise TumorQuantAIError(f"Expected a JSON object in {path}", EXIT_DATA)
    return payload


def format_bytes(value: int | float | None) -> str:
    if value is None:
        return "unknown"
    number = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(number) < 1024 or unit == "TiB":
            return f"{number:.1f} {unit}" if unit != "B" else f"{int(number)} B"
        number /= 1024
    return f"{number:.1f} TiB"


def command_output(command: Sequence[str], timeout: float = 15.0) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            list(command), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return completed.returncode, completed.stdout.strip()


def git_commit() -> str:
    code, output = command_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"])
    return output.splitlines()[-1] if code == 0 and output else "unknown"


def redact_text(value: str, *, paths: bool = False) -> str:
    redacted = _TOKEN_RE.sub("token=<redacted>", value)
    redacted = _HF_VALUE_RE.sub("<redacted-token>", redacted)
    if paths:
        home = str(Path.home())
        if home and home != "/":
            escaped_home = re.escape(home)
            redacted = re.sub(
                rf"'{escaped_home}(?:/[^']*)?'", "'~/<redacted-path>'", redacted
            )
            redacted = re.sub(
                rf'"{escaped_home}(?:/[^"]*)?"', '"~/<redacted-path>"', redacted
            )
            redacted = re.sub(
                rf"{escaped_home}(?:/[^\s'\"<>]*)?", "~/<redacted-path>", redacted
            )
        redacted = redacted.replace(str(ROOT), "<repository>")
        redacted = _QUOTED_ABSOLUTE_PATH_RE.sub("'<absolute-path>'", redacted)
        redacted = _ABSOLUTE_PATH_RE.sub("<absolute-path>", redacted)
    return redacted


def shell_join(
    command: Sequence[str], secret_values: Iterable[str] = (), *, paths: bool = False
) -> str:
    secret_set = {str(value) for value in secret_values if value}
    rendered = ["<redacted-path>" if item in secret_set else item for item in command]
    return redact_text(shlex.join(rendered), paths=paths)


def nearest_existing(path: Path) -> Path:
    candidate = path.expanduser().absolute()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def associated_cache_directory(output: Path) -> Path:
    resolved = output.expanduser().resolve()
    return resolved.parent / f".{resolved.name}-tumorquantai-cache"


def mount_details(path: Path) -> dict[str, str]:
    existing = nearest_existing(path)
    code, output = command_output(
        ["findmnt", "-T", str(existing), "-n", "-o", "TARGET,FSTYPE,SOURCE"], timeout=5
    )
    fields = output.split(None, 2) if code == 0 else []
    return {
        "target": fields[0] if fields else "unknown",
        "filesystem": fields[1] if len(fields) > 1 else "unknown",
        "source": fields[2] if len(fields) > 2 else "unknown",
    }


def df_details(path: Path) -> dict[str, Any]:
    """Return the capacity row from an explicit ``df -hT`` check."""
    existing = nearest_existing(path)
    code, output = command_output(["df", "-hT", str(existing)], timeout=10)
    lines = [line for line in output.splitlines() if line.strip()]
    return {
        "ok": code == 0 and len(lines) >= 2,
        "target": redact_text(str(existing), paths=True),
        "row": lines[-1] if len(lines) >= 2 else "",
    }


def validate_large_data_root(path: Path) -> dict[str, str]:
    """Reject repository, home, root, and unverifiable tutorial data roots."""
    resolved = path.expanduser().resolve(strict=False)
    repository = ROOT.resolve()
    home = Path.home().resolve()
    if resolved == repository or repository in resolved.parents:
        raise TumorQuantAIError(
            "Tutorial data cannot be stored inside the repository; choose mounted storage.",
            EXIT_PREFLIGHT,
        )
    if resolved == home or home in resolved.parents or resolved == Path("/home") or Path("/home") in resolved.parents:
        raise TumorQuantAIError(
            "Tutorial data cannot be stored under /home; choose mounted storage.",
            EXIT_PREFLIGHT,
        )
    mount = mount_details(resolved)
    if mount.get("target") in {None, "", "unknown", "/"}:
        raise TumorQuantAIError(
            "A non-root mounted filesystem could not be verified for tutorial data.",
            EXIT_PREFLIGHT,
        )
    return mount


def writable_probe(path: Path, *, create: bool = True) -> tuple[bool, str]:
    target = path.expanduser().absolute()
    try:
        if create:
            target.mkdir(parents=True, exist_ok=True)
            directory = target
        else:
            directory = nearest_existing(target)
        descriptor, probe = tempfile.mkstemp(prefix=".tumorquantai-write-", dir=directory)
        os.close(descriptor)
        os.unlink(probe)
    except OSError as exc:
        return False, str(exc)
    return True, "write test passed"


def storage_preflight(
    output: Path, work: Path, required_bytes: int, *, create: bool = True
) -> dict[str, Any]:
    output = output.expanduser().absolute()
    work = work.expanduser().absolute()
    output_ok, output_note = writable_probe(output, create=create)
    work_ok, work_note = writable_probe(work, create=create)
    existing = nearest_existing(output)
    usage = shutil.disk_usage(existing)
    same_filesystem = os.stat(nearest_existing(output)).st_dev == os.stat(nearest_existing(work)).st_dev
    mount = mount_details(output)
    df = df_details(output)
    result = {
        "output_writable": output_ok,
        "work_writable": work_ok,
        "output_note": output_note,
        "work_note": work_note,
        "free_bytes": usage.free,
        "required_bytes": int(required_bytes),
        "enough_space": usage.free >= required_bytes,
        "same_filesystem": same_filesystem,
        "mount": mount,
        "df": df,
    }
    result["ok"] = (
        output_ok
        and work_ok
        and result["enough_space"]
        and same_filesystem
        and mount.get("target") not in {None, "", "unknown"}
        and bool(df.get("ok"))
    )
    return result


def resolve_token_file(explicit: Path | None = None) -> tuple[Path | None, str, str | None]:
    configured = os.environ.get("TUMORQUANTAI_HF_TOKEN_FILE", "").strip()
    if configured:
        return Path(configured).expanduser().resolve(), "TUMORQUANTAI_HF_TOKEN_FILE", None
    if explicit is not None:
        return explicit.expanduser().resolve(), "command-line file path", None
    if CANONICAL_TOKEN.is_file():
        return CANONICAL_TOKEN, "canonical file", None
    compatible = os.environ.get("HF_TOKEN_FILE", "").strip()
    if compatible:
        return (
            Path(compatible).expanduser().resolve(),
            "legacy HF_TOKEN_FILE environment",
            "Legacy HF_TOKEN_FILE is supported for automation; prefer TUMORQUANTAI_HF_TOKEN_FILE.",
        )
    if LEGACY_TOKEN.is_file():
        return (
            LEGACY_TOKEN,
            "legacy file",
            "Legacy token path detected; move it to ~/.config/tumorquantai/hf_token.",
        )
    return None, "not configured", None


def token_file_ready(path: Path | None) -> tuple[bool, str]:
    if path is None:
        return False, "no token file configured"
    candidate = path.expanduser()
    try:
        if candidate.is_symlink() or not candidate.is_file():
            return False, "configured token path is not a regular file"
        if stat.S_IMODE(candidate.stat().st_mode) & 0o077:
            return False, "token file permissions should be 0600"
        with candidate.open("rb") as handle:
            content = handle.read(16 * 1024 + 1)
        if not content.strip() or len(content) > 16 * 1024:
            return False, "token file is empty or unexpectedly large"
    except OSError as exc:
        return False, f"token file is unreadable: {exc.strerror or exc}"
    return True, "token file is readable with private permissions"


def model_access(local_weight: Path | None, token_file: Path | None) -> dict[str, Any]:
    configured_weight = local_weight
    if configured_weight is None and os.environ.get("HISTOPLUS_WEIGHT_FILE", "").strip():
        configured_weight = Path(os.environ["HISTOPLUS_WEIGHT_FILE"]).expanduser()
    if configured_weight is not None:
        configured_weight = configured_weight.expanduser().resolve()
        ready = configured_weight.is_file() and not configured_weight.is_symlink()
        return {
            "ready": ready,
            "method": "authorized local weight file",
            "note": "local weight file is readable" if ready else "local weight file is missing",
            "weight": configured_weight,
            "token": None,
        }
    token_ready, note = token_file_ready(token_file)
    if not token_ready and bool(os.environ.get("HF_TOKEN", "").strip()):
        return {
            "ready": True,
            "method": "existing HF_TOKEN environment",
            "note": "token value is present and was not inspected or recorded",
            "weight": None,
            "token": None,
        }
    return {
        "ready": token_ready,
        "method": "authorized token file" if token_ready else "not configured",
        "note": note,
        "weight": None,
        "token": token_file if token_ready else None,
    }


def _version_tuple(text: str) -> tuple[int, ...]:
    match = re.search(r"(?<!\d)(\d+)(?:\.(\d+))?(?:\.(\d+))?", text)
    if not match:
        return ()
    return tuple(int(value or 0) for value in match.groups())


def check_record(code: str, status_value: str, item: str, detail: str, action: str) -> dict[str, str]:
    return {"code": code, "status": status_value, "item": item, "detail": detail, "next_action": action}


def online_check(url: str, code: str, label: str) -> dict[str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": f"TumorQuantAI/{VERSION}"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status_code = getattr(response, "status", 200)
        if 200 <= status_code < 400:
            return check_record(code, "PASS", label, f"HTTP {status_code}", "No action required.")
        return check_record(code, "WARN", label, f"HTTP {status_code}", "Retry the online check later.")
    except (OSError, urllib.error.URLError) as exc:
        return check_record(code, "WARN", label, redact_text(str(exc), paths=True), "Check network access and retry with --online.")


def doctor_checks(
    *, output: Path | None = None, work: Path | None = None,
    input_path: Path | None = None, online: bool = False,
    explicit_token: Path | None = None, local_weight: Path | None = None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    linux = sys.platform.startswith("linux")
    checks.append(check_record("TQA-OS", "PASS" if linux else "FAIL", f"OS: {platform.system()}", platform.platform(), "Use a supported Linux host." if not linux else "No action required."))
    machine = platform.machine() or "unknown"
    checks.append(check_record("TQA-ARCH", "PASS" if machine in {"x86_64", "amd64", "aarch64", "arm64"} else "WARN", f"Architecture: {machine}", "Architecture was detected.", "Confirm container support for this architecture." if machine not in {"x86_64", "amd64", "aarch64", "arm64"} else "No action required."))

    for name, command, minimum, code in (
        ("Java", ["java", "-version"], (17, 0, 0), "TQA-JAVA"),
        ("Nextflow", ["nextflow", "-version"], (24, 10, 0), "TQA-NEXTFLOW"),
    ):
        if shutil.which(command[0]) is None:
            checks.append(check_record(code, "FAIL", f"{name}: not found", f"{name} is needed for real runs.", f"Install {name}; see docs/how-to/install.md."))
            continue
        return_code, text = command_output(command)
        version = _version_tuple(text)
        ok = return_code == 0 and version >= minimum
        detail = redact_text(text.splitlines()[0] if text else "version unavailable", paths=True)
        checks.append(check_record(code, "PASS" if ok else "FAIL", f"{name}: {'.'.join(map(str, version)) if version else 'unknown'}", detail, "No action required." if ok else f"Install {name} >= {'.'.join(map(str, minimum))}."))

    docker_installed = shutil.which("docker") is not None
    docker = docker_installed
    docker_version: tuple[int, ...] = ()
    docker_detail = "command not found"
    if docker_installed:
        docker_code, docker_text = command_output(["docker", "--version"])
        docker_version = _version_tuple(docker_text)
        docker_detail = redact_text(docker_text.splitlines()[0] if docker_text else "version unavailable", paths=True)
        docker = docker_code == 0 and docker_version >= (24, 0, 0)
    checks.append(check_record(
        "TQA-DOCKER-CLI", "PASS" if docker else "FAIL",
        f"Docker CLI: {'.'.join(map(str, docker_version)) if docker_version else 'not ready'}",
        docker_detail,
        "No action required." if docker else "Install Docker 24+ for containerized inference, or use an intentionally prepared local profile.",
    ))
    daemon = False
    if docker_installed:
        daemon_code, daemon_text = command_output(["docker", "info"], timeout=12)
        daemon = daemon_code == 0
        checks.append(check_record("TQA-DOCKER-DAEMON", "PASS" if daemon else "FAIL", "Docker daemon", "reachable" if daemon else redact_text(daemon_text[-240:], paths=True), "No action required." if daemon else "Start Docker and grant this user daemon access."))
    else:
        checks.append(check_record(
            "TQA-DOCKER-DAEMON", "FAIL", "Docker daemon", "not checked because the Docker CLI is absent",
            "Install Docker 24+ before checking daemon access, or use an intentionally prepared local profile.",
        ))

    gpu = False
    if shutil.which("nvidia-smi"):
        gpu_code, gpu_text = command_output(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], timeout=10)
        gpu = gpu_code == 0
        checks.append(check_record("TQA-GPU", "PASS" if gpu else "WARN", "NVIDIA GPU", redact_text(gpu_text[:300], paths=True) if gpu_text else "not visible", "No action required." if gpu else "Use --profile cpu or repair NVIDIA visibility."))
    else:
        checks.append(check_record("TQA-GPU", "WARN", "NVIDIA GPU", "nvidia-smi is not available", "Use --profile cpu; a GPU is optional."))
    nvidia_runtime = False
    runtime_detail = "Docker daemon is unavailable"
    if daemon:
        runtime_code, runtime_text = command_output(
            ["docker", "info", "--format", "{{json .Runtimes}}"], timeout=10
        )
        nvidia_runtime = runtime_code == 0 and "nvidia" in runtime_text.lower()
        runtime_detail = "NVIDIA runtime is registered" if nvidia_runtime else "NVIDIA runtime is not registered"
    checks.append(check_record(
        "TQA-GPU-RUNTIME",
        "PASS" if gpu and nvidia_runtime else "WARN",
        "NVIDIA container runtime",
        runtime_detail if gpu else "GPU execution is optional; host GPU is not ready",
        "No action required." if gpu and nvidia_runtime else "Use --profile cpu or configure NVIDIA Container Toolkit before --profile gpu.",
    ))
    checks.append(check_record("TQA-CPU", "PASS", "CPU fallback", f"{os.cpu_count() or 1} logical CPU(s) visible", "Use --profile cpu when a GPU is unavailable."))

    token, source, warning = resolve_token_file(explicit_token)
    access = model_access(local_weight, token)
    if warning:
        checks.append(check_record("TQA-AUTH-LEGACY", "WARN", "Legacy credential path", warning, "Move the file with permissions preserved; do not copy its contents into an issue."))
    checks.append(check_record("TQA-AUTH", "PASS" if access["ready"] else "WARN", "HistoPLUS access (optional for demo/inspect)", f"{access['method']}: {access['note']}; source={source}", "No action required." if access["ready"] else "Follow docs/how-to/model-access.md before real inference."))

    mount_safety_errors: list[str] = []
    unsafe_explicit_paths: set[str] = set()
    for label, selected_path in (("output", output), ("work", work)):
        if selected_path is None:
            continue
        try:
            validate_large_data_root(selected_path)
        except TumorQuantAIError as exc:
            mount_safety_errors.append(f"{label}: {exc}")
            unsafe_explicit_paths.add(label)

    configured_cache = os.environ.get("TUMORQUANTAI_CACHE", "").strip()
    cache_safety_error = ""
    if configured_cache:
        cache = Path(configured_cache).expanduser()
        try:
            validate_large_data_root(cache)
        except TumorQuantAIError as exc:
            cache_safety_error = f"configured cache: {exc}"
        create_cache = not cache_safety_error
    elif output is not None:
        cache = associated_cache_directory(output)
        if "output" in unsafe_explicit_paths:
            cache_safety_error = "output path failed mounted-path validation; cache was not created"
        else:
            try:
                validate_large_data_root(cache)
            except TumorQuantAIError as exc:
                cache_safety_error = f"output-associated cache: {exc}"
        create_cache = not cache_safety_error
    else:
        cache = Path.cwd()
        create_cache = False
    cache_writable, cache_note = writable_probe(cache, create=create_cache)
    cache_ok = cache_writable and not cache_safety_error
    if cache_safety_error:
        cache_note = cache_safety_error
    checks.append(check_record(
        "TQA-CACHE", "PASS" if cache_ok else "FAIL", "Writable output-associated cache filesystem",
        redact_text(cache_note, paths=True),
        "No action required." if cache_ok else "Choose an output on a writable mounted filesystem or set TUMORQUANTAI_CACHE there.",
    ))

    if input_path is not None:
        candidate = input_path.expanduser()
        readable = candidate.exists() and os.access(candidate, os.R_OK)
        mount = mount_details(candidate)
        checks.append(check_record(
            "TQA-INPUT", "PASS" if readable else "FAIL", "Input path",
            f"{'exists and is readable' if readable else 'missing or unreadable'}; mount={mount['target']} ({mount['filesystem']})",
            "No action required." if readable else "Provide an existing readable input directory or sample sheet.",
        ))
    selected_output = output.expanduser() if output is not None else Path.cwd()
    effective_work = work.expanduser() if work is not None else (
        selected_output / ".tumorquantai-work" if output is not None else selected_output
    )
    storage = storage_preflight(
        selected_output, effective_work, 5 * 1024**3,
        create=(output is not None or work is not None) and not mount_safety_errors,
    )
    storage_ok = storage["ok"] and not mount_safety_errors
    mount_safety = (
        "; ".join(mount_safety_errors)
        if mount_safety_errors
        else "explicit mounted-path validation passed"
        if output is not None or work is not None
        else "no explicit output/work path requested"
    )
    checks.append(check_record(
        "TQA-STORAGE", "PASS" if storage_ok else "FAIL",
        "Output/work storage" if output is not None or work is not None else "Current-path storage",
        f"mount={storage['mount']['target']} ({storage['mount']['filesystem']}), free={format_bytes(storage['free_bytes'])}, same_filesystem={storage['same_filesystem']}; mount_safety={mount_safety}",
        "No action required." if storage_ok else "Choose writable output/work paths on the same verified non-root mount with at least 5 GiB free.",
    ))
    if online:
        checks.extend((
            online_check(
                "https://api.github.com/repos/cfarkas/tumorquantai/releases/tags/"
                f"{RELEASE_TAG}",
                "TQA-ONLINE-GITHUB",
                "GitHub release metadata",
            ),
            online_check(f"https://zenodo.org/api/records/{DATASET_RECORD}", "TQA-ONLINE-ZENODO", "Zenodo tutorial record"),
            online_check(f"https://huggingface.co/api/models/Owkin-Bioptimus/histoplus/revision/{MODEL_REVISION}", "TQA-ONLINE-MODEL", "Pinned HistoPLUS revision metadata"),
        ))
    return checks


def doctor_json(checks: list[dict[str, Any]]) -> dict[str, Any]:
    safe_checks: list[dict[str, Any]] = []
    for check in checks:
        safe_checks.append({key: redact_text(str(value), paths=True) for key, value in check.items()})
    fail_count = sum(item["status"] == "FAIL" for item in checks)
    warn_count = sum(item["status"] == "WARN" for item in checks)
    return {
        "schema_version": "tumorquantai_doctor_v1",
        "generated_at_utc": utc_now(),
        "software_version": VERSION,
        "summary": {"pass": len(checks) - fail_count - warn_count, "warn": warn_count, "fail": fail_count},
        "checks": safe_checks,
        "privacy": "Secrets and common personal path prefixes are redacted.",
    }


def format_doctor(checks: list[dict[str, Any]]) -> str:
    width = max((len(item["code"]) for item in checks), default=10)
    lines = [f"{'STATE':<5}  {'CHECK':<{width}}  RESULT", "-" * (width + 44)]
    for item in checks:
        lines.append(f"{item['status']:<5}  {item['code']:<{width}}  {item['item']}")
        lines.append(f"       {'':<{width}}  {item['detail']}")
        if item["status"] != "PASS":
            lines.append(f"       {'':<{width}}  Next: {item['next_action']}")
    return "\n".join(lines)


def _positive_tiff_resolution(value: Any) -> float | None:
    try:
        if isinstance(value, (tuple, list)):
            if len(value) != 2:
                return None
            numerator, denominator = float(value[0]), float(value[1])
            if denominator == 0:
                return None
            resolution = numerator / denominator
        else:
            resolution = float(value)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
    return resolution if math.isfinite(resolution) and resolution > 0 else None


def _read_tiff_metadata(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"format": "TIFF", "pyramid_levels": None, "dimensions": None, "source_mpp": None, "metadata_reader": "unavailable"}
    try:
        import tifffile  # type: ignore
    except ImportError:
        return result
    try:
        with tifffile.TiffFile(path) as slide:
            series = slide.series[0]
            levels = getattr(series, "levels", ()) or (series,)
            result["pyramid_levels"] = len(levels)
            shape = tuple(int(value) for value in series.shape)
            result["dimensions"] = "x".join(str(value) for value in shape[-3:-1] if value) if len(shape) >= 3 else "x".join(map(str, shape))
            page = slide.pages[0]
            x_tag = page.tags.get("XResolution")
            y_tag = page.tags.get("YResolution")
            unit_tag = page.tags.get("ResolutionUnit")
            resolution_tags = (x_tag, y_tag, unit_tag)
            if any(tag is not None for tag in resolution_tags):
                if not all(tag is not None for tag in resolution_tags):
                    result["metadata_reader"] = "tifffile; incomplete physical resolution metadata ignored"
                else:
                    x_pixels_per_unit = _positive_tiff_resolution(x_tag.value)
                    y_pixels_per_unit = _positive_tiff_resolution(y_tag.value)
                    try:
                        unit = int(unit_tag.value)
                    except (TypeError, ValueError, OverflowError):
                        unit = 0
                    micrometres_per_unit = {2: 25_400.0, 3: 10_000.0}.get(unit)
                    if x_pixels_per_unit is None or y_pixels_per_unit is None:
                        result["metadata_reader"] = "tifffile; invalid TIFF resolution ignored"
                    elif micrometres_per_unit is None:
                        result["metadata_reader"] = "tifffile; unsupported physical resolution unit ignored"
                    else:
                        x_mpp = micrometres_per_unit / x_pixels_per_unit
                        y_mpp = micrometres_per_unit / y_pixels_per_unit
                        if not (0.05 <= x_mpp <= 10.0 and 0.05 <= y_mpp <= 10.0):
                            result["metadata_reader"] = "tifffile; implausible generic resolution ignored"
                        elif not math.isclose(x_mpp, y_mpp, rel_tol=1e-3, abs_tol=1e-6):
                            result["metadata_reader"] = "tifffile; anisotropic TIFF resolution ignored"
                        else:
                            result["source_mpp"] = (x_mpp + y_mpp) / 2.0
            if result["metadata_reader"] == "unavailable":
                result["metadata_reader"] = "tifffile"
    except Exception as exc:
        result["metadata_reader"] = f"tifffile could not parse metadata: {type(exc).__name__}"
    return result


def _edge_digest(path: Path) -> str:
    digest = hashlib.sha256()
    size = path.stat().st_size
    with path.open("rb") as handle:
        digest.update(handle.read(64 * 1024))
        if size > 64 * 1024:
            handle.seek(max(0, size - 64 * 1024))
            digest.update(handle.read(64 * 1024))
    digest.update(str(size).encode("ascii"))
    return digest.hexdigest()[:16]


def inspect_inputs(
    input_root: Path, output: Path, *, patterns: Sequence[str] = (),
    sample_sheet: Path | None = None, source_mpp: float | None = None,
    include: str = "*", exclude: str = "", require_l2: bool = False,
) -> dict[str, Any]:
    input_root = input_root.expanduser().resolve()
    if not input_root.is_dir():
        raise TumorQuantAIError(f"Input directory does not exist: {input_root}", EXIT_INPUT)
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    discovery_tsv = output / "inspection_manifest.tsv"
    discovery_json = output / "inspection_discovery.json"
    command = [
        sys.executable, str(ROOT / "bin/discover_slides.py"), "--input-root", str(input_root),
        "--output", str(discovery_tsv), "--json", str(discovery_json), "--include", include,
        "--exclude", exclude, "--exclude-root", str(output),
        "--l2-policy", "required" if require_l2 else "optional",
    ]
    for pattern in patterns or ("*_L0_rgb.tif", "*_L0_rgb.tiff"):
        command.extend(["--pattern", pattern])
    if sample_sheet is not None:
        command.extend(["--sample-sheet", str(sample_sheet.expanduser().resolve())])
    code, discovered_output = command_output(command, timeout=300)
    if code != 0:
        message = re.sub(r"^ERROR:\s*", "", redact_text(discovered_output, paths=True))
        raise TumorQuantAIError(message, EXIT_INPUT)
    with discovery_tsv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))

    duplicate_keys: dict[tuple[str, str], list[str]] = {}
    enriched: list[dict[str, Any]] = []
    for row in rows:
        slide_path = Path(row["slide_path"])
        metadata = _read_tiff_metadata(slide_path)
        effective_mpp = source_mpp if source_mpp is not None else metadata.get("source_mpp")
        provenance = "supplied" if source_mpp is not None else ("embedded TIFF metadata" if effective_mpp else "missing")
        digest = _edge_digest(slide_path)
        duplicate_keys.setdefault((str(row["size_bytes"]), digest), []).append(row["sample_id"])
        l2_size = int(row["l2_size_bytes"]) if str(row.get("l2_size_bytes", "")).isdigit() else 0
        primary_size = int(row["size_bytes"])
        enriched.append({
            "sample_id": row["sample_id"],
            "selected_file": row["relative_path"],
            "format": metadata["format"],
            "size_bytes": primary_size,
            "pyramid_levels": metadata["pyramid_levels"],
            "dimensions": metadata["dimensions"],
            "metadata_reader": metadata["metadata_reader"],
            "l0": "primary full-resolution image",
            "l2_companion": Path(row["l2_path"]).name if row.get("l2_path") else "",
            "l2_exists": str(row.get("l2_exists", "")).lower() == "true",
            "source_mpp": round(float(effective_mpp), 9) if effective_mpp else None,
            "source_mpp_provenance": provenance,
            "physical_scale_ready": effective_mpp is not None and float(effective_mpp) > 0,
            "estimated_work_bytes": 2 * (primary_size + l2_size),
            "estimated_result_bytes": max(256 * 1024**2, (primary_size + l2_size) // 2),
            "fingerprint": row["fingerprint"],
            "edge_probe": digest,
        })
    for row in enriched:
        candidates = duplicate_keys[(str(row["size_bytes"]), row["edge_probe"])]
        row["potential_duplicate_of"] = ",".join(value for value in candidates if value != row["sample_id"])
        row.pop("edge_probe", None)

    manifest_csv = output / "inspection_manifest.csv"
    columns = list(enriched[0].keys()) if enriched else []
    if columns:
        with manifest_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(enriched)
    summary = {
        "schema_version": "tumorquantai_inspection_v1",
        "generated_at_utc": utc_now(),
        "input_name": input_root.name,
        "sample_count": len(enriched),
        "missing_l2": sum(not row["l2_exists"] for row in enriched),
        "missing_source_mpp": sum(not row["physical_scale_ready"] for row in enriched),
        "potential_duplicate_count": sum(bool(row["potential_duplicate_of"]) for row in enriched),
        "input_bytes": sum(row["size_bytes"] for row in enriched),
        "estimated_work_bytes": sum(row["estimated_work_bytes"] for row in enriched),
        "estimated_result_bytes": sum(row["estimated_result_bytes"] for row in enriched),
        "sample_ids": [row["sample_id"] for row in enriched],
        "ready_for_sampled_run": bool(enriched) and all(row["l2_exists"] and row["physical_scale_ready"] for row in enriched),
        "definitions": {
            "WSI": "whole-slide image: a very large digital microscope slide",
            "L0": "the full-resolution image level",
            "L2": "a lower-resolution companion used for tissue sampling",
            "source_mpp": "micrometres represented by one pixel in the source L0 image",
            "target_mpp": f"the model tile scale; TumorQuantAI uses {TARGET_MPP:g} MPP by default",
        },
    }
    payload = {"summary": summary, "slides": enriched}
    write_json(output / "inspection.json", payload)
    write_inspection_html(output / "INSPECTION.html", payload)
    return {**payload, "manifest_csv": str(manifest_csv), "manifest_tsv": str(discovery_tsv), "html": str(output / "INSPECTION.html")}


def write_inspection_html(path: Path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    rows = []
    for item in payload["slides"]:
        rows.append(
            "<tr>" + "".join(
                f"<td>{html.escape(str(value if value not in (None, '') else 'unknown'))}</td>"
                for value in (
                    item["sample_id"], item["selected_file"], item["format"],
                    item["pyramid_levels"], item["l2_exists"], item["source_mpp"],
                    item["source_mpp_provenance"], item["potential_duplicate_of"],
                )
            ) + "</tr>"
        )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TumorQuantAI input inspection</title><style>
body{{font:16px/1.5 system-ui,sans-serif;max-width:1100px;margin:auto;padding:1rem;color:#17202a}}
.notice{{border-left:.4rem solid #2563eb;background:#eff6ff;padding:1rem}} table{{border-collapse:collapse;width:100%;display:block;overflow:auto}}
th,td{{border:1px solid #cbd5e1;padding:.5rem;text-align:left}} th{{background:#e2e8f0}}
</style></head><body><h1>TumorQuantAI input inspection</h1>
<p class="notice">No inference was run. This report checks file structure and physical-scale readiness only.</p>
<p>Samples: {summary['sample_count']}; missing L2: {summary['missing_l2']}; missing source MPP: {summary['missing_source_mpp']}; potential duplicates: {summary['potential_duplicate_count']}.</p>
<p>Estimated workflow storage: {format_bytes(summary['estimated_work_bytes'])}; estimated results: {format_bytes(summary['estimated_result_bytes'])}. Estimates are planning aids, not guarantees.</p>
<h2>Files</h2><table><thead><tr><th>Sample</th><th>Selected file</th><th>Format</th><th>Pyramid levels</th><th>L2 exists</th><th>Source MPP</th><th>MPP source</th><th>Potential duplicate</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<h2>Plain-language scale guide</h2><dl><dt>WSI</dt><dd>{html.escape(summary['definitions']['WSI'])}</dd><dt>L0</dt><dd>{html.escape(summary['definitions']['L0'])}</dd><dt>L2</dt><dd>{html.escape(summary['definitions']['L2'])}</dd><dt>Source MPP</dt><dd>{html.escape(summary['definitions']['source_mpp'])}</dd><dt>Target MPP</dt><dd>{html.escape(summary['definitions']['target_mpp'])}</dd></dl>
</body></html>"""
    atomic_text(path, document)


def input_signature(rows: Sequence[dict[str, Any]]) -> str:
    payload = "\n".join(f"{row['sample_id']}\t{row['fingerprint']}" for row in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_run_manifest(output: Path) -> dict[str, Any]:
    path = output / RUN_MANIFEST
    if not path.is_file():
        return {}
    return read_json(path)


def write_run_manifest(output: Path, payload: dict[str, Any]) -> None:
    write_json(output / RUN_MANIFEST, payload)


def _truth(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _relative_if_inside(root: Path, value: str | Path | None) -> str | None:
    if not value:
        return None
    path = Path(str(value))
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.name


def _safe_result_artifact(output: Path, raw: str, fallback: str) -> Path | None:
    relative = Path(raw.strip()) if raw.strip() else Path(fallback)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    candidate = (output / relative).resolve()
    try:
        candidate.relative_to(output)
    except ValueError:
        return None
    return candidate


def _completed_artifacts_valid(
    output: Path, sample: str, summary_value: str = "", counts_value: str = ""
) -> tuple[bool, str]:
    if Path(sample).name != sample or sample in {"", ".", ".."}:
        return False, "unsafe sample identifier in aggregation audit"
    summary = _safe_result_artifact(
        output, summary_value, f"{sample}/summary/summary.json"
    )
    counts = _safe_result_artifact(
        output, counts_value, f"{sample}/cell_types/class_counts.csv"
    )
    if summary is None or counts is None:
        return False, "unsafe included-artifact path in aggregation audit"
    if not summary.is_file() or not counts.is_file():
        return False, "included sample is missing summary.json or class_counts.csv"
    try:
        payload = json.loads(summary.read_text(encoding="utf-8"))
        with counts.open("r", encoding="utf-8", newline="") as handle:
            fields = csv.DictReader(handle).fieldnames or []
    except (OSError, json.JSONDecodeError):
        return False, "included sample has unreadable summary.json or class_counts.csv"
    if not isinstance(payload, dict) or "count" not in fields:
        return False, "included sample has an invalid summary or count-table schema"
    return True, ""


def collect_status(output: Path, *, include_private_paths: bool = False) -> dict[str, Any]:
    output = output.expanduser().resolve()
    if not output.is_dir():
        raise TumorQuantAIError(f"Output directory does not exist: {output}", EXIT_INPUT)
    manifest = load_run_manifest(output)
    smoke_output = output / "smoke-results"
    if manifest.get("completion_status") in {
        "one_slide_smoke_complete", "inference_failed", "audit_failed"
    } and smoke_output.is_dir():
        delegated = collect_status(smoke_output, include_private_paths=include_private_paths)
        delegated["output_name"] = output.name if include_private_paths else "redacted-output"
        recorded_resume = str(manifest.get("resume_command", "not recorded"))
        delegated["resume_command"] = recorded_resume if include_private_paths else redact_text(recorded_resume, paths=True)
        if delegated.get("first_log"):
            delegated["first_log"] = f"smoke-results/{delegated['first_log']}"
        delegated["run"] = {
            key: manifest.get(key) for key in (
                "software_version", "software_commit", "preset", "sampling_percent", "seed",
                "source_mpp", "source_mpp_values", "source_mpp_provenance", "target_mpp",
                "execution_profile", "container_identity", "model_revision",
                "completion_status", "demonstration", "dataset_record", "dataset_doi",
                "dataset_release",
            ) if key in manifest
        }
        return delegated
    discovery_paths = [output / "workflow_metadata/slides.tsv", output / "inspection/inspection_manifest.tsv"]
    discovered: list[str] = []
    for discovery in discovery_paths:
        if discovery.is_file():
            with discovery.open("r", encoding="utf-8", newline="") as handle:
                discovered = [str(row.get("sample_id", "")).strip() for row in csv.DictReader(handle, delimiter="\t") if str(row.get("sample_id", "")).strip()]
            break

    audit_candidates = [
        output / "aggregated_celltypes/sample_aggregation_audit.csv",
        output / "sample_aggregation_audit.csv",
    ]
    audit = next((path for path in audit_candidates if path.is_file()), None)
    states: dict[str, str] = {}
    reasons: dict[str, str] = {}
    failure_logs: list[str] = []
    other_logs: list[str] = []
    if audit is not None:
        with audit.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                sample = str(row.get("slide_id") or row.get("sample_id") or "").strip()
                if not sample:
                    continue
                status_value = str(row.get("status", "")).strip().lower()
                included = _truth(row.get("included")) or status_value == "included"
                selected_raw = row.get("manifest_selected", row.get("selected"))
                selected = True if selected_raw in (None, "") else _truth(selected_raw)
                completed_raw = row.get("manifest_completed", row.get("completed"))
                completed = included or _truth(completed_raw)
                return_code = str(row.get("returncode", "")).strip()
                reason = str(row.get("reason", "")).strip()
                if included and completed:
                    artifacts_ok, artifact_reason = _completed_artifacts_valid(
                        output,
                        sample,
                        str(row.get("summary_json", "")),
                        str(row.get("class_counts_csv", "")),
                    )
                    state = "completed" if artifacts_ok else "incomplete"
                    if not artifacts_ok:
                        reason = artifact_reason
                elif not selected or "unselected" in status_value:
                    state = "excluded"
                elif return_code not in {"", "0", "0.0"} or "fail" in status_value or "returncode=" in reason:
                    state = "failed"
                else:
                    state = "incomplete"
                states[sample] = state
                reasons[sample] = redact_text(reason, paths=True)
                if str(row.get("log_file", "")).strip():
                    target_logs = failure_logs if state in {"failed", "incomplete"} else other_logs
                    target_logs.append(str(row["log_file"]).strip())

    trace_files = sorted(
        (output / "workflow_metadata").glob("nextflow_trace_*.tsv"),
        key=lambda path: path.stat().st_mtime_ns,
    ) if (output / "workflow_metadata").is_dir() else []
    trace_states: dict[str, tuple[str, str]] = {}
    for trace in trace_files:
        try:
            with trace.open("r", encoding="utf-8", newline="") as handle:
                trace_rows = list(csv.DictReader(handle, delimiter="\t"))
        except OSError:
            continue
        for row in trace_rows:
            name = str(row.get("name", ""))
            match = re.search(r"(?:^|:)PROCESS_SLIDE \((.*)\)$", name)
            status_value = str(row.get("status", "")).strip().upper()
            if not match:
                continue
            sample = match.group(1)
            trace_states[sample] = (status_value, str(row.get("exit", "")).strip())
    for sample, (status_value, exit_value) in trace_states.items():
        if status_value not in {"FAILED", "ABORTED"} or states.get(sample) == "completed":
            continue
        states[sample] = "failed"
        reasons[sample] = f"Nextflow PROCESS_SLIDE status={status_value}" + (
            f", exit={exit_value}" if exit_value else ""
        )

    for sample_dir in sorted(output.iterdir()):
        if not sample_dir.is_dir() or sample_dir.name in {"workflow_metadata", "aggregated_celltypes", "inspection", ".tumorquantai-work"}:
            continue
        summary_path = sample_dir / "summary/summary.json"
        counts_path = sample_dir / "cell_types/class_counts.csv"
        if sample_dir.name not in states:
            artifacts_ok, _artifact_reason = _completed_artifacts_valid(output, sample_dir.name)
            if artifacts_ok:
                states[sample_dir.name] = "completed"
    for sample in discovered:
        states.setdefault(sample, "pending")

    zero_ids: list[str] = []
    for sample, state in states.items():
        if state != "completed":
            continue
        summary_path = output / sample / "summary/summary.json"
        if not summary_path.is_file():
            continue
        try:
            slide_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(slide_summary, dict):
            continue
        counts_path = output / sample / "cell_types/class_counts.csv"
        if not counts_path.is_file():
            continue
        try:
            with counts_path.open("r", encoding="utf-8", newline="") as handle:
                count_rows = list(csv.DictReader(handle))
            observed_total = sum(int(row.get("count", "")) for row in count_rows)
        except (OSError, TypeError, ValueError):
            continue
        if (
            _truth(slide_summary.get("zero_detections"))
            and slide_summary.get("n_cells") == 0
            and observed_total == 0
        ):
            zero_ids.append(sample)

    grouped = {name: sorted(sample for sample, state in states.items() if state == name) for name in ("completed", "failed", "incomplete", "excluded", "pending")}
    if grouped["failed"] and not grouped["completed"]:
        overall = "FAIL"
    elif grouped["failed"] or grouped["incomplete"] or grouped["pending"]:
        overall = "WARN"
    elif grouped["completed"]:
        overall = "PASS"
    else:
        overall = "WARN"

    first_log: str | None = None
    for raw in failure_logs + ["workflow_metadata/nextflow.log"] + other_logs:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = output / candidate
        if candidate.is_file():
            first_log = _relative_if_inside(output, candidate)
            break
    result = {
        "schema_version": "tumorquantai_status_v1",
        "generated_at_utc": utc_now(),
        "output_name": output.name if include_private_paths else "redacted-output",
        "overall_status": overall,
        "counts": {key: len(value) for key, value in grouped.items()} | {"biological_zero": len(zero_ids)},
        "samples": grouped | {"biological_zero": sorted(zero_ids)},
        "reasons": {key: value for key, value in reasons.items() if value},
        "resume_command": (
            str(manifest.get("resume_command", "not recorded"))
            if include_private_paths
            else redact_text(str(manifest.get("resume_command", "not recorded")), paths=True)
        ),
        "first_log": first_log,
        "run": {
            key: manifest.get(key) for key in (
                "software_version", "software_commit", "preset", "sampling_percent", "seed",
                "source_mpp", "source_mpp_values", "source_mpp_provenance", "target_mpp",
                "execution_profile", "container_identity", "model_revision",
                "completion_status", "demonstration", "dataset_record", "dataset_doi",
                "dataset_release",
            ) if key in manifest
        },
        "interpretation": "A completed biological zero is a successful sample with zero detected cells. Failed, incomplete, excluded, and pending samples are never numerical zeroes.",
    }
    return result


def _source_mpp_display(run: dict[str, Any]) -> tuple[str | None, str | None]:
    raw_values = run.get("source_mpp_values")
    if isinstance(raw_values, (list, tuple)) and raw_values:
        values = list(raw_values)
    elif run.get("source_mpp") not in (None, ""):
        values = [run["source_mpp"]]
    else:
        return None, None

    rendered = ", ".join(
        f"{value:.9g}" if isinstance(value, (int, float)) and not isinstance(value, bool)
        else str(value)
        for value in values
    )
    label = (
        "Source MPP values (µm/pixel)"
        if len(values) > 1
        else "Source MPP (µm/pixel)"
    )
    return label, rendered


def format_status(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    run = summary.get("run", {})
    lines = [
        f"Run status: {summary['overall_status']}",
        f"Output: {summary['output_name']}",
        f"Completed: {counts['completed']}",
        f"Failed: {counts['failed']}",
        f"Incomplete: {counts['incomplete']}",
        f"Excluded: {counts['excluded']}",
        f"Pending: {counts['pending']}",
        f"Completed biological zeroes: {counts['biological_zero']}",
        "Failed or missing samples are not biological zeroes and are not inserted into matrices.",
    ]
    mpp_label, mpp_value = _source_mpp_display(run)
    if mpp_label and mpp_value:
        lines.append(f"{mpp_label}: {mpp_value}")
    if run.get("source_mpp_provenance") not in (None, ""):
        lines.append(f"Source MPP provenance: {run['source_mpp_provenance']}")
    for state in ("failed", "incomplete", "excluded", "pending", "biological_zero"):
        if summary["samples"][state]:
            lines.append(f"{state.replace('_', ' ').title()}: {', '.join(summary['samples'][state])}")
    lines.append(f"Resume command: {summary['resume_command']}")
    lines.append(f"First log to inspect: {summary['first_log'] or 'no workflow log was found'}")
    return "\n".join(lines)


def _link_if_file(output: Path, relative: str, label: str) -> tuple[str, str] | None:
    candidate = output / relative
    return (relative, label) if candidate.is_file() else None


def generate_report(output: Path) -> tuple[Path, dict[str, Any]]:
    output = output.expanduser().resolve()
    summary = collect_status(output)
    report_payload = dict(summary)
    links: list[tuple[str, str]] = []
    for relative, label in (
        ("aggregated_celltypes/sample_aggregation_audit.csv", "Sample aggregation audit"),
        ("aggregated_celltypes/celltype_fractions_by_sample.csv", "Cell-type fraction matrix"),
        ("aggregated_celltypes/celltype_counts_by_sample.csv", "Cell-type count matrix"),
        ("aggregated_celltypes/aggregation_summary.json", "Aggregation summary"),
        ("workflow_metadata/slides.tsv", "Discovered-slide manifest"),
        ("workflow_metadata/nextflow.log", "Nextflow log"),
        ("inspection/INSPECTION.html", "Input inspection"),
        ("inspection/inspection_manifest.csv", "Inspection manifest"),
        ("converted/mds_conversion_manifest.json", "MDS conversion manifest"),
        ("smoke-results/START_HERE.html", "One-slide inference report"),
        ("smoke-results/aggregated_celltypes/sample_aggregation_audit.csv", "One-slide sample aggregation audit"),
        ("smoke-results/aggregated_celltypes/celltype_fractions_by_sample.csv", "One-slide cell-type fraction matrix"),
        ("smoke-results/aggregated_celltypes/celltype_counts_by_sample.csv", "One-slide cell-type count matrix"),
        ("smoke-results/aggregated_celltypes/aggregation_summary.json", "One-slide aggregation summary"),
    ):
        linked = _link_if_file(output, relative, label)
        if linked:
            links.append(linked)
    sample_prefix = "smoke-results/" if (output / "smoke-results").is_dir() else ""
    for sample in summary["samples"]["completed"]:
        linked = _link_if_file(output, f"{sample_prefix}{sample}/summary/summary.json", f"{sample}: per-slide summary")
        if linked:
            links.append(linked)
        for overlay in OVERLAY_FILES:
            linked = _link_if_file(output, f"{sample_prefix}{sample}/{overlay}", f"{sample}: {Path(overlay).name}")
            if linked:
                links.append(linked)
    report_payload["links"] = [{"path": path, "label": label} for path, label in links]
    write_json(output / REPORT_JSON, report_payload)

    run = summary.get("run", {})
    cards = []
    for label, key in (("Completed", "completed"), ("Failed", "failed"), ("Incomplete", "incomplete"), ("Excluded", "excluded"), ("Pending", "pending"), ("Biological zero", "biological_zero")):
        value = summary["counts"][key]
        if key == "failed":
            state = "FAIL" if value else "PASS"
        elif key in {"incomplete", "excluded", "pending"}:
            state = "WARN" if value else "PASS"
        elif key == "completed":
            state = "PASS" if value else "WARN"
        else:
            state = "PASS"
        cards.append(
            f'<section class="card {state.lower()}" aria-label="{html.escape(label)} status {state}">'
            f'<h2>{html.escape(label)}</h2><p class="count">{value}</p>'
            f'<p class="state">{state}</p></section>'
        )
    identity_values = [
        ("Software version", run.get("software_version")),
        ("Software commit", run.get("software_commit")),
        ("Container", run.get("container_identity")),
        ("Model revision", run.get("model_revision")),
    ]
    mpp_label, mpp_value = _source_mpp_display(run)
    identity_values.extend([
        (mpp_label, mpp_value),
        ("Source MPP provenance", run.get("source_mpp_provenance")),
        ("Target MPP", run.get("target_mpp")),
        ("Sampling (%)", run.get("sampling_percent")),
        ("Random seed", run.get("seed")),
        ("Dataset record", run.get("dataset_record")),
        ("Dataset DOI", run.get("dataset_doi")),
        ("Completion state", run.get("completion_status")),
    ])
    identity_rows = [
        f"<tr><th>{html.escape(str(label))}</th><td>{html.escape(str(value))}</td></tr>"
        for label, value in identity_values
        if label and value not in (None, "")
    ]
    link_items = "".join(f'<li><a href="{html.escape(path, quote=True)}">{html.escape(label)}</a></li>' for path, label in links)
    demo_banner = "<p class=\"demo\">STRUCTURAL SOFTWARE DEMO — no HistoPLUS inference, biological prediction, or validation data.</p>" if run.get("demonstration") else ""
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TumorQuantAI START HERE</title><style>
:root{{--ink:#17202a;--muted:#475569;--pass:#166534;--warn:#92400e;--fail:#991b1b;--line:#cbd5e1}}
body{{font:16px/1.55 system-ui,sans-serif;max-width:1100px;margin:auto;padding:1rem;color:var(--ink)}}
.banner,.demo{{padding:1rem;border-left:.45rem solid #7c3aed;background:#f5f3ff}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:.75rem}}
.card{{border:1px solid var(--line);border-top:.4rem solid var(--warn);padding:.75rem;border-radius:.35rem}} .card.pass{{border-top-color:var(--pass)}} .card.fail{{border-top-color:var(--fail)}}
.card .count{{font-size:1.8rem;margin:.2rem 0}} .card .state{{font-weight:700;margin:.2rem 0}} table{{border-collapse:collapse;width:100%}} th,td{{border:1px solid var(--line);padding:.5rem;text-align:left;overflow-wrap:anywhere}}
a{{color:#075985}} code{{overflow-wrap:anywhere}} @media(max-width:600px){{body{{font-size:15px}}}}
</style></head><body><h1>TumorQuantAI: start here</h1>
<p class="banner"><strong>Research use only.</strong> These outputs are not a diagnosis and are not clinically validated.</p>{demo_banner}
<p>Run state: <strong>{html.escape(summary['overall_status'])}</strong>. Failed, incomplete, excluded, and pending samples are never represented as biological zeroes.</p>
<div class="grid">{''.join(cards)}</div><h2>Run identity and provenance</h2><table>{''.join(identity_rows) or '<tr><td>Run provenance is not available yet.</td></tr>'}</table>
<h2>Open these outputs</h2><ul>{link_items or '<li>No linked result files exist yet.</li>'}</ul>
<h2>Resume and support</h2><p>Resume command: <code>{html.escape(summary['resume_command'])}</code></p><p>First log to inspect: <code>{html.escape(summary['first_log'] or 'no workflow log was found')}</code></p>
<p>See the <a href="https://cfarkas.github.io/tumorquantai/troubleshooting/">troubleshooting guide</a>. Share only redacted doctor/status JSON; never share tokens, model weights, raw slides, PHI, or patient-level tables.</p>
<h2>Interpretation guardrail</h2><p>{html.escape(summary['interpretation'])} Sampled-tile counts describe sampled tiles only; they are not whole-slide counts and are not multiplied by 100 divided by the sampling percentage.</p>
</body></html>"""
    atomic_text(output / START_HERE, document)
    text_summary = format_status(summary) + f"\nMachine-readable summary: {REPORT_JSON}\n"
    atomic_text(output / RUN_SUMMARY, text_summary)
    return output / START_HERE, report_payload


def _write_demo_matrices(output: Path, samples: Sequence[str], counts: dict[str, dict[tuple[int, str], int]]) -> None:
    classes = sorted({item for sample_counts in counts.values() for item in sample_counts})
    aggregate = output / "aggregated_celltypes"
    aggregate.mkdir(parents=True, exist_ok=True)
    with (aggregate / "celltype_counts_by_sample.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["class_id", "cell_type", *samples])
        for class_id, class_name in classes:
            writer.writerow([class_id, class_name, *(counts[sample].get((class_id, class_name), 0) for sample in samples)])
    with (aggregate / "celltype_fractions_by_sample.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["class_id", "cell_type", *samples])
        totals = {sample: sum(counts[sample].values()) for sample in samples}
        for class_id, class_name in classes:
            writer.writerow([class_id, class_name, *(f"{counts[sample].get((class_id, class_name), 0) / totals[sample]:.6g}" if totals[sample] else "0" for sample in samples)])


def make_demo(output: Path) -> dict[str, Any]:
    output = output.expanduser().resolve()
    existing = load_run_manifest(output) if output.is_dir() else {}
    if output.exists() and any(output.iterdir()) and not existing.get("demonstration"):
        raise TumorQuantAIError(f"Refusing to mix a demo with existing files in {output}", EXIT_PREFLIGHT)
    output.mkdir(parents=True, exist_ok=True)
    metadata = output / "workflow_metadata"
    logs = metadata / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tumorquantai-demo-") as temporary:
        fixture_root = Path(temporary) / "input"
        for target_name, source_name in (("case_complete", "case_a"), ("case_zero", "case_a"), ("case_fail", "case_fail")):
            target = fixture_root / target_name
            target.mkdir(parents=True)
            for level in ("L0", "L2"):
                shutil.copyfile(ROOT / f"tests/fixtures/{source_name}/1_{level}_rgb.tif", target / f"1_{level}_rgb.tif")
        discover_command = [
            sys.executable, str(ROOT / "bin/discover_slides.py"), "--input-root", str(fixture_root),
            "--output", str(metadata / "slides.tsv"), "--json", str(metadata / "slides.json"),
            "--l2-policy", "required",
        ]
        code, text = command_output(discover_command, timeout=60)
        if code != 0:
            raise TumorQuantAIError(f"Structural demo discovery failed: {text}", EXIT_WORKFLOW)
        with (metadata / "slides.tsv").open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        roster: list[dict[str, Any]] = []
        completed_counts: dict[str, dict[tuple[int, str], int]] = {}
        for row in rows:
            sample = row["sample_id"]
            sample_output = output / sample
            worker_command = [
                sys.executable, str(ROOT / "tests/fixtures/stub_worker.py"),
                "--input-slide", row["slide_path"], "--output", str(sample_output),
                "--slide-id", sample, "--percent-slide", "1", "--patch-random-seed", str(DEFAULT_SEED),
            ]
            completed = subprocess.run(worker_command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
            atomic_text(logs / f"{sample}.log", redact_text(completed.stdout, paths=True) + "\n")
            if completed.returncode == 0:
                zero = "case_zero" in sample
                count_text = "class_id,class_name,count\n" if zero else "class_id,class_name,count\n1,STRUCTURAL_DEMO_CLASS_A,7\n2,STRUCTURAL_DEMO_CLASS_B,3\n"
                atomic_text(sample_output / "cell_types/class_counts.csv", count_text)
                summary = read_json(sample_output / "summary/summary.json")
                summary.update({
                    "n_cells": 0 if zero else 10, "zero_detections": zero,
                    "demonstration": True, "inference_engine": "stub",
                    "biological_result": False, "source_mpp_provenance": "synthetic fixture",
                })
                write_json(sample_output / "summary/summary.json", summary)
                completed_counts[sample] = {} if zero else {(1, "STRUCTURAL_DEMO_CLASS_A"): 7, (2, "STRUCTURAL_DEMO_CLASS_B"): 3}
            roster.append({
                "slide_id": sample, "raw_dir": "", "output_dir": sample,
                "expected_l0": Path(row["relative_path"]).as_posix(), "expected_l0_exists": True,
                "expected_l2_exists": True, "completed": completed.returncode == 0,
                "selected": True, "returncode": completed.returncode, "elapsed_sec": "",
                "log_file": f"workflow_metadata/logs/{sample}.log",
            })

        portable_rows: list[dict[str, Any]] = []
        for row in rows:
            portable = dict(row)
            source = Path(row["slide_path"])
            portable["slide_path"] = f"synthetic_fixture/{row['relative_path']}"
            portable["l2_path"] = (
                f"synthetic_fixture/{Path(row['relative_path']).with_name(Path(row['relative_path']).name.replace('_L0_', '_L2_')).as_posix()}"
                if row.get("l2_path") else ""
            )
            for key in ("mtime_ns", "ctime_ns", "device", "inode", "l2_mtime_ns"):
                portable[key] = ""
            portable["fingerprint"] = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
            portable_rows.append(portable)
        with (metadata / "slides.tsv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(portable_rows[0]), delimiter="\t", lineterminator="\n")
            writer.writeheader(); writer.writerows(portable_rows)
        write_json(metadata / "slides.json", {"slides": portable_rows})

    manifest_path = output / "workflow_aggregation_manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(roster[0]))
        writer.writeheader(); writer.writerows(roster)
    audit_rows: list[dict[str, Any]] = []
    for row in roster:
        included = bool(row["completed"] and int(row["returncode"]) == 0)
        sample = row["slide_id"]
        audit_rows.append({
            "slide_id": sample, "sample_id": sample, "included": included,
            "status": "included" if included else "excluded_incomplete",
            "reason": "" if included else "intentional stub-worker failure for audit demonstration",
            "manifest_completed": row["completed"], "manifest_selected": True,
            "returncode": row["returncode"], "total_cells": sum(completed_counts.get(sample, {}).values()) if included else "",
            "n_detected_cell_types": len(completed_counts.get(sample, {})) if included else "",
            "percent_slide": 1 if included else "", "random_seed": DEFAULT_SEED if included else "",
            "n_tiles_total": 10 if included else "", "n_tiles_sampled": 1 if included else "",
            "class_counts_csv": f"{sample}/cell_types/class_counts.csv" if included else "",
            "summary_json": f"{sample}/summary/summary.json" if included else "",
            "log_file": row["log_file"],
        })
    aggregate = output / "aggregated_celltypes"
    aggregate.mkdir(exist_ok=True)
    with (aggregate / "sample_aggregation_audit.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(audit_rows[0]))
        writer.writeheader(); writer.writerows(audit_rows)
    included_samples = sorted(completed_counts)
    _write_demo_matrices(output, included_samples, completed_counts)
    write_json(aggregate / "aggregation_summary.json", {
        "schema_version": "histoplus_celltype_aggregation_v1",
        "demonstration": True, "inference_engine": "stub", "biological_result": False,
        "n_included_slides": len(included_samples), "n_excluded_slides": len(roster) - len(included_samples),
        "counts_are": "structural fixture values only; they have no biological meaning",
        "percent_slide_values": [1.0], "random_seed_values": [DEFAULT_SEED],
    })
    run_manifest = {
        "schema_version": "tumorquantai_run_v1", "software_version": VERSION,
        "software_commit": git_commit(), "created_at_utc": utc_now(), "completed_at_utc": utc_now(),
        "completion_status": "complete_with_intentional_fixture_failure", "preset": "structural-demo",
        "sampling_percent": 1.0, "seed": DEFAULT_SEED, "source_mpp": "synthetic",
        "target_mpp": TARGET_MPP, "execution_profile": "stub", "container_identity": "not used",
        "model_revision": "not used", "demonstration": True, "biological_result": False,
        "resume_command": "./tumorquantai demo --output " + shlex.quote(output.name),
    }
    write_run_manifest(output, run_manifest)
    atomic_text(output / "DEMO_README.txt", "STRUCTURAL SOFTWARE DEMO\nNo HistoPLUS inference ran. Values have no biological meaning.\n")
    report, status_payload = generate_report(output)
    return {"report": str(report), "status": status_payload, "manifest": run_manifest}


def verify_tutorial_download(download_root: Path) -> dict[str, Any]:
    manifest = download_root / "tumorquantai_lymphoma_mds_manifest.csv"
    if not manifest.is_file():
        raise TumorQuantAIError("Authoritative downloaded manifest is missing", EXIT_DATA)
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    matching = [row for row in rows if row.get("alias") == TUTORIAL_SAMPLE]
    if len(matching) != 1:
        raise TumorQuantAIError("Authoritative manifest does not contain exactly one sample-022 row", EXIT_DATA)
    row = matching[0]
    expected = {
        "zenodo_filename": TUTORIAL_FILE, "size_bytes": str(TUTORIAL_SIZE),
        "md5": TUTORIAL_MD5, "sha256": TUTORIAL_SHA256,
    }
    for key, value in expected.items():
        if str(row.get(key, "")).strip().lower() != value.lower():
            raise TumorQuantAIError(f"Manifest identity mismatch for {key}", EXIT_DATA)
    try:
        observed_mpp = float(row.get("source_mpp", ""))
    except ValueError as exc:
        raise TumorQuantAIError("Manifest source_mpp is invalid", EXIT_DATA) from exc
    if abs(observed_mpp - TUTORIAL_SOURCE_MPP) > 1e-9:
        raise TumorQuantAIError("Manifest source_mpp differs from the verified tutorial value", EXIT_DATA)
    source = download_root / f"raw/{TUTORIAL_SAMPLE}/1.mds"
    if not source.is_file() or source.stat().st_size != TUTORIAL_SIZE:
        raise TumorQuantAIError("Downloaded sample-022 file is missing or has the wrong size", EXIT_DATA)
    sha256 = hashlib.sha256(); md5 = hashlib.md5(usedforsecurity=False)
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            sha256.update(chunk); md5.update(chunk)
    if sha256.hexdigest() != TUTORIAL_SHA256 or md5.hexdigest() != TUTORIAL_MD5:
        raise TumorQuantAIError("Downloaded sample-022 checksum verification failed", EXIT_DATA)
    return {
        "file": f"raw/{TUTORIAL_SAMPLE}/1.mds", "size_bytes": TUTORIAL_SIZE,
        "sha256": TUTORIAL_SHA256, "md5": TUTORIAL_MD5,
        "source_mpp": TUTORIAL_SOURCE_MPP, "manifest": manifest.name,
    }


def validate_single_sample_audit(output: Path) -> None:
    audit = output / "aggregated_celltypes/sample_aggregation_audit.csv"
    if not audit.is_file():
        raise TumorQuantAIError("One-slide smoke run did not produce its aggregation audit", EXIT_WORKFLOW)
    with audit.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    included = [row for row in rows if _truth(row.get("included")) or row.get("status") == "included"]
    excluded = [row for row in rows if row not in included]
    included_sample = str(
        (included[0].get("slide_id") or included[0].get("sample_id") or "")
        if included else ""
    ).strip()
    if (
        len(rows) != 1 or len(included) != 1 or excluded
        or included_sample != TUTORIAL_SAMPLE
    ):
        raise TumorQuantAIError(f"Expected exactly one included sample and zero excluded samples; observed included={len(included)}, excluded={len(excluded)}", EXIT_WORKFLOW)


__all__ = [name for name in globals() if name.isupper()] + [
    "TumorQuantAIError", "atomic_text", "write_json", "read_json", "format_bytes",
    "command_output", "git_commit", "redact_text", "shell_join", "storage_preflight",
    "df_details", "validate_large_data_root",
    "associated_cache_directory",
    "resolve_token_file", "model_access", "doctor_checks", "doctor_json", "format_doctor",
    "inspect_inputs", "input_signature", "load_run_manifest", "write_run_manifest",
    "collect_status", "format_status", "generate_report", "make_demo",
    "verify_tutorial_download", "validate_single_sample_audit", "utc_now",
]
