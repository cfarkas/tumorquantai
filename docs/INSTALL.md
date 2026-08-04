# Installation

Use the maintained [installation guide](installation.md).

```bash
# Clone, install, and check TumorQuantAI.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
./tumorquantai install --docker
export PATH="$HOME/.local/bin:$PATH"
tumorquantai doctor
```

Replace `--docker` with `--singularity`, `--poetry`, or `--conda` when needed. The installer includes the tutorial download and conversion dependencies.

Authorized model setup is separate: [Configure HistoPLUS access](how-to/model-access.md).
