#!/usr/bin/env python3
"""Apply the first-class runtime portability layer for the TumorQuantAI overhaul."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise SystemExit(f"Missing expected text in {path}: {old[:160]!r}")
    write(path, text.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str, flags: int = 0) -> None:
    text = read(path)
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"Expected one regex replacement in {path}, found {count}: {pattern}")
    write(path, updated)


# ---------------------------------------------------------------------------
# Nextflow runtime profiles
# ---------------------------------------------------------------------------
config = read("nextflow.config")
marker = "process {\n"
if marker not in config:
    raise SystemExit("Unable to locate the Nextflow runtime section")
prefix = config.split(marker, 1)[0]
runtime_config = r'''process {
    executor = 'local'
    shell = ['/bin/bash', '-Eeuo', 'pipefail']
}

docker {
    enabled = false
    runOptions = "--shm-size=${params.docker_shm_size} ${params.docker_run_options ?: ''}".trim()
}

singularity {
    enabled = false
    autoMounts = true
}

apptainer {
    enabled = false
    autoMounts = true
}

conda {
    enabled = false
}

profiles {
    local {
        process {
            withName: 'DISCOVER_SLIDES|PROCESS_SLIDE|AGGREGATE_COUNTS' {
                container = null
                conda = null
            }
        }
        params.device = 'cpu'
        params.histoplus_cache_dir = "${System.getenv('HOME')}/.cache/tumorquantai/histoplus"
    }

    docker_cpu {
        docker.enabled = true
        process {
            withName: 'DISCOVER_SLIDES|PROCESS_SLIDE|AGGREGATE_COUNTS' {
                container = params.container_image
                conda = null
            }
        }
        params.device = 'cpu'
    }

    docker_gpu {
        docker.enabled = true
        process {
            withName: 'DISCOVER_SLIDES|PROCESS_SLIDE|AGGREGATE_COUNTS' {
                container = params.container_image
                conda = null
            }
        }
        params.device = 'cuda'
        docker.runOptions = "--gpus all --shm-size=${params.docker_shm_size} ${params.docker_run_options ?: ''}".trim()
    }

    singularity_cpu {
        singularity.enabled = true
        process {
            withName: 'DISCOVER_SLIDES|PROCESS_SLIDE|AGGREGATE_COUNTS' {
                container = params.container_image
                conda = null
            }
        }
        params.device = 'cpu'
    }

    singularity_gpu {
        singularity.enabled = true
        singularity.runOptions = '--nv'
        process {
            withName: 'DISCOVER_SLIDES|PROCESS_SLIDE|AGGREGATE_COUNTS' {
                container = params.container_image
                conda = null
            }
        }
        params.device = 'cuda'
    }

    apptainer_cpu {
        apptainer.enabled = true
        process {
            withName: 'DISCOVER_SLIDES|PROCESS_SLIDE|AGGREGATE_COUNTS' {
                container = params.container_image
                conda = null
            }
        }
        params.device = 'cpu'
    }

    apptainer_gpu {
        apptainer.enabled = true
        apptainer.runOptions = '--nv'
        process {
            withName: 'DISCOVER_SLIDES|PROCESS_SLIDE|AGGREGATE_COUNTS' {
                container = params.container_image
                conda = null
            }
        }
        params.device = 'cuda'
    }

    conda_cpu {
        conda.enabled = true
        process {
            withName: 'DISCOVER_SLIDES|PROCESS_SLIDE|AGGREGATE_COUNTS' {
                container = null
                conda = "${projectDir}/environment.yml"
            }
        }
        params.device = 'cpu'
        params.histoplus_cache_dir = "${System.getenv('HOME')}/.cache/tumorquantai/histoplus"
    }
}

report.overwrite = true
trace.overwrite = true
timeline.overwrite = true
dag.overwrite = true
'''
write("nextflow.config", prefix + runtime_config)

write(
    "environment.yml",
    """name: tumorquantai
channels:
  - pytorch
  - conda-forge
