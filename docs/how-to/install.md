# Install and check the computer

| | |
| --- | --- |
| **For** | Users preparing a Linux host for TumorQuantAI |
| **Hands-on steps** | Clone, run offline doctor, install only missing prerequisites, rerun |
| **Prerequisites** | Linux shell and permission to use the selected output mount |
| **Download/storage** | Doctor is offline by default; containers/models are downloaded only for real runs |
| **Writes to** | A temporary writable-path probe and, only when requested, redacted JSON |

The recommended inference path is Nextflow on the host plus Docker. Python,
LazySlide, HistoPLUS, and image dependencies run inside the pinned container.

## Check before installing

```bash
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai

./tumorquantai doctor \
  --output /mounted/storage/tumorquantai-check
```

Doctor always checks OS/architecture, Java/Nextflow, Docker CLI and daemon
access, NVIDIA visibility, CPU fallback, caches, and configured model
readiness. With `--output` and optional `--work-dir`, it also checks the
selected output/work mount and free space; `--input` checks the chosen input.
It does not require internet unless `--online` is supplied.

Expected output is a compact `PASS`/`WARN`/`FAIL` table with one next action
per failure. Exit 0 means no blocking failure; see the [exit-code
reference](../reference/exit-codes.md).

## Minimum real-run components

- Linux;
- Java 17 or newer;
- Nextflow 24.10 or newer;
- Docker 24 or newer, or a fully prepared local Python environment;
- NVIDIA driver and NVIDIA Container Toolkit for GPU execution; and
- enough verified mounted storage for input, conversion, work, result, and
  cache categories.

The repository helper can install its verified Nextflow launcher without root:

```bash
./setup_server.sh --install-nextflow
export PATH="$HOME/.local/bin:$PATH"
```

It does not install Java, Docker, GPU drivers, or modify system packages.

## Lightweight public-slide host environment

The public MDS downloader/converter runs on the host before inference. Use
Python 3.10 or newer and install only its small declared environment:

```bash
python3 -m venv .venv-tumorquantai-tutorial
. .venv-tumorquantai-tutorial/bin/activate
python -m pip install -r requirements-tutorial.txt
./tumorquantai quickstart --output /mounted/storage/tutorial-one-slide --dry-run
```

Keep this small environment in the checkout only if the checkout itself is on
an approved filesystem. It contains software packages, never slides, model
weights, tokens, work files, or results.

## Redacted issue attachment

```bash
./tumorquantai doctor \
  --output /mounted/storage/tumorquantai-check \
  --json > doctor.json
```

Review `doctor.json` before sharing. It excludes secret contents and minimizes
personally identifying paths, but you remain responsible for redaction.

## Stop and clean up

Doctor is read-only apart from its small writable-path probe. Press **Ctrl+C**
to stop. Remove only the explicitly selected check directory if it was created.

**Next:** [configure authorized HistoPLUS access](model-access.md) or run the
[structural demo](../start-here/demo.md).
