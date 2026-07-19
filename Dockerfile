# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.11-slim-bookworm@sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba
FROM ${PYTHON_IMAGE}

ARG FLAVOR=cpu
ARG TORCH_CUDA=cu124
ARG TORCH_VERSION=2.6.0
ARG TORCHVISION_VERSION=0.21.0
ARG TORCHAUDIO_VERSION=2.6.0
ARG LAZYSLIDE_VERSION=0.10.1
ARG LAZYSLIDE_MODELS_REF=0127beb5ff7989005f0eff7b481a95b989c4187f
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="TumorQuantAI" \
      org.opencontainers.image.description="TumorQuantAI whole-slide inference and cohort reporting tools" \
      org.opencontainers.image.source="https://github.com/cfarkas/tumorquantai" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg \
    HOME=/home/lazyslide \
    HF_HOME=/home/lazyslide/.cache/huggingface \
    HUGGINGFACE_HUB_CACHE=/home/lazyslide/.cache/huggingface/hub

RUN apt-get update && apt-get install -y --no-install-recommends \
      bash ca-certificates curl git tini build-essential pkg-config procps \
      libgl1 libglib2.0-0 libgomp1 libjpeg62-turbo libtiff6 \
      libopenslide0 openslide-tools libvips42 libvips-tools \
    && rm -rf /var/lib/apt/lists/*

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade pip setuptools wheel

RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "${FLAVOR}" = "gpu" ]; then \
      python -m pip install --index-url "https://download.pytorch.org/whl/${TORCH_CUDA}" \
        "torch==${TORCH_VERSION}" "torchvision==${TORCHVISION_VERSION}" "torchaudio==${TORCHAUDIO_VERSION}"; \
    else \
      python -m pip install --index-url https://download.pytorch.org/whl/cpu \
        "torch==${TORCH_VERSION}" "torchvision==${TORCHVISION_VERSION}" "torchaudio==${TORCHAUDIO_VERSION}"; \
    fi

COPY requirements.txt constraints.txt /tmp/
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --constraint /tmp/constraints.txt \
      "git+https://github.com/rendeirolab/lazyslide-models.git@${LAZYSLIDE_MODELS_REF}" \
    && python -m pip install --constraint /tmp/constraints.txt \
      "lazyslide==${LAZYSLIDE_VERSION}" \
    && python -m pip install --constraint /tmp/constraints.txt -r /tmp/requirements.txt \
    && python -m pip check

RUN useradd --create-home --shell /bin/bash lazyslide \
    && mkdir -p /opt/lazyslide/bin \
      /home/lazyslide/.cache/huggingface \
      /home/lazyslide/.cache/histoplus \
    && chown -R lazyslide:lazyslide /opt/lazyslide /home/lazyslide

COPY --chown=lazyslide:lazyslide lazyslide_histoplus_wsi_celltype.py /opt/lazyslide/
COPY --chown=lazyslide:lazyslide bin/ /opt/lazyslide/bin/
RUN chmod +x /opt/lazyslide/lazyslide_histoplus_wsi_celltype.py /opt/lazyslide/bin/*.py \
    && python -m py_compile /opt/lazyslide/lazyslide_histoplus_wsi_celltype.py /opt/lazyslide/bin/*.py \
    && python - <<'PY'
from wsidata import open_wsi
import lazyslide as zs
try:
    from lazyslide.models import list_models
except Exception:
    from lazyslide_models import list_models
try:
    models = set(list_models(task="segmentation"))
except TypeError:
    models = set(list_models("segmentation"))
assert "histoplus" in models, f"HistoPLUS is not registered: {sorted(models)}"
print("LazySlide:", getattr(zs, "__version__", "unknown"))
print("HistoPLUS registration: OK")
PY

USER lazyslide
WORKDIR /work
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "/opt/lazyslide/lazyslide_histoplus_wsi_celltype.py", "--help"]