dependencies:
  - python=3.11
  - pip>=24
  - pytorch=2.6.0
  - torchvision=0.21.0
  - torchaudio=2.6.0
  - cpuonly
  - openslide
  - openslide-python>=1.4,<2
  - libvips
  - pyvips>=3,<4
  - numpy>=1.26,<3
  - pandas>=2.2,<3
  - scipy>=1.15,<2
  - scikit-learn>=1.6,<2
  - matplotlib>=3.8,<4
  - pillow>=10,<13
  - tifffile>=2024.12,<2027
  - imagecodecs>=2024.12,<2027
  - olefile>=0.47,<1
  - opencv>=4.10,<5
  - pyyaml>=6,<7
  - openpyxl>=3.1,<4
  - tqdm>=4.67,<5
  - python-pptx>=1,<2
  - pymupdf>=1.25,<2
  - umap-learn>=0.5.7,<0.6
  - seaborn>=0.13,<0.14
  - requests>=2.32,<3
  - huggingface_hub>=1.1.5,<2
  - pip:
      - lazyslide==0.10.1
      - git+https://github.com/rendeirolab/lazyslide-models.git@0127beb5ff7989005f0eff7b481a95b989c4187f
""",
)

# ---------------------------------------------------------------------------
# Poetry launcher
# ---------------------------------------------------------------------------
write(
    "pyproject.toml",
    """[tool.poetry]
name = "tumorquantai-launcher"
version = "0.5.0"
description = "Poetry-managed launcher for the TumorQuantAI Nextflow workflow"
authors = ["Carlos Farkas"]
readme = "README.md"
packages = [{ include = "tumorquantai_cli" }]

[tool.poetry.dependencies]
python = ">=3.11,<3.13"
PyYAML = ">=6,<7"
requests = ">=2.32,<3"
numpy = ">=1.26,<3"
olefile = ">=0.47,<1"
Pillow = ">=10,<13"
tifffile = ">=2024.12,<2027"
imagecodecs = ">=2024.12,<2027"

[tool.poetry.group.dev.dependencies]
pytest = ">=8,<9"

[tool.poetry.scripts]
tumorquantai = "tumorquantai_cli.cli:main"

