#!/usr/bin/env python3
"""Expose the complete public one-slide commands on the repository front page."""

from pathlib import Path

path = Path("README.md")
text = path.read_text(encoding="utf-8")
start = "## QuickStart #1: one public lymphoma WSI\n"
end = "## Four installation and execution methods\n"
if start not in text or end not in text:
    raise SystemExit("Unable to locate the generated README QuickStart section")

section = r'''## QuickStart #1: one public lymphoma WSI

This reproducible example downloads only `TumorQuantAI_LymphomaWSI_022.mds` from [Zenodo record 21466410](https://zenodo.org/records/21466410), verifies the published file, converts image-pyramid levels L0 and L2, and creates a model-free inspection report. HistoPLUS access is required only for inference.

```bash
# Clone TumorQuantAI and install the lightweight public-data tools.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-tutorial.txt

# Create a sibling directory for the public slide, conversion, work, and results.
TQA_RUN="$(dirname "$PWD")/tumorquantai-quickstart-one-wsi"
mkdir -p "$TQA_RUN/download/raw/TumorQuantAI_LymphomaWSI_022"

# Download or resume the public manifest and sample 022.
wget -c -O "$TQA_RUN/download/tumorquantai_lymphoma_mds_manifest.csv" \
  "https://zenodo.org/records/21466410/files/tumorquantai_lymphoma_mds_manifest.csv?download=1"
wget -c -O "$TQA_RUN/download/raw/TumorQuantAI_LymphomaWSI_022/1.mds" \
  "https://zenodo.org/records/21466410/files/TumorQuantAI_LymphomaWSI_022.mds?download=1"

# Verify the manifest, file size, and Secure Hash Algorithm 256-bit checksum.
echo "ad9a9472e8beb302f8b9ba2b3359bacc  $TQA_RUN/download/tumorquantai_lymphoma_mds_manifest.csv" \
  | md5sum -c -
test "$(stat -c %s "$TQA_RUN/download/raw/TumorQuantAI_LymphomaWSI_022/1.mds")" \
  -eq 125350400
echo "db2988b5c6bc791510cec4127106509e604e577feafdb15b94c149043ed7067a  $TQA_RUN/download/raw/TumorQuantAI_LymphomaWSI_022/1.mds" \
  | sha256sum -c -

# Convert exactly sample 022 to level 0 and level 2 Tagged Image File Format files.
python bin/mds_to_tiff.py \
  --input "$TQA_RUN/download/raw" \
  --manifest "$TQA_RUN/download/tumorquantai_lymphoma_mds_manifest.csv" \
  --output-dir "$TQA_RUN/converted" \
  --levels 0 2 \
  --sample-id TumorQuantAI_LymphomaWSI_022 \
  --expected-count 1 \
  --resume

# Inspect the converted slide without loading HistoPLUS.
./tumorquantai inspect "$TQA_RUN/converted" \
  --sample-sheet "$TQA_RUN/converted/samples.csv" \
  --output "$TQA_RUN/inspection" \
  --source-mpp 0.261780

# Verify the public download, conversion, and inspection checkpoint.
python examples/quickstart/verify_outputs.py "$TQA_RUN"
```

The public preparation needs no Zenodo account or HistoPLUS credential. Open `inspection/INSPECTION.html` before inference.

After approved HistoPLUS access is configured, run a deterministic 1% tissue sample through one of the four methods below. For example, Docker on a central processing unit (CPU):

```bash
# Run the one-slide 1% analysis with Docker after model access is ready.
TQA_RUN="$(dirname "$PWD")/tumorquantai-quickstart-one-wsi"
./tumorquantai run "$TQA_RUN/converted" \
  --sample-sheet "$TQA_RUN/converted/samples.csv" \
  --output "$TQA_RUN/smoke-results" \
  --work-dir "$TQA_RUN/work-docker" \
  --preset smoke \
  --source-mpp 0.261780 \
  --docker \
  --cpu

# Verify the required model-free and inference outputs.
python examples/quickstart/verify_outputs.py \
  "$TQA_RUN" \
  --require-inference
```

The smoke run is a software validation, not a whole-slide abundance estimate. See [QuickStart #1](https://cfarkas.github.io/tumorquantai/quick_start/) for Docker, Singularity/Apptainer, Poetry, and Conda commands.

'''
before, remainder = text.split(start, 1)
_, after = remainder.split(end, 1)
path.write_text(before + section + end + after, encoding="utf-8")
