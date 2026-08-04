# QuickStart Example 1 files

The canonical instructions are in [`docs/quick_start.md`](../../docs/quick_start.md).

```bash
# Clone, install, and prepare the fixed public WSI.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
./tumorquantai install --docker
export PATH="$HOME/.local/bin:$PATH"
tumorquantai quickstart --no-inference

# Verify the default preparation directory.
python3 examples/quickstart/verify_outputs.py --preparation-only
```

After authorized HistoPLUS access is configured, run `tumorquantai quickstart --docker --cpu` and then run the verifier without `--preparation-only`.
