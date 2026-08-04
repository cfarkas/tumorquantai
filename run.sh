#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

INPUT_DIR=""
OUTPUT_DIR=""
SAMPLE_SHEET=""
PROFILE="auto"
BACKEND="${TUMORQUANTAI_BACKEND:-docker}"
CONTAINER_IMAGE="${CONTAINER_IMAGE:-}"
CANONICAL_HF_TOKEN_FILE="${HOME}/.config/tumorquantai/hf_token"
LEGACY_HF_TOKEN_FILE="${HOME}/.config/lazyslide-histoplus/hf_token"
CONFIGURED_TUMORQUANTAI_TOKEN_FILE="${TUMORQUANTAI_HF_TOKEN_FILE:-}"
LEGACY_AUTOMATION_TOKEN_FILE="${HF_TOKEN_FILE:-}"
HF_TOKEN_FILE="${CANONICAL_HF_TOKEN_FILE}"
HF_TOKEN_FILE_EXPLICIT="false"
HF_CACHE="${HF_HOME:-${HOME}/.cache/lazyslide-histoplus/huggingface}"
HISTOPLUS_CACHE="${HISTOPLUS_CACHE:-${HOME}/.cache/lazyslide-histoplus/histoplus}"
HISTOPLUS_REVISION="${HISTOPLUS_REVISION:-cde2eee81af9e39b03802fc33d4f284733b5ee5e}"
HISTOPLUS_WEIGHT_FILE="${HISTOPLUS_WEIGHT_FILE:-}"
HISTOPLUS_WEIGHT_SHA256=""
WORK_DIR="${NXF_WORK:-${SCRIPT_DIR}/work}"
INCLUDE="*"
EXCLUDE=""
PATTERNS=()
MODE=""
PERCENT_SLIDE=""
PERCENT_SLIDE_SET="false"
PATCH_RANDOM_SEED="20260709"
MPP="0.5"
SLIDE_MPP=""
TILE_PX="840"
DEVICE=""
CPUS="8"
MEMORY="32 GB"
SHM_SIZE="2g"
TIME_LIMIT="120h"
NUM_WORKERS="2"
MAX_PARALLEL_SLIDES="1"
CELLTYPES_BATCH_SIZE="2"
QC_PATCH_COUNT="0"
COLLAGE=""
DRY_RUN="false"
CONVERT_TO_PYRAMIDAL="true"
CONTINUE_ON_ERROR="true"
NEXTFLOW_RESUME="true"
RUN_CELLS_STAGE="false"
EXPORT_QUPATH="false"
AMP="false"
PLAIN_CSV="true"
DOCTOR_ONLY="false"
RUN_ID="$(date +%Y%m%d_%H%M%S)_$$"
EXTRA_NF_ARGS=()


