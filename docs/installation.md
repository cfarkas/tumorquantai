# Install TumorQuantAI

TumorQuantAI has two preparation levels:

1. **Public data preparation:** download, checksum validation, MDS-to-TIFF conversion, and model-free inspection.
2. **HistoPLUS inference:** Java, Nextflow, Docker or a prepared local environment, and authorized HistoPLUS access.

The public one-slide tutorial can be prepared before model access is available.

## Requirements

Use Linux with:

- [Git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git)
- [Python 3.10](https://www.python.org/downloads/) or newer
- [Java 17](https://adoptium.net/temurin/releases/?version=17) or newer
- [Nextflow 24.10](https://www.nextflow.io/docs/latest/install.html) or newer
- [Docker Engine](https://docs.docker.com/engine/install/) for the maintained container route
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) only for GPU execution
- `wget` or `curl`, `sha256sum`, `findmnt`, and `df`

HistoPLUS is gated separately. Creating a Hugging Face account or token does not automatically grant model access. Follow [Configure authorized HistoPLUS access](how-to/model-access.md).

## 1. Clone TumorQuantAI

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
```

## 2. Install the tutorial environment

The tutorial environment contains only the host-side download, checksum, MDS conversion, and inspection dependencies.

```bash
# Create and activate the tutorial environment.
python3 -m venv .venv
. .venv/bin/activate

# Install the pinned tutorial requirements.
python -m pip install --upgrade pip
python -m pip install -r requirements-tutorial.txt
```

Repeat `. .venv/bin/activate` after opening a new terminal.

## 3. Install Nextflow

```bash
# Download Nextflow into the current directory.
curl -s https://get.nextflow.io | bash

# Install the executable on the system path.
sudo install -m 0755 nextflow /usr/local/bin/nextflow

# Confirm the installed version.
nextflow -version
```

A system administrator may provide Nextflow through a module or shared software installation instead.

## 4. Check Docker

```bash
# Confirm the Docker client and daemon.
docker --version
docker info
```

For GPU execution, also check:

```bash
# Confirm the NVIDIA host and Docker runtime.
nvidia-smi
docker info --format '{{json .Runtimes}}'
```

Use the CPU route when the GPU is unavailable or reserved by another workload.

## 5. Run the TumorQuantAI doctor

```bash
# Check the local computer without starting inference.
./tumorquantai doctor

# Check an intended storage mount and the public metadata.
./tumorquantai doctor \
  --output /path/to/mounted/storage/tumorquantai-check \
  --online
```

`doctor` never prints a token value. Resolve every `FAIL` relevant to the selected route before inference.

## 6. Check the model-free workflow

```bash
# Run the small structural software demo.
./tumorquantai demo

# Open the generated local report.
python -m webbrowser tumorquantai-demo/START_HERE.html
```

The demo uses synthetic fixtures and has no biological meaning. It confirms discovery, per-sample isolation, failure auditing, aggregation, status, and reporting without Docker, HistoPLUS, or public slide downloads.

## 7. Prepare one real public WSI

```bash
# Set the only path that must be changed.
TQA_ROOT=/path/to/mounted/storage/tumorquantai-quickstart

# Download, verify, convert, and inspect the public WSI without inference.
./tumorquantai quickstart \
  --output "$TQA_ROOT" \
  --cpu \
  --no-inference
```

Continue with [QuickStart Example 1](quick_start.md). The data preparation stage requires no Zenodo credential and does not require HistoPLUS access.

## CPU and GPU selection

| Command option | Use |
| --- | --- |
| `--cpu` | Force the maintained Docker CPU profile |
| `--gpu` | Require a working NVIDIA host and container runtime |
| `--profile auto` | Select GPU only when the host and Docker runtime are visible; otherwise use CPU |
| `--profile local` | Use a separately prepared expert environment without Docker |

The beginner tutorials use explicit `--cpu` or `--gpu` so the selected route is visible in the command and provenance.

## Storage requirements

WSIs are much larger after conversion than their compressed MDS downloads. Keep four budgets separate:

- public MDS downloads;
- converted L0/L2 TIFFs;
- Nextflow work and cache;
- final results.

The one-slide command prints a preflight estimate. The 21-slide tutorial requires much more space; read [Full tutorial](full_tutorial.md) before downloading.

```bash
# Confirm the selected mount, free space, and write access.
TQA_ROOT=/path/to/mounted/storage/tumorquantai-check
mkdir -p "$TQA_ROOT"
findmnt -T "$TQA_ROOT"
df -hT "$TQA_ROOT"
test -w "$TQA_ROOT"
```

## Next steps

- [QuickStart Example 1: one public WSI](quick_start.md)
- [Full 21-slide lymphoma tutorial at 10%](full_tutorial.md)
- [Apply TumorQuantAI to your own WSIs](own_data.md)
- [Troubleshooting](troubleshooting/index.md)