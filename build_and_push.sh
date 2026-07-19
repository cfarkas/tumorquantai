#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${IMAGE:-carlosfarkas/tumorquantai}"
TAG="${TAG:-0.4.0}"
FLAVOR="${FLAVOR:-both}"
PUSH="false"
NO_CACHE="false"

usage() {
  cat <<'USAGE'
Usage: ./build_and_push.sh [--image NAME] [--tag TAG] [--flavor cpu|gpu|both] [--push] [--no-cache]

Without --push, images are loaded into the local Docker daemon. CPU and GPU
images receive explicit -cpu and -gpu suffixes; no mutable latest tag is made.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image) IMAGE="$2"; shift 2 ;;
    --tag) TAG="$2"; shift 2 ;;
    --flavor) FLAVOR="$2"; shift 2 ;;
    --push) PUSH="true"; shift ;;
    --no-cache) NO_CACHE="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; exit 2 ;;
  esac
done

case "${FLAVOR}" in
  cpu) flavors=(cpu) ;;
  gpu) flavors=(gpu) ;;
  both) flavors=(cpu gpu) ;;
  *) echo 'ERROR: --flavor must be cpu, gpu, or both' >&2; exit 2 ;;
esac

command -v docker >/dev/null 2>&1 || { echo 'ERROR: Docker is required' >&2; exit 2; }
VCS_REF="$(git -C "${SCRIPT_DIR}" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"

for flavor in "${flavors[@]}"; do
  args=(
    buildx build "${SCRIPT_DIR}"
    --build-arg "FLAVOR=${flavor}"
    --build-arg "VCS_REF=${VCS_REF}"
    --tag "${IMAGE}:${TAG}-${flavor}"
  )
  [[ "${NO_CACHE}" == "true" ]] && args+=(--no-cache)
  if [[ "${PUSH}" == "true" ]]; then
    args+=(--push)
  else
    args+=(--load)
  fi
  docker "${args[@]}"
done