usage() {
  cat <<'USAGE'
Usage:
  ./run.sh --input-dir DIR [--output-dir DIR] [options]

Portable input:
  A directory containing exported primary L0 TIFFs. By default only
  *_L0_rgb.tif and *_L0_rgb.tiff are selected; companion L2/L3 TIFFs are not.

Core options:
  --input-dir DIR                 Required slide root
  --output-dir DIR                Default: <input-dir>_histoplus_results
  --sample-sheet CSV|TSV          Explicit sample_id,slide_path mapping
  --pattern GLOB                  Primary-slide glob; repeat as needed
  --include GLOB                  Filter inferred sample IDs (default: *)
  --exclude GLOB                  Exclude inferred sample IDs
  --dry-run                       Discover and write a manifest only
  --mode full|fast                Full uses 100%; fast defaults to 10%
  --full                          Alias for --mode full
  --fast                          Alias for --mode fast
  --percent-slide FLOAT           Explicit percent in (0,100]; usable without --mode
  --seed INT                      Sampling seed (default: 20260709)
  --backend docker|singularity|conda|local
                                  Software execution backend (default: docker)
  --docker                       Alias for --backend docker
  --singularity                  Alias for --backend singularity or Apptainer
  --conda                        Alias for --backend conda
  --profile auto|gpu|cpu|local    Compute profile (default: auto; local remains compatible)
  --container-image IMAGE         Docker image override
  --no-resume                     Disable Nextflow cache reuse
  --fail-fast                     Stop after a sample exhausts retries
  --doctor                        Check prerequisites and exit

Inference/resources:
  --mpp FLOAT                     Target model-tile MPP (default: 0.5)
  --slide-mpp FLOAT               Verified physical MPP of source L0; required when metadata is absent
  --tile-px INT                   Default: 840 (must be divisible by 14)
  --device cuda|cpu|auto          Normally selected by --profile
  --celltypes-batch-size INT      Default: 2
  --num-workers INT               DataLoader workers (default: 2)
  --max-parallel-slides INT        Concurrent slide tasks (default: 1; GPU-safe)
  --cpus INT                      CPUs per slide task (default: 8)
  --memory STRING                 Memory per slide task (default: 32 GB)
  --shm-size SIZE                 Docker shared memory (default: 2g; prevents DataLoader bus errors)
  --time STRING                   Limit per slide task (default: 120h)
  --qc-patch-count INT            Dense QC overlays per slide
  --collage GRID                  Sampled patch collage, e.g. 4x4
  --run-cells-stage               Also run optional InstanSeg cell stage
  --export-qupath                 Export QuPath annotations
  --amp                           Enable mixed precision (test first)
  --no-convert-to-pyramidal       Use input TIFF directly
  --compressed-coordinates        Write cell coordinates as csv.gz

Authentication/cache:
  --hf-token-file FILE            Default: TUMORQUANTAI_HF_TOKEN_FILE or
                                  ~/.config/tumorquantai/hf_token; legacy path supported
  --hf-cache DIR                  Hugging Face cache mounted into Docker
  --histoplus-cache DIR           Resolved HistoPLUS weight cache
  --histoplus-weight-file FILE     Existing gated 20x/40x weight; never copied into outputs
  --histoplus-revision SHA        Immutable 40-hex model revision
  --work-dir DIR                  Nextflow work directory

Everything after -- is passed directly to Nextflow.

Examples:
  ./run.sh --input-dir /data/exported --dry-run
  ./run.sh --input-dir /data/exported --full
  ./run.sh --input-dir /data/exported --fast
  ./run.sh --input-dir /data/exported --docker --profile cpu --percent-slide 1
  ./run.sh --input-dir /data/exported --singularity --profile cpu --percent-slide 1
  ./run.sh --input-dir /data/exported --conda --profile cpu --percent-slide 1
USAGE
}


die() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }


