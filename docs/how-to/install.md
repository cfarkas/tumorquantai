# Install and check the computer

The repository installer prepares the `tumorquantai` command, its download/conversion dependencies, pinned Nextflow when needed, and one selected execution route.

## Install once

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai

# Install the command and Docker route.
./tumorquantai install --docker
export PATH="$HOME/.local/bin:$PATH"

# Confirm the command and computer readiness.
tumorquantai --version
tumorquantai doctor
```

Use `--singularity`, `--poetry`, or `--conda` instead of `--docker` when that is the route you will use. Do not create another environment for the tutorials.

## What is checked

Doctor checks the operating system, Java, Nextflow, the selected container or Conda runtime, GPU visibility, writable caches, and configured HistoPLUS access. Add `--online` to check public release, dataset, and model metadata:

```bash
# Include public online metadata checks.
tumorquantai doctor --online
```

## System-wide installation

```bash
# Install the command under /usr/local for all users.
sudo ./tumorquantai install --docker --system

tumorquantai --version
```

## First command

```bash
# Prepare one public WSI without HistoPLUS inference.
tumorquantai quickstart --no-inference
```

**Next:** [configure HistoPLUS access](model-access.md) or continue to the [one-WSI QuickStart](../quick_start.md).
