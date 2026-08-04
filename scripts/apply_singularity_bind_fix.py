#!/usr/bin/env python3
"""Apply the final Singularity/Apptainer and four-route acceptance fixes."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text.rstrip() + "\n", encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Unable to patch {label}")
    return text.replace(old, new, 1)


run_sh = read("run.sh")
old_singularity = '''if [[ "${BACKEND}" == "singularity" ]]; then
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
'''
new_singularity = '''if [[ "${BACKEND}" == "singularity" ]]; then
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
    [[ "${BIND_PATH}" != *:* \
      && "${BIND_PATH}" != *,* \
      && ! "${BIND_PATH}" =~ [[:space:]] ]] || \
      die "Singularity bind paths cannot contain whitespace, ',' or ':' characters: ${BIND_PATH}"
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
'''
run_sh = replace_once(
    run_sh, old_singularity, new_singularity,
    "explicit Singularity/Apptainer binds",
)
run_sh = replace_once(
    run_sh,
    '  --include "${INCLUDE}"\n  --exclude "${EXCLUDE}"\n  --dry_run "${DRY_RUN}"\n',
    '  --include "${INCLUDE}"\n  --dry_run "${DRY_RUN}"\n',
    "empty exclude removal",
)
run_sh = replace_once(
    run_sh,
    '[[ -n "${SLIDE_MPP}" ]] && NF_ARGS+=(--slide_mpp "${SLIDE_MPP}")\n',
    '[[ -n "${SLIDE_MPP}" ]] && NF_ARGS+=(--slide_mpp "${SLIDE_MPP}")\n'
    '[[ -n "${EXCLUDE}" ]] && NF_ARGS+=(--exclude "${EXCLUDE}")\n',
    "conditional exclude argument",
)
write("run.sh", run_sh)

cli = read("tumorquantai")
cli = replace_once(
    cli,
    '    resume_parts = [\n        "./tumorquantai", "run", str(input_root), "--output", str(output),\n',
    '    resume_parts = [\n        "tumorquantai", "run", str(input_root), "--output", str(output),\n',
    "global resume command",
)
write("tumorquantai", cli)

installation = read("docs/installation.md")
installation = replace_once(
    installation,
    '''# Optional manual launcher copy.
sudo cp tumorquantai /usr/local/bin/tumorquantai

# Run from the cloned repository so it can record this location.
./tumorquantai install --docker
''',
    '''# Optional manual launcher copy.
sudo cp tumorquantai /usr/local/bin/tumorquantai

# Run from the cloned repository and complete the system installation.
sudo tumorquantai install --docker --system
''',
    "manual system installation",
)
write("docs/installation.md", installation)

runtime_tests = read("tests/test_runtime_backends.py")
addition = '''


def test_singularity_route_binds_every_required_host_path() -> None:
    launcher = (ROOT / "run.sh").read_text(encoding="utf-8")
    assert 'export APPTAINER_BINDPATH=' in launcher
    assert 'export SINGULARITY_BINDPATH=' in launcher
    for variable in (
        "SCRIPT_DIR", "INPUT_DIR", "OUTPUT_DIR", "WORK_DIR",
        "HF_CACHE", "HISTOPLUS_CACHE",
    ):
        assert f'${{{variable}}}:${{{variable}}}' in launcher
    assert "SAMPLE_SHEET_DIR" in launcher
    assert "HISTOPLUS_WEIGHT_DIR" in launcher


def test_empty_exclude_is_not_forwarded_as_a_nextflow_boolean() -> None:
    launcher = (ROOT / "run.sh").read_text(encoding="utf-8")
    base_block = launcher.split("NF_ARGS=(", 1)[1].split(")\n\n", 1)[0]
    assert '--exclude "${EXCLUDE}"' not in base_block
    assert '[[ -n "${EXCLUDE}" ]] && NF_ARGS+=(--exclude "${EXCLUDE}")' in launcher


def test_resume_command_uses_the_installed_command_name() -> None:
    cli = CLI.read_text(encoding="utf-8")
    assert 'resume_parts = [\n        "tumorquantai", "run"' in cli
    assert 'resume_parts = [\n        "./tumorquantai", "run"' not in cli
'''
if "test_singularity_route_binds_every_required_host_path" not in runtime_tests:
    runtime_tests = runtime_tests.rstrip() + addition + "\n"
write("tests/test_runtime_backends.py", runtime_tests)

workflow = read(".github/workflows/quickstart-runtime-routes.yml")
workflow = workflow.replace(
    "name: QuickStart #1 — Docker, Singularity, Poetry, and Conda\n",
    'name: "QuickStart #1 — Docker, Singularity, Poetry, and Conda"\n',
    1,
)
miniforge_start = workflow.index("      - name: Install pinned Miniforge\n")
miniforge_end = workflow.index(
    "      - name: Create the non-biological local test weight\n",
    miniforge_start,
)
miniforge_block = workflow[miniforge_start:miniforge_end]
workflow = workflow[:miniforge_start] + workflow[miniforge_end:]
conda_marker = "      - name: Install and run the Conda route\n"
if conda_marker not in workflow:
    raise SystemExit("Unable to move Miniforge before the Conda route")
workflow = workflow.replace(conda_marker, miniforge_block + conda_marker, 1)

for name, identifier in (
    ("Docker", "docker_route"),
    ("Singularity or Apptainer", "singularity_route"),
    ("Poetry", "poetry_route"),
    ("Conda", "conda_route"),
):
    marker = f"      - name: Install and run the {name} route\n        run: |\n"
    replacement = (
        f"      - name: Install and run the {name} route\n"
        f"        id: {identifier}\n"
        "        continue-on-error: true\n"
        "        run: |\n"
    )
    workflow = replace_once(
        workflow, marker, replacement, f"{name} route outcome capture"
    )

gate = '''      - name: Require all four runtime routes
        if: always()
        run: |
          printf 'Docker: %s\n' "${{ steps.docker_route.outcome }}"
          printf 'Singularity/Apptainer: %s\n' "${{ steps.singularity_route.outcome }}"
          printf 'Poetry: %s\n' "${{ steps.poetry_route.outcome }}"
          printf 'Conda: %s\n' "${{ steps.conda_route.outcome }}"
          test "${{ steps.docker_route.outcome }}" = success
          test "${{ steps.singularity_route.outcome }}" = success
          test "${{ steps.poetry_route.outcome }}" = success
          test "${{ steps.conda_route.outcome }}" = success

'''
upload_marker = "      - name: Upload route reports\n"
workflow = replace_once(
    workflow, upload_marker, gate + upload_marker,
    "four-route final gate",
)
write(".github/workflows/quickstart-runtime-routes.yml", workflow)

print("Applied Singularity binds, argument fix, resume cleanup, tests, and route gate.")