need_value() {
  [[ $# -ge 2 && -n "${2:-}" && "${2:-}" != --* ]] || die "Missing value for $1"
}


absolute_path() {
  realpath -m -- "$1"
}


set_mode() {
  local requested="$1"
  if [[ -n "${MODE}" && "${MODE}" != "${requested}" ]]; then
    die "Conflicting modes: ${MODE} and ${requested}"
  fi
  MODE="${requested}"
}


set_percent_slide() {
  if [[ "${PERCENT_SLIDE_SET}" == "true" ]]; then
    die "--percent-slide may be specified only once"
  fi
  PERCENT_SLIDE="$1"
  PERCENT_SLIDE_SET="true"
}


valid_positive() {
  local value="$1"
  [[ "${value}" =~ ^[+]?(([0-9]+([.][0-9]*)?)|([.][0-9]+))([eE][+-]?[0-9]+)?$ ]] || return 1
  awk -v value="${value}" 'BEGIN { exit !(value > 0) }'
}


valid_percent() {
  local value="$1"
  [[ "${value}" =~ ^[+]?(([0-9]+([.][0-9]*)?)|([.][0-9]+))([eE][+-]?[0-9]+)?$ ]] || return 1
  awk -v value="${value}" 'BEGIN { exit !(value > 0 && value <= 100) }'
}


percent_is_100() {
  awk -v value="$1" 'BEGIN { exit !(value == 100) }'
}


percent_is_less_than_100() {
  awk -v value="$1" 'BEGIN { exit !(value < 100) }'
}


while [[ $# -gt 0 ]]; do
  case "$1" in
    --input-dir) need_value "$@"; INPUT_DIR="$2"; shift 2 ;;
    --output-dir|--output-root) need_value "$@"; OUTPUT_DIR="$2"; shift 2 ;;
    --sample-sheet) need_value "$@"; SAMPLE_SHEET="$2"; shift 2 ;;
    --pattern) need_value "$@"; PATTERNS+=("$2"); shift 2 ;;
    --include) need_value "$@"; INCLUDE="$2"; shift 2 ;;
    --exclude) need_value "$@"; EXCLUDE="$2"; shift 2 ;;
    --mode)
      need_value "$@"
      [[ "$2" == "full" || "$2" == "fast" ]] || die "--mode must be full or fast"
      set_mode "$2"
      shift 2
      ;;
    --full) set_mode "full"; shift ;;
    --fast) set_mode "fast"; shift ;;
    --percent-slide|--percent_slide)
      need_value "$@"
      set_percent_slide "$2"
      shift 2
      ;;
    --seed|--patch-random-seed) need_value "$@"; PATCH_RANDOM_SEED="$2"; shift 2 ;;
    --mpp) need_value "$@"; MPP="$2"; shift 2 ;;
    --slide-mpp) need_value "$@"; SLIDE_MPP="$2"; shift 2 ;;
    --tile-px) need_value "$@"; TILE_PX="$2"; shift 2 ;;
    --device) need_value "$@"; DEVICE="$2"; shift 2 ;;
    --backend) need_value "$@"; BACKEND="$2"; shift 2 ;;
    --docker) BACKEND="docker"; shift ;;
    --singularity|--apptainer) BACKEND="singularity"; shift ;;
    --conda) BACKEND="conda"; shift ;;
    --local) BACKEND="local"; shift ;;
    --profile) need_value "$@"; PROFILE="$2"; shift 2 ;;
    --container-image) need_value "$@"; CONTAINER_IMAGE="$2"; shift 2 ;;
    --celltypes-batch-size) need_value "$@"; CELLTYPES_BATCH_SIZE="$2"; shift 2 ;;
    --num-workers) need_value "$@"; NUM_WORKERS="$2"; shift 2 ;;
    --max-parallel-slides) need_value "$@"; MAX_PARALLEL_SLIDES="$2"; shift 2 ;;
    --cpus) need_value "$@"; CPUS="$2"; shift 2 ;;
    --memory) need_value "$@"; MEMORY="$2"; shift 2 ;;
    --shm-size) need_value "$@"; SHM_SIZE="$2"; shift 2 ;;
    --time) need_value "$@"; TIME_LIMIT="$2"; shift 2 ;;
    --qc-patch-count) need_value "$@"; QC_PATCH_COUNT="$2"; shift 2 ;;
    --collage) need_value "$@"; COLLAGE="$2"; shift 2 ;;
    --hf-token-file) need_value "$@"; HF_TOKEN_FILE="$2"; HF_TOKEN_FILE_EXPLICIT="true"; shift 2 ;;
    --hf-cache) need_value "$@"; HF_CACHE="$2"; shift 2 ;;
    --histoplus-cache) need_value "$@"; HISTOPLUS_CACHE="$2"; shift 2 ;;
    --histoplus-weight-file) need_value "$@"; HISTOPLUS_WEIGHT_FILE="$2"; shift 2 ;;
    --histoplus-revision) need_value "$@"; HISTOPLUS_REVISION="$2"; shift 2 ;;
    --work-dir) need_value "$@"; WORK_DIR="$2"; shift 2 ;;
    --dry-run) DRY_RUN="true"; shift ;;
    --no-resume) NEXTFLOW_RESUME="false"; shift ;;
    --fail-fast) CONTINUE_ON_ERROR="false"; shift ;;
    --run-cells-stage) RUN_CELLS_STAGE="true"; shift ;;
    --export-qupath) EXPORT_QUPATH="true"; shift ;;
    --amp) AMP="true"; shift ;;
    --no-convert-to-pyramidal) CONVERT_TO_PYRAMIDAL="false"; shift ;;
    --compressed-coordinates) PLAIN_CSV="false"; shift ;;
    --doctor) DOCTOR_ONLY="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    --)
      shift
      for argument in "$@"; do
        case "${argument}" in
          --percent-slide|--percent-slide=*|--percent_slide|--percent_slide=*|\
          --slide-mpp|--slide-mpp=*|--slide_mpp|--slide_mpp=*|\
          --histoplus-weight-file|--histoplus-weight-file=*|--histoplus_weight_file|--histoplus_weight_file=*|\
          --histoplus-weight-sha256|--histoplus-weight-sha256=*|--histoplus_weight_sha256|--histoplus_weight_sha256=*|\
          --histoplus-revision|--histoplus-revision=*|--histoplus_revision|--histoplus_revision=*|\
          --docker-shm-size|--docker-shm-size=*|--docker_shm_size|--docker_shm_size=*)
            die "Pass protected workflow parameters before --"
            ;;
        esac
      done
      EXTRA_NF_ARGS+=("$@")
      break
      ;;
    *) die "Unknown option: $1" ;;
  esac
