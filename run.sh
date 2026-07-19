#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

INPUT_DIR=""
OUTPUT_DIR=""
SAMPLE_SHEET=""
PROFILE="auto"
CONTAINER_IMAGE="${CONTAINER_IMAGE:-}"
HF_TOKEN_FILE="${HF_TOKEN_FILE:-${HOME}/.config/lazyslide-histoplus/hf_token}"
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
  --profile auto|gpu|cpu|local    Execution profile (default: auto)
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
  --hf-token-file FILE            Default: ~/.config/lazyslide-histoplus/hf_token
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
  ./run.sh --input-dir /data/exported --profile cpu --percent-slide 1
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
    --hf-token-file) need_value "$@"; HF_TOKEN_FILE="$2"; shift 2 ;;
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

command -v nextflow >/dev/null 2>&1 || die "Nextflow is not installed (see docs/INSTALL.md)"
if [[ "${PROFILE}" != "local" ]]; then
  command -v docker >/dev/null 2>&1 || die "Docker is not installed; use --profile local with a prepared environment"
  docker info >/dev/null 2>&1 || die "Docker daemon is not accessible"
fi

if [[ "${DOCTOR_ONLY}" == "true" ]]; then
  printf 'nextflow: %s\n' "$(nextflow -version 2>&1 | awk '/version/ { print; exit }')"
  command -v docker >/dev/null 2>&1 && printf 'docker:   %s\n' "$(docker --version)"
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

if [[ -n "${HISTOPLUS_WEIGHT_FILE}" ]]; then
  HISTOPLUS_WEIGHT_FILE="$(absolute_path "${HISTOPLUS_WEIGHT_FILE}")"
  [[ -f "${HISTOPLUS_WEIGHT_FILE}" ]] || die "HistoPLUS weight file does not exist: ${HISTOPLUS_WEIGHT_FILE}"
  HISTOPLUS_WEIGHT_SHA256="$(sha256sum -- "${HISTOPLUS_WEIGHT_FILE}" | awk '{print $1}')"
  [[ "${HISTOPLUS_WEIGHT_SHA256}" =~ ^[0-9a-f]{64}$ ]] || \
    die "Could not compute the HistoPLUS weight SHA-256"
fi

if [[ -z "${HF_TOKEN:-}" && -f "${HF_TOKEN_FILE}" ]]; then
  HF_TOKEN="$(tr -d '\r\n' < "${HF_TOKEN_FILE}")"
  export HF_TOKEN
fi
if [[ "${DRY_RUN}" != "true" && -z "${HF_TOKEN:-}" && -z "${HISTOPLUS_WEIGHT_FILE}" ]]; then
  printf 'WARNING: HF_TOKEN is unset; gated HistoPLUS weight download may fail.\n' >&2
fi

case "${PROFILE}" in
  auto)
    if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
      NF_PROFILE="docker_gpu"
      DEVICE="cuda"
    else
      NF_PROFILE="docker_cpu"
      DEVICE="cpu"
    fi
    ;;
  gpu|docker_gpu) NF_PROFILE="docker_gpu"; DEVICE="cuda" ;;
  cpu|docker_cpu) NF_PROFILE="docker_cpu"; DEVICE="cpu" ;;
  local) NF_PROFILE="local" ;;
  *) die "Unsupported profile: ${PROFILE}" ;;
esac

if [[ -z "${CONTAINER_IMAGE}" ]]; then
  case "${NF_PROFILE}" in
    docker_gpu) CONTAINER_IMAGE="carlosfarkas/lazyslide-histoplus@sha256:c4b02485d4549a56348cd09995ce0788a6acc8a3e1e600e986b644231a95bd25" ;;
    *) CONTAINER_IMAGE="carlosfarkas/lazyslide-histoplus@sha256:413bed6b55bc86923321c61453c18ece678da3c125ae44dcbd5f6c3bce7115d4" ;;
  esac
fi

[[ -n "${DEVICE}" ]] || DEVICE="cpu"

PATTERN_VALUE="*_L0_rgb.tif,*_L0_rgb.tiff"
if [[ ${#PATTERNS[@]} -gt 0 ]]; then
  PATTERN_VALUE="$(IFS=,; printf '%s' "${PATTERNS[*]}")"
fi

WORKER_HISTOPLUS_CACHE="${HISTOPLUS_CACHE}"
DOCKER_RUN_OPTIONS=""
if [[ "${NF_PROFILE}" != "local" ]]; then
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
  DOCKER_RUN_OPTIONS="-u $(id -u):$(id -g) -e HOME=/home/lazyslide -e HF_TOKEN -e HF_HOME=/home/lazyslide/.cache/huggingface -e HUGGINGFACE_HUB_CACHE=/home/lazyslide/.cache/huggingface/hub -v ${INPUT_DIR}:${INPUT_DIR}:ro -v ${OUTPUT_DIR}:${OUTPUT_DIR} -v ${HF_CACHE}:/home/lazyslide/.cache/huggingface -v ${HISTOPLUS_CACHE}:/home/lazyslide/.cache/histoplus ${SAMPLE_SHEET_MOUNT} ${HISTOPLUS_WEIGHT_MOUNT}"
fi

NF_ARGS=(
  run "${SCRIPT_DIR}"
  -profile "${NF_PROFILE}"
  -work-dir "${WORK_DIR}"
  --input_dir "${INPUT_DIR}"
  --output_dir "${OUTPUT_DIR}"
  --slide_patterns "${PATTERN_VALUE}"
  --include "${INCLUDE}"
  --exclude "${EXCLUDE}"
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
