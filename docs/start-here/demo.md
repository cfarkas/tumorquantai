# Structural demo

| | |
| --- | --- |
| **For** | Anyone evaluating TumorQuantAI or learning its output layout |
| **Hands-on steps** | Clone, run one command, inspect a local report |
| **Prerequisites** | Linux and Python 3; no GPU, Docker, model weights, account, or internet after cloning |
| **Storage** | A small synthetic result directory; no WSI download or model cache |
| **Writes to** | `tumorquantai-demo/` by default |

!!! warning "Not a biological prediction"
    The demo is a structural software fixture. Its samples, counts, classes,
    failures, and images have no biological or validation meaning.

## Run it

```bash
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
./tumorquantai demo
```

Expected final output includes an absolute path ending in:

```text
TumorQuantAI structural demo complete.
No HistoPLUS inference ran; values have no biological meaning.
Open first: /your/checkout/tumorquantai-demo/START_HERE.html
```

The demo does not contact HistoPLUS, Hugging Face, or Zenodo. It uses bundled
fixtures and a stub worker to exercise the same structural stages used for
slide discovery, sample scattering, failure auditing, aggregation, `status`,
and `report`.

## Inspect the result

Open `tumorquantai-demo/START_HERE.html`. Then compare:

- `aggregated_celltypes/sample_aggregation_audit.csv`: successful and failed
  fixture samples remain explicit;
- `aggregated_celltypes/celltype_counts_by_sample.csv`: only completed fixture
  samples have numeric columns; and
- `tumorquantai_report.json`: machine-readable structural summary.

Run the readers directly:

```bash
./tumorquantai status tumorquantai-demo
./tumorquantai status tumorquantai-demo --json
./tumorquantai report tumorquantai-demo
```

The status output must distinguish a fixture zero from a fixture failure. Do
not interpret either as biology.

## Stop, repeat, and clean up

Press **Ctrl+C** if the demo is interrupted, then repeat
`./tumorquantai demo`. It is safe to rerun. To remove only this demo, first
confirm the exact directory and then delete it:

```bash
test "$PWD/tumorquantai-demo" != "/" &&
  rm -r -- "$PWD/tumorquantai-demo"
```

Do not run a recursive deletion against a variable you have not printed and
checked.

**Next:** prepare a [public one-slide quickstart](public-slide.md), or
[inspect your own slides](own-slides.md) without inference.