[build-system]
requires = ["poetry-core>=2.0.0,<3.0.0"]
build-backend = "poetry.core.masonry.api"
""",
)
write(
    "tumorquantai_cli/__init__.py",
    '"""Poetry entry point for the repository TumorQuantAI launcher."""\n',
)
write(
    "tumorquantai_cli/cli.py",
    '''"""Execute the repository CLI from a Poetry-managed environment."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def repository_root() -> Path:
    configured = os.environ.get("TUMORQUANTAI_REPO")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def main() -> int:
    script = repository_root() / "tumorquantai"
    if not script.is_file():
        print(
            "ERROR: TumorQuantAI repository launcher was not found. "
            "Run Poetry from the cloned tumorquantai directory or set TUMORQUANTAI_REPO.",
            file=sys.stderr,
        )
        return 2
    return subprocess.call([sys.executable, str(script), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
''',
)

# ---------------------------------------------------------------------------
# run.sh backend selection
# ---------------------------------------------------------------------------
replace_once(
    "run.sh",
    'PROFILE="auto"\nCONTAINER_IMAGE=',
    'PROFILE="auto"\nBACKEND="${TUMORQUANTAI_BACKEND:-docker}"\nCONTAINER_IMAGE=',
)
replace_once(
    "run.sh",
    "  --profile auto|gpu|cpu|local    Execution profile (default: auto)\n",
    "  --backend docker|singularity|conda|local\n"
    "                                  Software execution backend (default: docker)\n"
    "  --docker                       Alias for --backend docker\n"
    "  --singularity                  Alias for --backend singularity or Apptainer\n"
    "  --conda                        Alias for --backend conda\n"
    "  --profile auto|gpu|cpu|local    Compute profile (default: auto; local remains compatible)\n",
)
replace_once(
    "run.sh",
    "  ./run.sh --input-dir /data/exported --profile cpu --percent-slide 1\n",
    "  ./run.sh --input-dir /data/exported --docker --profile cpu --percent-slide 1\n"
    "  ./run.sh --input-dir /data/exported --singularity --profile cpu --percent-slide 1\n"
    "  ./run.sh --input-dir /data/exported --conda --profile cpu --percent-slide 1\n",
)
replace_once(
    "run.sh",
    '    --profile) need_value "$@"; PROFILE="$2"; shift 2 ;;\n',
    '    --backend) need_value "$@"; BACKEND="$2"; shift 2 ;;\n'
    '    --docker) BACKEND="docker"; shift ;;\n'
    '    --singularity|--apptainer) BACKEND="singularity"; shift ;;\n'
    '    --conda) BACKEND="conda"; shift ;;\n'
    '    --local) BACKEND="local"; shift ;;\n'
    '    --profile) need_value "$@"; PROFILE="$2"; shift 2 ;;\n',
)
replace_once(
    "run.sh",
    '[[ "${HISTOPLUS_REVISION}" =~ ^[0-9a-fA-F]{40}$ ]] || \\\n  die "--histoplus-revision must be an immutable full 40-hex commit SHA"\n\ncommand -v nextflow >/dev/null 2>&1 || die "Nextflow is not installed (see docs/INSTALL.md)"\nif [[ "${PROFILE}" != "local" ]]; then\n  command -v docker >/dev/null 2>&1 || die "Docker is not installed; use --profile local with a prepared environment"\n  docker info >/dev/null 2>&1 || die "Docker daemon is not accessible"\nfi\n\nif [[ "${DOCTOR_ONLY}" == "true" ]]; then\n  printf \'nextflow: %s\\n\' "$(nextflow -version 2>&1 | awk \'/version/ { print; exit }\')"\n  command -v docker >/dev/null 2>&1 && printf \'docker:   %s\\n\' "$(docker --version)"\n  command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true\n  printf \'doctor: OK\\n\'\n  exit 0\nfi\n',
    '[[ "${HISTOPLUS_REVISION}" =~ ^[0-9a-fA-F]{40}$ ]] || \\\n  die "--histoplus-revision must be an immutable full 40-hex commit SHA"\n\ncase "${BACKEND}" in\n  docker|singularity|conda|local) ;;\n  *) die "--backend must be docker, singularity, conda, or local" ;;\nesac\n\n# Backward compatibility: --profile local selects the local backend.\nif [[ "${PROFILE}" == "local" ]]; then\n  BACKEND="local"\nfi\n\ncommand -v nextflow >/dev/null 2>&1 || die "Nextflow is not installed (see docs/installation.md)"\ncase "${BACKEND}" in\n  docker)\n    command -v docker >/dev/null 2>&1 || die "Docker is not installed"\n    docker info >/dev/null 2>&1 || die "Docker daemon is not accessible"\n    ;;\n  singularity)\n    command -v apptainer >/dev/null 2>&1 || command -v singularity >/dev/null 2>&1 || \\\n      die "Install Apptainer or Singularity before using --singularity"\n    ;;\n  conda)\n    command -v conda >/dev/null 2>&1 || die "Conda is not installed; install Miniforge before using --conda"\n    ;;\n  local) ;;\nesac\n\nif [[ "${DOCTOR_ONLY}" == "true" ]]; then\n  printf \'nextflow:    %s\\n\' "$(nextflow -version 2>&1 | awk \'/version/ { print; exit }\')"\n  printf \'backend:     %s\\n\' "${BACKEND}"\n  command -v docker >/dev/null 2>&1 && printf \'docker:      %s\\n\' "$(docker --version)"\n  command -v apptainer >/dev/null 2>&1 && printf \'apptainer:   %s\\n\' "$(apptainer --version)"\n  command -v singularity >/dev/null 2>&1 && printf \'singularity: %s\\n\' "$(singularity --version)"\n  command -v conda >/dev/null 2>&1 && printf \'conda:       %s\\n\' "$(conda --version)"\n  command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true\n  printf \'doctor: OK\\n\'\n  exit 0\nfi\n',
)
regex_once(
    "run.sh",
    r'''case "\$\{PROFILE\}" in\n.*?\nesac\n\nif \[\[ -z "\$\{CONTAINER_IMAGE\}" \]\]; then\n.*?\nfi\n''',
    r'''case "${PROFILE}" in
  local) PROFILE="cpu" ;;
  auto|cpu|gpu|docker_cpu|docker_gpu) ;;
  *) die "Unsupported profile: ${PROFILE}" ;;
esac

if [[ "${PROFILE}" == "auto" ]]; then
  case "${BACKEND}" in
    docker)
      DOCKER_RUNTIMES="$(docker info --format '{{json .Runtimes}}' 2>/dev/null || true)"
      if command -v nvidia-smi >/dev/null 2>&1 \
        && nvidia-smi >/dev/null 2>&1 \
        && [[ "${DOCKER_RUNTIMES,,}" == *nvidia* ]]; then
        PROFILE="gpu"
      else
        PROFILE="cpu"
      fi
      ;;
    singularity)
      if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
        PROFILE="gpu"
      else
        PROFILE="cpu"
      fi
      ;;
    conda|local) PROFILE="cpu" ;;
  esac
