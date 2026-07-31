# Public one-slide quickstart

| | |
| --- | --- |
| **For** | A first real-WSI preparation and optional 1% inference check |
| **Hands-on steps** | Preflight, download one file, verify, convert L0/L2, inspect, optionally infer |
| **Prerequisites** | Linux, Python 3.10+ with `requirements-tutorial.txt`, ample space on a verified mounted filesystem; Java/Nextflow/Docker and authorized HistoPLUS access only for inference |
| **Download** | Exactly 125,350,400 bytes plus the small authoritative manifest |
| **Storage** | Budget download, L0/L2 conversion, Nextflow work, and results separately; check the plan printed by the command |
| **Writes to** | The path supplied with `--output`; work stays associated with that filesystem |

This route uses public [Zenodo record
21466410](https://zenodo.org/records/21466410), DOI
[`10.5281/zenodo.21466410`](https://doi.org/10.5281/zenodo.21466410), matched
to software `v0.4.0`.

| Fixed item | Value |
| --- | --- |
| Sample | `TumorQuantAI_LymphomaWSI_022` |
| File | `TumorQuantAI_LymphomaWSI_022.mds` |
| Size | `125350400` bytes |
| MD5 | `94bb5b08ccf1957f8c42a579e8b33cfb` |
| SHA-256 | `db2988b5c6bc791510cec4127106509e604e577feafdb15b94c149043ed7067a` |
| Source MPP | `0.261780` µm/pixel |
| Conversion levels | L0 and L2 |
| L0 dimensions | 37,888 × 26,112 pixels |
| L2 dimensions | 9,728 × 6,656 pixels |
| Smoke sampling | Seeded 1% |

No Zenodo token is needed. HistoPLUS remains gated separately.

## 1. Check the plan and mount

Choose an output on a mounted storage filesystem, not inside the repository:

```bash
export TQA_TUTORIAL=/mounted/storage/tumorquantai-one-slide

mkdir -p "$TQA_TUTORIAL"
findmnt -T "$TQA_TUTORIAL"
df -hT "$TQA_TUTORIAL"
test -w "$TQA_TUTORIAL"
./tumorquantai quickstart --output "$TQA_TUTORIAL" --cpu --dry-run
```

If the host dependencies are missing, follow [Install and check the
computer](../how-to/install.md). The command checks these dependencies before
making a network request.

The dry run prints distinct estimates for the MDS download, converted TIFFs,
work cache, and final results. Resolve any `FAIL` before continuing.

## 2. Prepare the slide without inference

```bash
./tumorquantai quickstart \
  --output "$TQA_TUTORIAL" \
  --no-inference
```

The command fetches the authoritative 10,108-byte manifest from the same
version-specific record, downloads only alias 022 with resume support, and
verifies file size, MD5, SHA-256, manifest identity, and safe paths. Conversion
writes only L0/L2 and keeps resumable state. Inspection confirms source MPP
`0.261780`.

Expected completion when model access is absent or inference is disabled:

```text
One-slide data preparation and model-free inspection complete.
Open first: /mounted/storage/tumorquantai-one-slide/START_HERE.html
```

Missing gated access is a readiness state, not corrupted data.
Without `--no-inference`, an otherwise ready preparation with no authorized
model prints `Data preparation is complete. Authorized HistoPLUS access is not
configured; the data are not corrupt.` and exits successfully.

The bounded output remains separated:

```text
tumorquantai-one-slide/
├── download/                    # public manifest and alias 022 only
├── converted/                   # verified L0/L2 and conversion state
├── inspection/                  # model-free manifest and INSPECTION.html
├── smoke-results/               # appears after authorized inference
├── .tumorquantai-work/          # resumable Nextflow work
├── tumorquantai_report.json
└── START_HERE.html
```

## 3. Continue when HistoPLUS access is authorized

Follow [Configure authorized HistoPLUS access](../how-to/model-access.md), then
rerun the same command:

```bash
./tumorquantai quickstart --output "$TQA_TUTORIAL" --cpu
```

Use `--cpu` when the GPU is unavailable or reserved by another workload. Use
`--gpu` only when `doctor` confirms the NVIDIA host and container path. These
flags are mutually exclusive aliases for the compatible `--profile cpu` and
`--profile gpu` forms.

The prepared files are verified and reused. The inference stage selects exactly
one slide, uses a seeded 1% tissue-tile sample, and fails fast. After inference,
the command requires exactly one included sample and zero excluded samples in
`smoke-results/aggregated_celltypes/sample_aggregation_audit.csv`.

Open the printed `START_HERE.html` and review the overlay, source/target MPP,
sampling percentage and seed before treating the smoke run as technically
successful. This is not clinical or biological validation.

## Stop, resume, and clean up

Press **Ctrl+C** to stop. Repeat the identical command with the same output to
resume downloads, conversion, and valid Nextflow tasks. For stage control:

```bash
./tumorquantai quickstart --output "$TQA_TUTORIAL" --download-only
./tumorquantai quickstart --output "$TQA_TUTORIAL" --convert-only
./tumorquantai quickstart --output "$TQA_TUTORIAL" --no-inference
```

To clean up, print and verify `TQA_TUTORIAL`, then remove only that tutorial
root. Keep the work directory while resume is useful. Never run
`nextflow clean -f` before verifying and backing up results.

**Next:** [understand the one-slide outputs](../tutorials/one-public-slide.md)
or [inspect your own slide](own-slides.md).
