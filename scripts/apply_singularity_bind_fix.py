#!/usr/bin/env python3
"""Pass explicit host bind paths through Nextflow to Apptainer/Singularity."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text.rstrip() + "\n", encoding="utf-8")


def replace_or_verify(
    text: str,
    old: str,
    new: str,
    label: str,
) -> str:
    """Apply one exact replacement, or accept an already-patched file."""
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"Unable to patch {label}")
    return text.replace(old, new, 1)


run_sh = read("run.sh")
run_sh = replace_or_verify(
    run_sh,
    '''WORKER_HISTOPLUS_CACHE="${HISTOPLUS_CACHE}"
DOCKER_RUN_OPTIONS=""
if [[ "${BACKEND}" == "docker" ]]; then
''',
    '''WORKER_HISTOPLUS_CACHE="${HISTOPLUS_CACHE}"
DOCKER_RUN_OPTIONS=""
SINGULARITY_RUN_OPTIONS=""
if [[ "${BACKEND}" == "docker" ]]; then
''',
    "Singularity run-options initialization",
)
run_sh = replace_or_verify(
    run_sh,
    '''  GENERATED_BINDPATH="$(IFS=,; printf '%s' "${SINGULARITY_BIND_SPECS[*]}")"
  EXISTING_APPTAINER_BINDPATH="${APPTAINER_BINDPATH:-}"
  EXISTING_SINGULARITY_BINDPATH="${SINGULARITY_BINDPATH:-}"
  export APPTAINER_BINDPATH="${GENERATED_BINDPATH}${EXISTING_APPTAINER_BINDPATH:+,${EXISTING_APPTAINER_BINDPATH}}"
  export SINGULARITY_BINDPATH="${GENERATED_BINDPATH}${EXISTING_SINGULARITY_BINDPATH:+,${EXISTING_SINGULARITY_BINDPATH}}"
''',
    '''  GENERATED_BINDPATH="$(IFS=,; printf '%s' "${SINGULARITY_BIND_SPECS[*]}")"
  EXISTING_BINDPATH="${APPTAINER_BINDPATH:-${SINGULARITY_BINDPATH:-}}"
  COMBINED_BINDPATH="${GENERATED_BINDPATH}${EXISTING_BINDPATH:+,${EXISTING_BINDPATH}}"
  SINGULARITY_RUN_OPTIONS="--bind ${COMBINED_BINDPATH}"

  # Nextflow may launch Apptainer with a sanitized environment. Pass the bind
  # list through the explicit runtime configuration instead of relying on
  # APPTAINER_BINDPATH or SINGULARITY_BINDPATH being inherited by task shells.
  unset APPTAINER_BINDPATH SINGULARITY_BINDPATH
''',
    "explicit Nextflow Singularity bind options",
)
run_sh = replace_or_verify(
    run_sh,
    '''  -ansi-log false
)

[[ -n "${SLIDE_MPP}" ]] && NF_ARGS+=(--slide_mpp "${SLIDE_MPP}")
''',
    '''  -ansi-log false
)

[[ -n "${SINGULARITY_RUN_OPTIONS}" ]] && \
  NF_ARGS+=("--singularity_run_options=${SINGULARITY_RUN_OPTIONS}")
[[ -n "${SLIDE_MPP}" ]] && NF_ARGS+=(--slide_mpp "${SLIDE_MPP}")
''',
    "Nextflow Singularity run-options argument",
)
write("run.sh", run_sh)


config = read("nextflow.config")
config = replace_or_verify(
    config,
    '''    docker_run_options = ''
    docker_shm_size = '2g'
''',
    '''    docker_run_options = ''
    singularity_run_options = ''
    docker_shm_size = '2g'
''',
    "Singularity run-options parameter",
)
config = replace_or_verify(
    config,
    '''singularity {
    enabled = false
    autoMounts = true
}

apptainer {
    enabled = false
    autoMounts = true
}
''',
    '''singularity {
    enabled = false
    autoMounts = true
    runOptions = params.singularity_run_options
}

apptainer {
    enabled = false
    autoMounts = true
    runOptions = params.singularity_run_options
}
''',
    "global Singularity and Apptainer run options",
)
config = replace_or_verify(
    config,
    '''    singularity_gpu {
        singularity.enabled = true
        singularity.runOptions = '--nv'
''',
    '''    singularity_gpu {
        singularity.enabled = true
        singularity.runOptions = "--nv ${params.singularity_run_options ?: ''}".trim()
''',
    "Singularity GPU run options",
)
config = replace_or_verify(
    config,
    '''    apptainer_gpu {
        apptainer.enabled = true
        apptainer.runOptions = '--nv'
''',
    '''    apptainer_gpu {
        apptainer.enabled = true
        apptainer.runOptions = "--nv ${params.singularity_run_options ?: ''}".trim()
''',
    "Apptainer GPU run options",
)
write("nextflow.config", config)


runtime_tests = read("tests/test_runtime_backends.py")
old_test = '''def test_singularity_route_binds_every_required_host_path() -> None:
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
'''
new_test = '''def test_singularity_route_binds_every_required_host_path() -> None:
    launcher = (ROOT / "run.sh").read_text(encoding="utf-8")
    config = (ROOT / "nextflow.config").read_text(encoding="utf-8")

    assert 'SINGULARITY_RUN_OPTIONS="--bind ${COMBINED_BINDPATH}"' in launcher
    assert 'NF_ARGS+=("--singularity_run_options=${SINGULARITY_RUN_OPTIONS}")' in launcher
    assert 'export APPTAINER_BINDPATH=' not in launcher
    assert 'export SINGULARITY_BINDPATH=' not in launcher
    for variable in (
        "SCRIPT_DIR", "INPUT_DIR", "OUTPUT_DIR", "WORK_DIR",
        "HF_CACHE", "HISTOPLUS_CACHE",
    ):
        assert f'${{{variable}}}:${{{variable}}}' in launcher
    assert "SAMPLE_SHEET_DIR" in launcher
    assert "HISTOPLUS_WEIGHT_DIR" in launcher

    assert "singularity_run_options = ''" in config
    assert config.count("runOptions = params.singularity_run_options") == 2
    gpu_options = 'runOptions = "--nv ${params.singularity_run_options ?: \'\'}".trim()'
    assert config.count(gpu_options) == 2
'''
runtime_tests = replace_or_verify(
    runtime_tests,
    old_test,
    new_test,
    "Singularity explicit-run-options regression test",
)
write("tests/test_runtime_backends.py", runtime_tests)

print(
    "Configured explicit Nextflow --bind options for Singularity/Apptainer "
    "and updated the regression tests."
)