fi

case "${PROFILE}" in
  docker_cpu) PROFILE="cpu" ;;
  docker_gpu) PROFILE="gpu" ;;
esac

case "${BACKEND}" in
  docker)
    NF_PROFILE="docker_${PROFILE}"
    ;;
  singularity)
    if command -v apptainer >/dev/null 2>&1; then
      NF_PROFILE="apptainer_${PROFILE}"
    else
      NF_PROFILE="singularity_${PROFILE}"
    fi
    ;;
  conda)
    [[ "${PROFILE}" != "gpu" ]] || die "The versioned Conda environment is CPU-only; use Docker or Singularity for GPU execution"
    NF_PROFILE="conda_cpu"
    PROFILE="cpu"
    ;;
  local)
    [[ "${PROFILE}" != "gpu" ]] || die "The local backend cannot configure a GPU automatically"
    NF_PROFILE="local"
    PROFILE="cpu"
    ;;
esac

DEVICE="cpu"
[[ "${PROFILE}" == "gpu" ]] && DEVICE="cuda"

if [[ -z "${CONTAINER_IMAGE}" && ( "${BACKEND}" == "docker" || "${BACKEND}" == "singularity" ) ]]; then
  if [[ "${PROFILE}" == "gpu" ]]; then
    CONTAINER_IMAGE="carlosfarkas/lazyslide-histoplus@sha256:c4b02485d4549a56348cd09995ce0788a6acc8a3e1e600e986b644231a95bd25"
  else
    CONTAINER_IMAGE="carlosfarkas/lazyslide-histoplus@sha256:413bed6b55bc86923321c61453c18ece678da3c125ae44dcbd5f6c3bce7115d4"
  fi
fi
''',
    flags=re.DOTALL,
)
replace_once(
    "run.sh",
    'if [[ "${NF_PROFILE}" != "local" ]]; then\n',
    'if [[ "${BACKEND}" == "docker" ]]; then\n',
)
replace_once(
    "run.sh",
    'fi\n\nNF_ARGS=(\n',
    '''fi

if [[ "${BACKEND}" == "singularity" ]]; then
  export NXF_SINGULARITY_CACHEDIR="${NXF_SINGULARITY_CACHEDIR:-${WORK_DIR}/singularity-cache}"
  export NXF_APPTAINER_CACHEDIR="${NXF_APPTAINER_CACHEDIR:-${WORK_DIR}/apptainer-cache}"
  mkdir -p "${NXF_SINGULARITY_CACHEDIR}" "${NXF_APPTAINER_CACHEDIR}"
  export APPTAINERENV_HF_HOME="${HF_CACHE}"
  export APPTAINERENV_HUGGINGFACE_HUB_CACHE="${HF_CACHE}/hub"
  export APPTAINERENV_HISTOPLUS_CACHE="${HISTOPLUS_CACHE}"
  export SINGULARITYENV_HF_HOME="${HF_CACHE}"
  export SINGULARITYENV_HUGGINGFACE_HUB_CACHE="${HF_CACHE}/hub"
  export SINGULARITYENV_HISTOPLUS_CACHE="${HISTOPLUS_CACHE}"
  if [[ -n "${HF_TOKEN:-}" ]]; then
    export APPTAINERENV_HF_TOKEN="${HF_TOKEN}"
    export SINGULARITYENV_HF_TOKEN="${HF_TOKEN}"
  fi
fi

