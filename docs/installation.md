# Install TumorQuantAI

TumorQuantAI includes a self-installing command. Start from a fresh clone and choose one route.

## 1. Clone the repository

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
```

## 2. Choose one installation method

### Installation and execution through Docker

Install Docker Engine first, then run:

```bash
# Install the global command and validate Docker.
./tumorquantai install --docker

# Make the user-level command available now.
export PATH="$HOME/.local/bin:$PATH"

# Confirm the installed command and selected default backend.
tumorquantai --version
tumorquantai doctor
```

### Installation and execution through Singularity or Apptainer

Install Apptainer or Singularity first, then run:

```bash
# Install the global command and validate Singularity or Apptainer.
./tumorquantai install --singularity

# Make the user-level command available now.
export PATH="$HOME/.local/bin:$PATH"

# Confirm the installed command.
tumorquantai --version
```

### Installation through Poetry

This route creates an in-repository Poetry environment and installs the same global `tumorquantai` command. Docker is the default scientific backend; another backend can still be selected at execution time.

```bash
# Install Poetry in an isolated tool environment and install TumorQuantAI.
./tumorquantai install --poetry

# Make the user-level command available now.
export PATH="$HOME/.local/bin:$PATH"

# Confirm the installed command.
tumorquantai --version
```

### Installation and execution through Conda

Install Miniforge or Conda first, then run:

```bash
# Install the global command and validate Conda.
./tumorquantai install --conda

# Make the user-level command available now.
export PATH="$HOME/.local/bin:$PATH"

# Confirm the installed command.
tumorquantai --version
```

## What the installer changes

The default user installation writes only to:

```text
~/.local/bin/tumorquantai
~/.local/bin/nextflow              # only when Nextflow was absent
~/.local/share/tumorquantai/
~/.config/tumorquantai/repository
~/.config/tumorquantai/backend
```

It creates an isolated host-side Python environment for download, MDS conversion, and inspection. It records the cloned repository location so the command continues to work from any directory. The selected backend becomes the default, while `--docker`, `--singularity`, or `--conda` can override it for an individual run.

The installer validates system prerequisites but does not silently add operating-system repositories or invoke `sudo`. Follow the displayed official link when Docker, Apptainer/Singularity, Conda, or Java is missing.

## System-wide installation

```bash
# Install under /usr/local and /etc for all users.
sudo ./tumorquantai install --docker --system

# Confirm the system command.
tumorquantai --version
```

Replace `--docker` with `--singularity`, `--poetry`, or `--conda` as needed.

A manual copy also works when it is made from the clone and followed by the installer, because the command records the repository location:

```bash
# Optional manual launcher copy.
sudo cp tumorquantai /usr/local/bin/tumorquantai

# Run from the cloned repository so it can record this location.
./tumorquantai install --docker
```

The built-in `--system` method is preferred because it also creates the managed Python environment and records the backend.

## Nextflow and Java

When `nextflow` is absent, the installer downloads pinned Nextflow `25.10.2` and verifies its SHA-256 checksum. Java 17 or newer is still required. Disable the download only when Nextflow is supplied by a module or administrator:

```bash
# Keep the external Nextflow installation unchanged.
./tumorquantai install --docker --no-nextflow-download
```

## First command

```bash
# Prepare one public WSI without model inference or an edited output path.
tumorquantai quickstart --no-inference
```

Continue with [QuickStart Example 1](quick_start.md).
