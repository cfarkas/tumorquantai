#!/usr/bin/env bash
set -Eeuo pipefail

ROUTE="${1:?usage: tests/run_quickstart_runtime_route.sh ROUTE}"
: "${TQA_ROOT:?TQA_ROOT is required}"
: "${ROUTES_ROOT:?ROUTES_ROOT is required}"
: "${SAMPLE:?SAMPLE is required}"
: "${STUB_WEIGHT:?STUB_WEIGHT is required}"
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"

PREFIX="${RUNNER_TEMP}/install-${ROUTE}"
OUTPUT="${ROUTES_ROOT}/${ROUTE}-results"
WORK="${ROUTES_ROOT}/${ROUTE}-work"
CACHE="${ROUTES_ROOT}/${ROUTE}-cache"
INSTALL_FLAG=""
BACKEND_FLAG=""
EXPECTED_BACKEND=""
CONTAINER_ARGUMENTS=()
EXPERT_ARGUMENTS=(
  --worker_script "${PWD}/tests/fixtures/stub_worker.py"
)

case "${ROUTE}" in
  docker)
    : "${DOCKER_IMAGE:?DOCKER_IMAGE is required for Docker}"
    INSTALL_FLAG="--docker"
    BACKEND_FLAG="--docker"
    EXPECTED_BACKEND="docker"
    CONTAINER_ARGUMENTS=(--container-image "${DOCKER_IMAGE}")
    ;;
  singularity)
    : "${SIF_PATH:?SIF_PATH is required for Singularity}"
    INSTALL_FLAG="--singularity"
    BACKEND_FLAG="--singularity"
    EXPECTED_BACKEND="singularity"
    CONTAINER_ARGUMENTS=(--container-image "${SIF_PATH}")
    ;;
  poetry)
    : "${DOCKER_IMAGE:?DOCKER_IMAGE is required for Poetry}"
    INSTALL_FLAG="--poetry"
    BACKEND_FLAG="--docker"
    EXPECTED_BACKEND="docker"
    CONTAINER_ARGUMENTS=(--container-image "${DOCKER_IMAGE}")
    ;;
  conda)
    INSTALL_FLAG="--conda"
    BACKEND_FLAG="--conda"
    EXPECTED_BACKEND="conda"
    EXPERT_ARGUMENTS+=(--conda_environment "${PWD}/environment-ci.yml")
    ;;
  *)
    printf 'ERROR: unsupported route: %s\n' "${ROUTE}" >&2
    exit 2
    ;;
esac

rm -rf "${PREFIX}" "${OUTPUT}" "${WORK}" "${CACHE}"
mkdir -p "${ROUTES_ROOT}"

./tumorquantai install \
  "${INSTALL_FLAG}" \
  --prefix "${PREFIX}" \
  --no-nextflow-download

"${PREFIX}/bin/tumorquantai" run "${TQA_ROOT}/converted" \
  --sample-sheet "${TQA_ROOT}/converted/samples.csv" \
  --output "${OUTPUT}" \
  --work-dir "${WORK}" \
  --cache-dir "${CACHE}" \
  --preset smoke \
  --sample "${SAMPLE}" \
  --source-mpp 0.261780 \
  --local-weight "${STUB_WEIGHT}" \
  "${CONTAINER_ARGUMENTS[@]}" \
  "${BACKEND_FLAG}" \
  --cpu \
  --cpus 2 \
  --memory '4 GB' \
  --num-workers 0 \
  --celltypes-batch-size 1 \
  --no-convert-to-pyramidal \
  --fail-fast \
  -- \
  "${EXPERT_ARGUMENTS[@]}"

python - "${OUTPUT}" "${EXPECTED_BACKEND}" "${SAMPLE}" "${ROUTE}" <<'PY'
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
expected_backend = sys.argv[2]
sample = sys.argv[3]
route = sys.argv[4]
required = (
    root / "START_HERE.html",
    root / sample / "summary/summary.json",
    root / sample / "cell_types/class_counts.csv",
    root / "aggregated_celltypes/sample_aggregation_audit.csv",
    root / "aggregated_celltypes/celltype_counts_by_sample.csv",
    root / "workflow_metadata/tumorquantai_run.json",
)
for path in required:
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"FAIL [{route}]: missing or empty output: {path}")

manifest = json.loads(required[-1].read_text(encoding="utf-8"))
if manifest.get("completion_status") != "complete":
    raise SystemExit(f"FAIL [{route}]: incomplete run manifest: {manifest}")
if manifest.get("execution_backend") != expected_backend:
    raise SystemExit(
        f"FAIL [{route}]: expected backend {expected_backend!r}, "
        f"observed {manifest.get('execution_backend')!r}"
    )
if float(manifest.get("sampling_percent", -1)) != 1.0:
    raise SystemExit(f"FAIL [{route}]: sampling percent is not 1.0")

with required[3].open(newline="", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle))
matching = [row for row in rows if row.get("sample_id") == sample]
if len(matching) != 1:
    raise SystemExit(f"FAIL [{route}]: audit does not contain exactly one sample row")
if str(matching[0].get("included", "")).lower() not in {"true", "1", "yes"}:
    raise SystemExit(f"FAIL [{route}]: sample is not included: {matching[0]}")

print(f"PASS: {route} completed the real one-WSI path for {sample}")
PY