done


if [[ ! "${SHM_SIZE}" =~ ^[1-9][0-9]*([kKmMgG][bB]?)?$ ]]; then
  die "--shm-size must be a positive integer optionally followed by k, m, or g"
fi

if ! valid_positive "${MPP}"; then
  die "--mpp must be numeric and > 0"
fi
if [[ -n "${SLIDE_MPP}" ]] && ! valid_positive "${SLIDE_MPP}"; then
  die "--slide-mpp must be numeric and > 0"
fi

if [[ "${PERCENT_SLIDE_SET}" == "true" ]]; then
  valid_percent "${PERCENT_SLIDE}" || die "--percent-slide must be numeric in the interval (0, 100]"
fi

case "${MODE}" in
  full)
    if [[ "${PERCENT_SLIDE_SET}" == "true" ]] && ! percent_is_100 "${PERCENT_SLIDE}"; then
      die "--mode full requires --percent-slide 100"
    fi
    PERCENT_SLIDE="100"
    ;;
  fast)
    if [[ "${PERCENT_SLIDE_SET}" == "true" ]]; then
      percent_is_less_than_100 "${PERCENT_SLIDE}" || \
        die "--mode fast requires --percent-slide below 100"
    else
      PERCENT_SLIDE="10"
    fi
    ;;
  "")
    if [[ "${PERCENT_SLIDE_SET}" != "true" ]]; then
      PERCENT_SLIDE="100"
    fi
    if percent_is_100 "${PERCENT_SLIDE}"; then
      MODE="full"
    else
      MODE="fast"
    fi
    ;;
esac

[[ "${HISTOPLUS_REVISION}" =~ ^[0-9a-fA-F]{40}$ ]] || \
  die "--histoplus-revision must be an immutable full 40-hex commit SHA"

case "${BACKEND}" in
  docker|singularity|conda|local) ;;
  *) die "--backend must be docker, singularity, conda, or local" ;;
esac

# Backward compatibility: --profile local selects the local backend.
if [[ "${PROFILE}" == "local" ]]; then
  BACKEND="local"
fi

command -v nextflow >/dev/null 2>&1 || die "Nextflow is not installed (see docs/installation.md)"
case "${BACKEND}" in
  docker)
    command -v docker >/dev/null 2>&1 || die "Docker is not installed"
    docker info >/dev/null 2>&1 || die "Docker daemon is not accessible"
    ;;
  singularity)
    command -v apptainer >/dev/null 2>&1 || command -v singularity >/dev/null 2>&1 || \
      die "Install Apptainer or Singularity before using --singularity"
    ;;
  conda)
    command -v conda >/dev/null 2>&1 || die "Conda is not installed; install Miniforge before using --conda"
    ;;
  local) ;;
esac

if [[ "${DOCTOR_ONLY}" == "true" ]]; then
  printf 'nextflow:    %s\n' "$(nextflow -version 2>&1 | awk '/version/ { print; exit }')"
  printf 'backend:     %s\n' "${BACKEND}"
  command -v docker >/dev/null 2>&1 && printf 'docker:      %s\n' "$(docker --version)"
  command -v apptainer >/dev/null 2>&1 && printf 'apptainer:   %s\n' "$(apptainer --version)"
  command -v singularity >/dev/null 2>&1 && printf 'singularity: %s\n' "$(singularity --version)"
  command -v conda >/dev/null 2>&1 && printf 'conda:       %s\n' "$(conda --version)"
  command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true
  printf 'doctor: OK\n'
  exit 0
