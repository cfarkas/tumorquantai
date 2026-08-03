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
