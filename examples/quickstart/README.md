# QuickStart Example 1 files

The maintained one-slide tutorial is [`docs/quick_start.md`](../../docs/quick_start.md).

It uses fixed public sample `TumorQuantAI_LymphomaWSI_022` from Zenodo record `21466410`:

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

# Prepare the public WSI without HistoPLUS inference.
./tumorquantai quickstart \
  --output "$TQA_ROOT" \
  --cpu \
  --no-inference
```

After authorized model access is ready:

```bash
# Run the fixed one-slide 1% smoke analysis.
./tumorquantai quickstart \
  --output "$TQA_ROOT" \
  --cpu

# Verify the required output structure and audit.
python3 examples/quickstart/verify_outputs.py \
  --tutorial-root "$TQA_ROOT"
```

The verifier requires one included sample, `percent_slide=1`, a nonempty overlay, summary, coordinates, class counts, aggregation audit, and cohort count/fraction matrices.