fi

[[ -n "${INPUT_DIR}" ]] || { usage >&2; die "--input-dir is required"; }
INPUT_DIR="$(absolute_path "${INPUT_DIR}")"
[[ -d "${INPUT_DIR}" ]] || die "Input directory does not exist: ${INPUT_DIR}"

if [[ -z "${OUTPUT_DIR}" ]]; then
  OUTPUT_DIR="${INPUT_DIR%/}_histoplus_results"
fi
OUTPUT_DIR="$(absolute_path "${OUTPUT_DIR}")"
WORK_DIR="$(absolute_path "${WORK_DIR}")"
[[ "${OUTPUT_DIR}" != "${INPUT_DIR}" ]] || die "Output directory must differ from input directory"
mkdir -p "${OUTPUT_DIR}" "${WORK_DIR}" "${HF_CACHE}" "${HISTOPLUS_CACHE}"

if [[ -n "${SAMPLE_SHEET}" ]]; then
  SAMPLE_SHEET="$(absolute_path "${SAMPLE_SHEET}")"
  [[ -f "${SAMPLE_SHEET}" ]] || die "Sample sheet does not exist: ${SAMPLE_SHEET}"
fi

if [[ "${DRY_RUN}" == "true" ]]; then
  # Discovery does not need gated model access. Do not read, hash, or forward
  # any credential or authorized local-weight path in this mode.
  unset HF_TOKEN TUMORQUANTAI_HF_TOKEN_FILE HF_TOKEN_FILE HISTOPLUS_WEIGHT_FILE
  HISTOPLUS_WEIGHT_FILE=""
  HISTOPLUS_WEIGHT_SHA256=""
else
  if [[ -n "${HISTOPLUS_WEIGHT_FILE}" ]]; then
    # A local authorized weight is sufficient. Prevent unrelated credentials
    # from entering Nextflow, a local worker, or Docker.
    unset HF_TOKEN TUMORQUANTAI_HF_TOKEN_FILE HF_TOKEN_FILE
    HF_TOKEN_FILE=""
  elif [[ -n "${CONFIGURED_TUMORQUANTAI_TOKEN_FILE}" ]]; then
    HF_TOKEN_FILE="${CONFIGURED_TUMORQUANTAI_TOKEN_FILE}"
  elif [[ "${HF_TOKEN_FILE_EXPLICIT}" == "true" ]]; then
    :
  elif [[ -f "${CANONICAL_HF_TOKEN_FILE}" ]]; then
    HF_TOKEN_FILE="${CANONICAL_HF_TOKEN_FILE}"
  elif [[ -n "${LEGACY_AUTOMATION_TOKEN_FILE}" ]]; then
    printf 'WARNING: HF_TOKEN_FILE is deprecated; use TUMORQUANTAI_HF_TOKEN_FILE.\n' >&2
    HF_TOKEN_FILE="${LEGACY_AUTOMATION_TOKEN_FILE}"
  elif [[ -f "${LEGACY_HF_TOKEN_FILE}" ]]; then
    printf 'WARNING: using deprecated HistoPLUS token path; move it to ~/.config/tumorquantai/hf_token.\n' >&2
    HF_TOKEN_FILE="${LEGACY_HF_TOKEN_FILE}"
  else
    HF_TOKEN_FILE="${CANONICAL_HF_TOKEN_FILE}"
  fi

  if [[ -n "${HISTOPLUS_WEIGHT_FILE}" ]]; then
    HISTOPLUS_WEIGHT_FILE="$(absolute_path "${HISTOPLUS_WEIGHT_FILE}")"
    [[ -f "${HISTOPLUS_WEIGHT_FILE}" ]] || die "HistoPLUS weight file does not exist: ${HISTOPLUS_WEIGHT_FILE}"
    HISTOPLUS_WEIGHT_SHA256="$(sha256sum -- "${HISTOPLUS_WEIGHT_FILE}" | awk '{print $1}')"
    [[ "${HISTOPLUS_WEIGHT_SHA256}" =~ ^[0-9a-f]{64}$ ]] || \
      die "Could not compute the HistoPLUS weight SHA-256"
  fi

  if [[ -z "${HISTOPLUS_WEIGHT_FILE}" && -f "${HF_TOKEN_FILE}" ]]; then
    HF_TOKEN="$(tr -d '\r\n' < "${HF_TOKEN_FILE}")"
    export HF_TOKEN
  fi
  if [[ -z "${HF_TOKEN:-}" && -z "${HISTOPLUS_WEIGHT_FILE}" ]]; then
    printf 'WARNING: HF_TOKEN is unset; gated HistoPLUS weight download may fail.\n' >&2
  fi