NF_ARGS=(
''',
)
replace_once(
    "run.sh",
    "printf 'profile:    %s\\n' \"${NF_PROFILE}\"\n",
    "printf 'backend:    %s\\n' \"${BACKEND}\"\nprintf 'profile:    %s\\n' \"${NF_PROFILE}\"\n",
)

# ---------------------------------------------------------------------------
# Python CLI backend aliases and provenance
# ---------------------------------------------------------------------------
replace_once(
    "tumorquantai",
    '    "profile": ("--profile", "--cpu", "--gpu"),\n',
    '    "profile": ("--profile", "--cpu", "--gpu"),\n'
    '    "backend": ("--backend", "--docker", "--singularity", "--conda"),\n',
)
replace_once(
    "tumorquantai",
    '    "profile": "auto",\n',
    '    "profile": "auto",\n    "backend": "docker",\n',
)
replace_once(
    "tumorquantai",
    '    if name == "profile" and value not in {"auto", "gpu", "cpu", "local"}:\n        raise _parameter_error("Parameter \'profile\' must be auto, gpu, cpu, or local.")\n',
    '    if name == "profile" and value not in {"auto", "gpu", "cpu", "local"}:\n        raise _parameter_error("Parameter \'profile\' must be auto, gpu, cpu, or local.")\n'
    '    if name == "backend" and value not in {"docker", "singularity", "conda", "local"}:\n'
    '        raise _parameter_error("Parameter \'backend\' must be docker, singularity, conda, or local.")\n',
)
replace_once(
    "tumorquantai",
    'def build_parser() -> argparse.ArgumentParser:\n',
    '''def add_execution_backend_options(command: argparse.ArgumentParser) -> None:
    """Add mutually exclusive software-runtime aliases."""
    backend = command.add_mutually_exclusive_group()
    backend.add_argument(
        "--backend", choices=("docker", "singularity", "conda", "local"),
        help="software backend (default: docker)",
    )
    backend.add_argument(
        "--docker", dest="backend", action="store_const", const="docker",
        help="run scientific tasks with Docker",
    )
    backend.add_argument(
        "--singularity", "--apptainer", dest="backend", action="store_const",
        const="singularity", help="run scientific tasks with Singularity or Apptainer",
    )
    backend.add_argument(
        "--conda", dest="backend", action="store_const", const="conda",
        help="let Nextflow create and reuse the versioned Conda environment",
    )
    command.set_defaults(backend="docker")


def build_parser() -> argparse.ArgumentParser:
''',
)
replace_once(
    "tumorquantai",
    '    add_execution_profile_options(run)\n',
    '    add_execution_profile_options(run)\n    add_execution_backend_options(run)\n',
)
replace_once(
    "tumorquantai",
    '    add_execution_profile_options(quickstart)\n',
    '    add_execution_profile_options(quickstart)\n    add_execution_backend_options(quickstart)\n',
)
regex_once(
    "tumorquantai",
    r'''def resolve_profile\(requested: str\) -> str:\n.*?\n\ndef print_storage_plan''',
    '''def resolve_profile(requested: str, backend: str = "docker") -> str:
    if requested != "auto":
        return requested
    if backend in {"conda", "local"}:
        return "cpu"
    if shutil.which("nvidia-smi"):
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        if result.returncode == 0:
            if backend == "singularity":
                return "gpu"
            if backend == "docker" and shutil.which("docker"):
                daemon = subprocess.run(
                    ["docker", "info", "--format", "{{json .Runtimes}}"],
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    check=False,
                )
                if daemon.returncode == 0 and "nvidia" in daemon.stdout.lower():
                    return "gpu"
    return "cpu"


def print_storage_plan''',
    flags=re.DOTALL,
)
replace_once(
    "tumorquantai",
    '    requested_profile = resolve_profile(args.profile)\n',
    '    if args.profile == "local":\n        args.backend = "local"\n    requested_profile = resolve_profile(args.profile, args.backend)\n'
    '    if args.backend == "conda" and requested_profile == "gpu":\n'
    '        raise core.TumorQuantAIError(\n'
    '            "The versioned Conda environment is CPU-only; use Docker or Singularity for GPU execution.",\n'
    '            core.EXIT_PREFLIGHT,\n'
    '        )\n',
)
replace_once(
    "tumorquantai",
    '        ("execution_profile", requested_profile),\n',
    '        ("execution_profile", requested_profile),\n        ("execution_backend", args.backend),\n',
)
regex_once(
    "tumorquantai",
    r'''    if profile != "local":\n.*?\n\n    percent = float\(args.percent_slide\)''',
    '''    if args.backend == "docker":
        if shutil.which("docker") is None:
            raise core.TumorQuantAIError("Docker is not installed.", core.EXIT_PREFLIGHT)
        daemon = subprocess.run(
            ["docker", "info"], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=False,
        )
        if daemon.returncode != 0:
            raise core.TumorQuantAIError("Docker daemon is unavailable.", core.EXIT_PREFLIGHT)
        if profile == "gpu":
            gpu_visible = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False,
            ) if shutil.which("nvidia-smi") else None
            runtimes = subprocess.run(
                ["docker", "info", "--format", "{{json .Runtimes}}"],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                check=False,
            )
            if (
                gpu_visible is None or gpu_visible.returncode != 0
                or runtimes.returncode != 0 or "nvidia" not in runtimes.stdout.lower()
            ):
                raise core.TumorQuantAIError(
                    "GPU execution requires NVIDIA visibility in Docker.",
                    core.EXIT_PREFLIGHT,
                )
    elif args.backend == "singularity":
        if shutil.which("apptainer") is None and shutil.which("singularity") is None:
            raise core.TumorQuantAIError(
                "Install Apptainer or Singularity before using --singularity.",
                core.EXIT_PREFLIGHT,
            )
        if profile == "gpu" and shutil.which("nvidia-smi") is None:
            raise core.TumorQuantAIError(
                "GPU execution requires an NVIDIA device visible on the host.",
                core.EXIT_PREFLIGHT,
            )
    elif args.backend == "conda":
        if shutil.which("conda") is None:
            raise core.TumorQuantAIError(
                "Conda is not installed. Install Miniforge before using --conda.",
                core.EXIT_PREFLIGHT,
            )
    elif args.backend != "local":
        raise core.TumorQuantAIError(
            f"Unsupported execution backend: {args.backend}", core.EXIT_USAGE
        )

    percent = float(args.percent_slide)''',
    flags=re.DOTALL,
)
replace_once(
    "tumorquantai",
    '        "--work-dir", str(work), "--profile", profile, "--percent-slide", f"{percent:g}",\n',
    '        "--work-dir", str(work), "--backend", args.backend,\n'
    '        "--profile", profile, "--percent-slide", f"{percent:g}",\n',
)
replace_once(
    "tumorquantai",
    '        "--profile", profile, "--seed", str(args.seed), "--work-dir", str(work),\n',
    '        "--backend", args.backend, "--profile", profile,\n'
    '        "--seed", str(args.seed), "--work-dir", str(work),\n',
)
replace_once(
    "tumorquantai",
    '        "target_mpp": args.mpp, "execution_profile": profile,\n        "container_identity": (\n            "not used (local profile)" if profile == "local"\n            else container_image\n        ),\n',
    '        "target_mpp": args.mpp, "execution_profile": profile,\n'
    '        "execution_backend": args.backend,\n'
    '        "container_identity": (\n'
    '            container_image if args.backend in {"docker", "singularity"}\n'
    '            else ("environment.yml" if args.backend == "conda" else "not used")\n'
    '        ),\n',
)
replace_once(
    "tumorquantai",
    '        "selected_samples", "execution_profile", "expert_args_fingerprint",\n',
    '        "selected_samples", "execution_profile", "execution_backend",\n'
    '        "expert_args_fingerprint",\n',
)
replace_once(
    "tumorquantai",
    '    print(f"Execution path: {plan[\'execution_profile\'].upper()}")\n',
    '    print(\n'
    '        f"Execution: {plan[\'execution_backend\'].upper()} / "\n'
    '        f"{plan[\'execution_profile\'].upper()}"\n'
    '    )\n',
)
replace_once(
    "tumorquantai",
    '    profile: str = "auto",\n    inference_manifest:',
    '    profile: str = "auto",\n    backend: str = "docker",\n    inference_manifest:',
)
replace_once(
    "tumorquantai",
    '            "./tumorquantai", "quickstart", "--output", str(root), "--profile", profile,\n            "--seed", str(seed),\n',
    '            "./tumorquantai", "quickstart", "--output", str(root),\n'
    '            "--backend", backend, "--profile", profile, "--seed", str(seed),\n',
)
replace_once(
    "tumorquantai",
    '            "execution_profile", "container_identity", "model_revision",\n',
    '            "execution_profile", "execution_backend", "container_identity",\n'
    '            "model_revision",\n',
)
# Forward the quickstart backend to every manifest update.
text = read("tumorquantai")
text = re.sub(
    r'profile=args\.profile(?=\s*[,\)])',
    'profile=args.profile, backend=args.backend',
    text,
)
write("tumorquantai", text)
replace_once(
    "tumorquantai",
    '        if args.profile != "local":\n            readiness_codes.update({"TQA-DOCKER-CLI", "TQA-DOCKER-DAEMON"})\n',
    '        if args.backend == "docker" and args.profile != "local":\n'
    '            readiness_codes.update({"TQA-DOCKER-CLI", "TQA-DOCKER-DAEMON"})\n',
)
replace_once(
    "tumorquantai",
    '        input=converted, output=smoke_results, preset="smoke", source_mpp=core.TUTORIAL_SOURCE_MPP,\n        sample=core.TUTORIAL_SAMPLE, profile=args.profile, seed=args.seed,\n',
    '        input=converted, output=smoke_results, preset="smoke",\n'
    '        source_mpp=core.TUTORIAL_SOURCE_MPP, sample=core.TUTORIAL_SAMPLE,\n'
    '        profile=args.profile, backend=args.backend, seed=args.seed,\n',
)

# ---------------------------------------------------------------------------
# Runtime regression tests and CI parsing
# ---------------------------------------------------------------------------
write(
    "tests/test_runtime_backends.py",
    '''from __future__ import annotations

