# Installation

## Supported execution paths

The recommended path is host Nextflow + Docker. Nextflow runs on the host;
Python, LazySlide, HistoPLUS, and report dependencies run in the image.

The `local` profile is intended for an already prepared environment and is not
an automatic installer.
It defaults to CPU and uses the host path supplied by `--histoplus-cache`; pass
`--device cuda` only in a compatible local GPU environment.

## Host requirements

- Linux
- Java 17 or newer
- Nextflow 24.10 or newer
- Docker 24 or newer
- NVIDIA driver and NVIDIA Container Toolkit for GPU use
- enough storage for input TIFFs, pyramidal conversions, Nextflow work files,
  coordinate tables, and published results

Run:

```bash
./setup_server.sh --check
```

The pinned Nextflow launcher can be installed without root:

```bash
./setup_server.sh --install-nextflow
export PATH="$HOME/.local/bin:$PATH"
```

The helper verifies the official launcher SHA-256. It does not install Docker,
Java, GPU drivers, or modify system packages.

## Container image

By default, `run.sh` selects the published CPU or GPU image by immutable digest.
This makes resume and reruns independent of mutable registry tags. Override it
only with an image you have built or approved.

Use an existing compatible image with `--container-image`, or build explicit
CPU/GPU tags:

```bash
./build_and_push.sh --image myorg/tumorquantai --tag 0.4.0 --flavor both
```

This creates:

```text
myorg/tumorquantai:0.4.0-cpu
myorg/tumorquantai:0.4.0-gpu
```

Select the matching image explicitly:

```bash
./run.sh --input-dir /data/slides --profile gpu \
  --container-image myorg/tumorquantai:0.4.0-gpu
```

Docker runs allocate `2g` of isolated shared memory by default because PyTorch
DataLoader workers can exceed Docker default `/dev/shm` during sampled WSI
inference. Override only with a validated value such as `--shm-size 4g`. If a
restricted host cannot allocate shared memory, use `--num-workers 0` as the
slower fallback.

The Dockerfile pins the LazySlide version, PyTorch family, and exact
`lazyslide-models` Git commit. The gated HistoPLUS runtime download is pinned
separately to commit
`cde2eee81af9e39b03802fc33d4f284733b5ee5e`. The repository, revision,
magnification, and expected weight filename are included in each Nextflow slide
task's cache identity. Use `--histoplus-revision` only for an intentional,
reviewed 40-hex commit override; mutable branch and tag names are rejected.

## Hugging Face authentication

Request model access on Hugging Face, create a read token, and store it with
mode 0600:

```bash
mkdir -p ~/.config/lazyslide-histoplus
printf '%s' "$TOKEN_FROM_A_SECURE_PROMPT" > ~/.config/lazyslide-histoplus/hf_token
chmod 600 ~/.config/lazyslide-histoplus/hf_token
```

`run.sh` exports the value as `HF_TOKEN` and mounts caches. It does not place the
token value in Nextflow parameters or the Python command line.

Docker bind-mount paths containing whitespace or `:` are rejected with an
actionable error because Nextflow Docker run options cannot represent them
reliably; use paths without those characters for input, output, sample sheets,
and caches.

## Local profile

For `-profile local`, install dependencies in Python 3.11 and ensure
`lazyslide`, `lazyslide-models`, `wsidata`, and the packages in
`requirements.txt`/`constraints.txt` are importable. Then run:

```bash
./run.sh --input-dir /data/slides --profile local
```

The bundled `bin/mds_to_tiff.py` reader supports the OLE2 MDS files used by
the privacy-sanitized lymphoma tutorial and requires `olefile`, Pillow, NumPy, and
`tifffile` from `requirements.txt`. Other proprietary slide variants may still
require their vendor reader.

## Storage planning

Keep the output root outside the input root when possible. The workflow prunes
the configured output tree during discovery, but separate roots simplify
read-only input mounts and backups. Nextflow work files can be large; choose a
scratch volume with `--work-dir` and retain it while resume is useful.

Do not run `nextflow clean -f` until published outputs and audit tables have
been verified.
