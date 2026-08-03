# QuickStart Example 1

The maintained QuickStart is [one public lymphoma WSI](quick_start.md).

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai

# Create the tutorial environment.
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-tutorial.txt

# Set the only path that must be changed.
TQA_ROOT=/path/to/mounted/storage/tumorquantai-quickstart

# Download, verify, convert, and inspect one public WSI without inference.
./tumorquantai quickstart \
  --output "$TQA_ROOT" \
  --cpu \
  --no-inference
```

The preparation step downloads only `TumorQuantAI_LymphomaWSI_022.mds`, validates the public identity and checksums, converts L0/L2, and writes `START_HERE.html` plus a model-free inspection report.

After authorized HistoPLUS access is configured, rerun without `--no-inference` to process a deterministic 1% of detected tissue tiles.

Continue to the [complete QuickStart Example 1](quick_start.md).