import runpy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tumorquantai"


@pytest.mark.parametrize(
    ("flag", "backend"),
    [
        ("--docker", "docker"),
        ("--singularity", "singularity"),
        ("--apptainer", "singularity"),
        ("--conda", "conda"),
    ],
)
def test_runtime_aliases_select_one_backend(flag: str, backend: str) -> None:
    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_backend_test")
    parser = namespace["build_parser"]()
    run = parser.parse_args([
        "run", "/input", "--output", "/output", flag, "--cpu"
    ])
    quickstart = parser.parse_args([
        "quickstart", "--output", "/output", flag, "--cpu"
    ])
    assert run.backend == backend
    assert quickstart.backend == backend
    assert run.profile == quickstart.profile == "cpu"


@pytest.mark.parametrize(
    "arguments",
    [
        ["run", "/input", "--output", "/output", "--docker", "--conda"],
        ["quickstart", "--output", "/output", "--docker", "--singularity"],
    ],
)
def test_runtime_aliases_are_mutually_exclusive(arguments: list[str]) -> None:
    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_backend_exclusion")
    with pytest.raises(SystemExit):
        namespace["build_parser"]().parse_args(arguments)


def test_versioned_conda_environment_contains_scientific_stack() -> None:
    environment = yaml.safe_load((ROOT / "environment.yml").read_text(encoding="utf-8"))
    dependencies = environment["dependencies"]
    rendered = "\n".join(map(str, dependencies))
    assert "pytorch=2.6.0" in rendered
    assert "openslide" in rendered
    assert "libvips" in rendered
    pip_section = next(item["pip"] for item in dependencies if isinstance(item, dict))
    assert "lazyslide==0.10.1" in pip_section
    assert any("lazyslide-models.git@0127beb" in item for item in pip_section)


