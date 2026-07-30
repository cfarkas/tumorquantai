# Tutorial: one public slide at 1%

| | |
| --- | --- |
| **For** | Researchers reviewing the first real WSI workflow and outputs |
| **Hands-on steps** | Plan, prepare alias 022, optionally infer 1%, inspect four files |
| **Prerequisites** | Verified mounted storage; HistoPLUS access plus Java/Nextflow/Docker only for inference |
| **Download** | One 125,350,400-byte MDS plus a small manifest |
| **Storage** | Conversion and work need more than the download; use the command's per-category preflight estimate |
| **Writes to** | `/mounted/storage/tqa-022/` in this example |

This tutorial uses public Zenodo record `21466410`, DOI
`10.5281/zenodo.21466410`, and the dataset-matched engine release `v0.4.0`.
It contains no pathologist ground truth.

## Prepare and inspect

```bash
export TQA_ONE=/mounted/storage/tqa-022

./tumorquantai quickstart --output "$TQA_ONE" --dry-run
./tumorquantai quickstart --output "$TQA_ONE" --no-inference
```

Preparation verifies:

- `TumorQuantAI_LymphomaWSI_022.mds` is exactly `125350400` bytes;
- MD5 `94bb5b08ccf1957f8c42a579e8b33cfb` and SHA-256
  `db2988b5c6bc791510cec4127106509e604e577feafdb15b94c149043ed7067a`
  agree with the authoritative manifest from record 21466410;
- conversion is limited to L0 and L2 and has resumable state; and
- manifest source MPP is `0.261780`.

Expected success is a readiness message and `$TQA_ONE/START_HERE.html`. No
Zenodo token is used.

## Optional authorized 1% run

After [HistoPLUS access](../how-to/model-access.md) is configured:

```bash
./tumorquantai quickstart --output "$TQA_ONE"
```

The smoke preset uses one selected slide, 1% of tissue tiles, a recorded random
seed, fail-fast behavior, conservative resources, and a work directory on the
same selected filesystem. It requires exactly one included and zero excluded
samples after aggregation.

## Review in this order

1. `START_HERE.html` — confirm PASS/WARN/FAIL cards and run identity.
2. `smoke-results/TumorQuantAI_LymphomaWSI_022/overlays/celltypes_overview_and_zoom.png` —
   review orientation, selected region, and visual alignment.
3. `smoke-results/TumorQuantAI_LymphomaWSI_022/summary/summary.json` — verify source MPP,
   target MPP, 1% sampling, seed, model revision, and completion.
4. `smoke-results/aggregated_celltypes/sample_aggregation_audit.csv` — require one included
   sample and no failed/incomplete sample.

The raw counts are detections in sampled tiles, not whole-slide counts. Do not
multiply them by 100.

## Stop, resume, and clean up

Press **Ctrl+C**, then repeat the same quickstart command to resume. Use
`./tumorquantai status "$TQA_ONE"` for the exact resume command and log. Keep
the work directory until review is complete. To clean up, print and verify
`TQA_ONE` and remove only that root; never clean an entire mount.

**Next:** use the [four-slide 10% tutorial](four-public-slides.md) only after
the one-slide audit and overlay pass review.
