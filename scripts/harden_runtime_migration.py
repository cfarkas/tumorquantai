#!/usr/bin/env python3
"""Harden the temporary runtime migration before it is applied."""

from pathlib import Path

path = Path(__file__).with_name("apply_oncotracer_runtime.py")
text = path.read_text(encoding="utf-8")

old = "  - pip>=24\n  - pytorch=2.6.0\n"
new = "  - pip>=24\n  - git\n  - pytorch=2.6.0\n"
if old not in text:
    raise SystemExit("Unable to add Git to the versioned Conda environment")
text = text.replace(old, new, 1)

old = "prefix = config.split(marker, 1)[0]\nruntime_config = r'''process {\n"
new = """prefix = config.split(marker, 1)[0]
if "    conda_environment = " not in prefix:
    prefix = prefix.replace(
        "    docker_shm_size = '2g'\\n",
        "    docker_shm_size = '2g'\\n"
        "    conda_environment = \\\"${projectDir}/environment.yml\\\"\\n",
        1,
    )
runtime_config = r'''process {
"""
if old not in text:
    raise SystemExit("Unable to add the configurable Conda environment path")
text = text.replace(old, new, 1)

# A quoted pipe-separated name is ambiguous across Nextflow releases. Use an
# explicit regular-expression selector so every scientific process receives
# the selected container or Conda environment.
old = "            withName: 'DISCOVER_SLIDES|PROCESS_SLIDE|AGGREGATE_COUNTS' {\n"
new = "            withName: /DISCOVER_SLIDES|PROCESS_SLIDE|AGGREGATE_COUNTS/ {\n"
if old not in text:
    raise SystemExit("Unable to convert runtime process selectors to regexes")
text = text.replace(old, new)

old = '                conda = "${projectDir}/environment.yml"\n'
new = '                conda = params.conda_environment\n'
if old not in text:
    raise SystemExit("Unable to make the Conda environment path configurable")
text = text.replace(old, new, 1)

marker = "# ---------------------------------------------------------------------------\n# Poetry launcher\n# ---------------------------------------------------------------------------\n"
addition = '''write(
    "environment-ci.yml",
    """name: tumorquantai-runtime-ci
channels:
  - conda-forge
dependencies:
  - python=3.11
  - pandas>=2.2,<3
  - pyyaml>=6,<7
""",
)

'''
if marker not in text:
    raise SystemExit("Unable to add the lightweight Conda route-test environment")
text = text.replace(marker, addition + marker, 1)

# The run parser stores profile options in an argparse argument group named
# `execution`, while QuickStart stores them directly on its parser.
if "add_execution_profile_options(run)" not in text:
    raise SystemExit("Unable to repair the run parser backend insertion")
text = text.replace("add_execution_profile_options(run)", "add_execution_profile_options(execution)")
text = text.replace("add_execution_backend_options(run)", "add_execution_backend_options(execution)")

# The migration adds backend explicitly to the QuickStart run namespace and
# then updates the remaining function calls. Avoid adding it twice.
old = r"r'profile=args\.profile(?=\s*[,\)])',"
new = r"r'profile=args\.profile(?!\s*,\s*backend=)(?=\s*[,\)])',"
if old not in text:
    raise SystemExit("Unable to harden the QuickStart backend call replacement")
text = text.replace(old, new, 1)

old = "    assert 'conda = \"${projectDir}/environment.yml\"' in config\n"
new = (
    '    assert "conda = params.conda_environment" in config\n'
    '    assert "conda_environment" in config\n'
    '    assert "withName: /DISCOVER_SLIDES|PROCESS_SLIDE|AGGREGATE_COUNTS/" in config\n'
)
if old not in text:
    raise SystemExit("Unable to update the runtime-profile Conda assertion")
text = text.replace(old, new, 1)

old = '''if [[ -z "${CONTAINER_IMAGE}" && ( "${BACKEND}" == "docker" || "${BACKEND}" == "singularity" ) ]]; then
  if [[ "${PROFILE}" == "gpu" ]]; then
    CONTAINER_IMAGE="carlosfarkas/lazyslide-histoplus@sha256:c4b02485d4549a56348cd09995ce0788a6acc8a3e1e600e986b644231a95bd25"
  else
    CONTAINER_IMAGE="carlosfarkas/lazyslide-histoplus@sha256:413bed6b55bc86923321c61453c18ece678da3c125ae44dcbd5f6c3bce7115d4"
  fi
fi
'''
new = old + '''
if [[ "${BACKEND}" == "singularity" \
  && "${CONTAINER_IMAGE}" != *://* \
  && "${CONTAINER_IMAGE}" != /* \
  && "${CONTAINER_IMAGE}" != *.sif ]]; then
  CONTAINER_IMAGE="docker://${CONTAINER_IMAGE}"
fi
'''
if old not in text:
    raise SystemExit("Unable to add the docker:// scheme for Singularity/Apptainer")
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