fi

# These paths are launcher inputs, not worker environment variables. Keep only
# the HF_TOKEN value exported when a gated download actually needs it.
unset TUMORQUANTAI_HF_TOKEN_FILE
export -n HF_TOKEN_FILE HISTOPLUS_WEIGHT_FILE 2>/dev/null || true

case "${PROFILE}" in
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

if [[ "${BACKEND}" == "singularity"   && "${CONTAINER_IMAGE}" != *://*   && "${CONTAINER_IMAGE}" != /*   && "${CONTAINER_IMAGE}" != *.sif ]]; then
  CONTAINER_IMAGE="docker://${CONTAINER_IMAGE}"
fi

[[ -n "${DEVICE}" ]] || DEVICE="cpu"

PATTERN_VALUE="*_L0_rgb.tif,*_L0_rgb.tiff"
if [[ ${#PATTERNS[@]} -gt 0 ]]; then
  PATTERN_VALUE="$(IFS=,; printf '%s' "${PATTERNS[*]}")"
fi

WORKER_HISTOPLUS_CACHE="${HISTOPLUS_CACHE}"
DOCKER_RUN_OPTIONS=""
if [[ "${BACKEND}" == "docker" ]]; then
  for MOUNT_PATH in "${INPUT_DIR}" "${OUTPUT_DIR}" "${HF_CACHE}" "${HISTOPLUS_CACHE}"; do
    [[ "${MOUNT_PATH}" != *:* && ! "${MOUNT_PATH}" =~ [[:space:]] ]] || \
      die "Docker bind-mount paths cannot contain whitespace or ':' characters: ${MOUNT_PATH}"
  done
  if [[ -n "${SAMPLE_SHEET}" ]]; then
    SAMPLE_SHEET_DIR="$(dirname "${SAMPLE_SHEET}")"
    [[ "${SAMPLE_SHEET_DIR}" != *:* && ! "${SAMPLE_SHEET_DIR}" =~ [[:space:]] ]] || \
      die "Docker bind-mount paths cannot contain whitespace or ':' characters: ${SAMPLE_SHEET_DIR}"
  fi

  SAMPLE_SHEET_MOUNT=""
  if [[ -n "${SAMPLE_SHEET}" && "${SAMPLE_SHEET}" != "${INPUT_DIR}"/* ]]; then
    SAMPLE_SHEET_MOUNT="-v ${SAMPLE_SHEET_DIR}:${SAMPLE_SHEET_DIR}:ro"
  fi
  WORKER_HISTOPLUS_CACHE="/home/lazyslide/.cache/histoplus"
  HISTOPLUS_WEIGHT_MOUNT=""
  if [[ -n "${HISTOPLUS_WEIGHT_FILE}" ]]; then
    [[ "${HISTOPLUS_WEIGHT_FILE}" != *:* && ! "${HISTOPLUS_WEIGHT_FILE}" =~ [[:space:]] ]] || \
      die "Docker bind-mount paths cannot contain whitespace or : characters: ${HISTOPLUS_WEIGHT_FILE}"
    HISTOPLUS_WEIGHT_MOUNT="-v ${HISTOPLUS_WEIGHT_FILE}:${HISTOPLUS_WEIGHT_FILE}:ro"
  fi
  HF_TOKEN_DOCKER_OPTION=""
  [[ -n "${HF_TOKEN:-}" ]] && HF_TOKEN_DOCKER_OPTION="-e HF_TOKEN"
  DOCKER_RUN_OPTIONS="-u $(id -u):$(id -g) -e HOME=/home/lazyslide ${HF_TOKEN_DOCKER_OPTION} -e HF_HOME=/home/lazyslide/.cache/huggingface -e HUGGINGFACE_HUB_CACHE=/home/lazyslide/.cache/huggingface/hub -v ${INPUT_DIR}:${INPUT_DIR}:ro -v ${OUTPUT_DIR}:${OUTPUT_DIR} -v ${HF_CACHE}:/home/lazyslide/.cache/huggingface -v ${HISTOPLUS_CACHE}:/home/lazyslide/.cache/histoplus ${SAMPLE_SHEET_MOUNT} ${HISTOPLUS_WEIGHT_MOUNT}"
fi

if [[ "${BACKEND}" == "singularity" ]]; then
  export NXF_SINGULARITY_CACHEDIR="${NXF_SINGULARITY_CACHEDIR:-${WORK_DIR}/singularity-cache}"
  export NXF_APPTAINER_CACHEDIR="${NXF_APPTAINER_CACHEDIR:-${WORK_DIR}/apptainer-cache}"
  mkdir -p "${NXF_SINGULARITY_CACHEDIR}" "${NXF_APPTAINER_CACHEDIR}"

  # Apptainer/Singularity do not automatically expose every absolute host path
  # used by the launcher. Bind all workflow inputs read-only and all mutable
  # workflow/cache paths read-write so a command behaves like the Docker route.
  SINGULARITY_BIND_PATHS=(
    "${SCRIPT_DIR}"
    "${INPUT_DIR}"
    "${OUTPUT_DIR}"
    "${WORK_DIR}"
    "${HF_CACHE}"
    "${HISTOPLUS_CACHE}"
  )
  if [[ -n "${SAMPLE_SHEET}" ]]; then
    SINGULARITY_BIND_PATHS+=("$(dirname "${SAMPLE_SHEET}")")
  fi
  if [[ -n "${HISTOPLUS_WEIGHT_FILE}" ]]; then
    SINGULARITY_BIND_PATHS+=("$(dirname "${HISTOPLUS_WEIGHT_FILE}")")
  fi
  for BIND_PATH in "${SINGULARITY_BIND_PATHS[@]}"; do
    [[ "${BIND_PATH}" != *:*       && "${BIND_PATH}" != *,*       && ! "${BIND_PATH}" =~ [[:space:]] ]] ||       die "Singularity bind paths cannot contain whitespace, ',' or ':' characters: ${BIND_PATH}"
  done

  SINGULARITY_BIND_SPECS=(
    "${SCRIPT_DIR}:${SCRIPT_DIR}:ro"
    "${INPUT_DIR}:${INPUT_DIR}:ro"
    "${OUTPUT_DIR}:${OUTPUT_DIR}"
    "${WORK_DIR}:${WORK_DIR}"
    "${HF_CACHE}:${HF_CACHE}"
    "${HISTOPLUS_CACHE}:${HISTOPLUS_CACHE}"
  )
  if [[ -n "${SAMPLE_SHEET}" && "${SAMPLE_SHEET}" != "${INPUT_DIR}"/* ]]; then
    SAMPLE_SHEET_DIR="$(dirname "${SAMPLE_SHEET}")"
    SINGULARITY_BIND_SPECS+=("${SAMPLE_SHEET_DIR}:${SAMPLE_SHEET_DIR}:ro")
  fi
  if [[ -n "${HISTOPLUS_WEIGHT_FILE}" ]]; then
    HISTOPLUS_WEIGHT_DIR="$(dirname "${HISTOPLUS_WEIGHT_FILE}")"
    SINGULARITY_BIND_SPECS+=("${HISTOPLUS_WEIGHT_DIR}:${HISTOPLUS_WEIGHT_DIR}:ro")
  fi
  GENERATED_BINDPATH="$(IFS=,; printf '%s' "${SINGULARITY_BIND_SPECS[*]}")"
  EXISTING_APPTAINER_BINDPATH="${APPTAINER_BINDPATH:-}"
  EXISTING_SINGULARITY_BINDPATH="${SINGULARITY_BINDPATH:-}"
  export APPTAINER_BINDPATH="${GENERATED_BINDPATH}${EXISTING_APPTAINER_BINDPATH:+,${EXISTING_APPTAINER_BINDPATH}}"
  export SINGULARITY_BINDPATH="${GENERATED_BINDPATH}${EXISTING_SINGULARITY_BINDPATH:+,${EXISTING_SINGULARITY_BINDPATH}}"

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
  run "${SCRIPT_DIR}"
  -profile "${NF_PROFILE}"
  -work-dir "${WORK_DIR}"
  --input_dir "${INPUT_DIR}"
  --output_dir "${OUTPUT_DIR}"
  --slide_patterns "${PATTERN_VALUE}"
  --include "${INCLUDE}"
  --dry_run "${DRY_RUN}"
  --container_image "${CONTAINER_IMAGE}"
  --docker_run_options "${DOCKER_RUN_OPTIONS}"
  --docker_shm_size "${SHM_SIZE}"
  --percent_slide "${PERCENT_SLIDE}"
  --patch_random_seed "${PATCH_RANDOM_SEED}"
  --mpp "${MPP}"
  --tile_px "${TILE_PX}"
  --device "${DEVICE}"
  --cpus "${CPUS}"
  --memory "${MEMORY}"
  --time "${TIME_LIMIT}"
  --num_workers "${NUM_WORKERS}"
  --max_parallel_slides "${MAX_PARALLEL_SLIDES}"
  --celltypes_batch_size "${CELLTYPES_BATCH_SIZE}"
  --histoplus_revision "${HISTOPLUS_REVISION}"
  --qc_patch_count "${QC_PATCH_COUNT}"
  --continue_on_error "${CONTINUE_ON_ERROR}"
  --convert_to_pyramidal "${CONVERT_TO_PYRAMIDAL}"
  --run_cells_stage "${RUN_CELLS_STAGE}"
  --export_qupath "${EXPORT_QUPATH}"
  --amp "${AMP}"
  --plain_csv "${PLAIN_CSV}"
  --histoplus_cache_dir "${WORKER_HISTOPLUS_CACHE}"
  -with-report "${OUTPUT_DIR}/workflow_metadata/nextflow_report_${RUN_ID}.html"
  -with-trace "${OUTPUT_DIR}/workflow_metadata/nextflow_trace_${RUN_ID}.tsv"
  -with-timeline "${OUTPUT_DIR}/workflow_metadata/nextflow_timeline_${RUN_ID}.html"
  -ansi-log false
)

[[ -n "${SLIDE_MPP}" ]] && NF_ARGS+=(--slide_mpp "${SLIDE_MPP}")
[[ -n "${EXCLUDE}" ]] && NF_ARGS+=(--exclude "${EXCLUDE}")
if [[ -n "${HISTOPLUS_WEIGHT_FILE}" ]]; then
  NF_ARGS+=(
    --histoplus_weight_file "${HISTOPLUS_WEIGHT_FILE}"
    --histoplus_weight_sha256 "${HISTOPLUS_WEIGHT_SHA256}"
  )
fi
[[ -n "${SAMPLE_SHEET}" ]] && NF_ARGS+=(--sample_sheet "${SAMPLE_SHEET}")
[[ -n "${COLLAGE}" ]] && NF_ARGS+=(--collage "${COLLAGE}")
[[ "${NEXTFLOW_RESUME}" == "true" ]] && NF_ARGS+=(-resume)
NF_ARGS+=("${EXTRA_NF_ARGS[@]}")

printf 'backend:    %s\n' "${BACKEND}"
printf 'profile:    %s\n' "${NF_PROFILE}"
printf 'input:      %s\n' "${INPUT_DIR}"
printf 'output:     %s\n' "${OUTPUT_DIR}"
printf 'mode:       %s\n' "${MODE}"
printf 'sampling:   %s%%\n' "${PERCENT_SLIDE}"
printf 'target mpp: %s\n' "${MPP}"
printf 'source mpp: %s\n' "${SLIDE_MPP:-embedded metadata}"
printf 'parallel:   %s slide(s)\n' "${MAX_PARALLEL_SLIDES}"
printf 'docker shm: %s\n' "${SHM_SIZE}"
printf 'container:  %s\n' "${CONTAINER_IMAGE}"
printf 'model rev:  %s\n' "${HISTOPLUS_REVISION}"

exec nextflow "${NF_ARGS[@]}"
