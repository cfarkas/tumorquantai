# QuickStart Example 1

The maintained QuickStart is [one public lymphoma WSI](quick_start.md).

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai

# Install the command once; Docker is shown.
./tumorquantai install --docker
export PATH="$HOME/.local/bin:$PATH"

# Download, verify, convert, and inspect one public WSI without inference.
tumorquantai quickstart --no-inference
```

The installer already contains the public-slide download and conversion dependencies. No tutorial virtual environment or edited output path is needed.

After HistoPLUS access is configured, rerun `tumorquantai quickstart --cpu` to process a deterministic 1% of detected tissue tiles.

Continue to the [complete QuickStart Example 1](quick_start.md).