def test_nextflow_config_exposes_all_runtime_profiles() -> None:
    config = (ROOT / "nextflow.config").read_text(encoding="utf-8")
    for profile in (
        "docker_cpu", "docker_gpu", "singularity_cpu", "singularity_gpu",
        "apptainer_cpu", "apptainer_gpu", "conda_cpu", "local",
    ):
        assert f"{profile} {{" in config
    assert 'conda = "${projectDir}/environment.yml"' in config
''',
)

ci = read(".github/workflows/ci.yml")
ci = ci.replace(
    "          yaml.safe_load(Path('.github/workflows/ci.yml').read_text(encoding='utf-8'))\n",
    "          yaml.safe_load(Path('.github/workflows/ci.yml').read_text(encoding='utf-8'))\n"
    "          yaml.safe_load(Path('environment.yml').read_text(encoding='utf-8'))\n"
    "          import tomllib\n"
    "          tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))\n",
    1,
)
ci = ci.replace(
    "      - name: Compile Python tools\n        run: python -m py_compile tumorquantai lazyslide_histoplus_wsi_celltype.py bin/*.py scripts/*.py\n",
    "      - name: Compile Python tools\n"
    "        run: python -m py_compile tumorquantai lazyslide_histoplus_wsi_celltype.py bin/*.py scripts/*.py tumorquantai_cli/*.py\n",
    1,
)
ci = ci.replace(
    "      - name: Parse Nextflow configuration\n        run: nextflow config -flat >/dev/null\n",
    "      - name: Parse every Nextflow execution profile\n"
    "        run: |\n"
    "          for profile in local docker_cpu docker_gpu singularity_cpu singularity_gpu apptainer_cpu apptainer_gpu conda_cpu; do\n"
    "            nextflow config -profile \"$profile\" -flat >/dev/null\n"
    "          done\n",
    1,
)
write(".github/workflows/ci.yml", ci)

# Keep executable modes in Git; the workflow also chmods before testing.
print("Runtime portability transformation prepared.")
