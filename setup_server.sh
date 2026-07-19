#!/usr/bin/env bash
set -Eeuo pipefail

NEXTFLOW_VERSION="${NEXTFLOW_VERSION:-25.10.2}"
NEXTFLOW_SHA256="${NEXTFLOW_SHA256:-60aff30ad532030657296ca1fa72e37befda236bfd4fc7358a3cabf5e7589dd7}"
INSTALL_DIR="${INSTALL_DIR:-${HOME}/.local/bin}"
export PATH="${INSTALL_DIR}:${PATH}"
INSTALL_NEXTFLOW="false"

usage() {
  cat <<'USAGE'
Usage: ./setup_server.sh [--check] [--install-nextflow]

Checks Docker, Java, Nextflow, GPU visibility, and writable cache paths.
--install-nextflow installs the pinned official launcher in ~/.local/bin.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) shift ;;
    --install-nextflow) INSTALL_NEXTFLOW="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'ERROR: unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
done

if [[ "${INSTALL_NEXTFLOW}" == "true" ]]; then
  command -v curl >/dev/null 2>&1 || { echo 'ERROR: curl is required' >&2; exit 2; }
  mkdir -p "${INSTALL_DIR}"
  tmp="$(mktemp)"
  trap 'rm -f "${tmp}"' EXIT
  curl -fsSL \
    "https://github.com/nextflow-io/nextflow/releases/download/v${NEXTFLOW_VERSION}/nextflow" \
    -o "${tmp}"
  printf '%s  %s\n' "${NEXTFLOW_SHA256}" "${tmp}" | sha256sum --check --status || {
    echo 'ERROR: Nextflow launcher checksum mismatch' >&2
    exit 2
  }
  install -m 0755 "${tmp}" "${INSTALL_DIR}/nextflow"
  printf 'Installed Nextflow launcher: %s\n' "${INSTALL_DIR}/nextflow"
fi

failures=0
check_command() {
  local name="$1"
  if command -v "${name}" >/dev/null 2>&1; then
    printf 'OK   %-12s %s\n' "${name}" "$(command -v "${name}")"
  else
    printf 'MISS %-12s\n' "${name}"
    failures=$((failures + 1))
  fi
}

check_command java
check_command nextflow
check_command docker

if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    echo 'OK   docker daemon'
  else
    echo 'MISS docker daemon access'
    failures=$((failures + 1))
  fi
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  echo 'OK   NVIDIA GPU detected'
  nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true
else
  echo 'INFO no NVIDIA GPU detected; use the CPU profile'
fi

mkdir -p "${HOME}/.cache/lazyslide-histoplus/huggingface" \
  "${HOME}/.cache/lazyslide-histoplus/histoplus"
echo 'OK   cache directories'

if (( failures > 0 )); then
  printf 'Doctor found %d missing prerequisite(s).\n' "${failures}" >&2
  exit 1
fi
echo 'Doctor: OK'
