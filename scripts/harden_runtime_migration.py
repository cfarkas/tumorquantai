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
new = '''prefix = config.split(marker, 1)[0]
if "    conda_environment = " not in prefix:
    prefix = prefix.replace(
        "    docker_shm_size = '2g'\\n",
        "    docker_shm_size = '2g'\\n"
        "    conda_environment = \\\"${projectDir}/environment.yml\\\"\\n",
        1,
    )
runtime_config = r'''process {
'''
if old not in text:
    raise SystemExit("Unable to add the configurable Conda environment path")
text = text.replace(old, new, 1)

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
