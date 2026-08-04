# Review one public WSI at 1%

Complete [QuickStart Example 1](../quick_start.md), including the optional authorized inference stage, before using this review checklist.

## 1. Open the top-level report

```bash
# Set the tutorial root used by QuickStart Example 1.
TQA_ROOT="$(dirname "$PWD")/tumorquantai-quickstart-one-wsi"

# Regenerate and open the portable report.
tumorquantai report "$TQA_ROOT/smoke-results"
```

Open `$TQA_ROOT/START_HERE.html` and `$TQA_ROOT/smoke-results/START_HERE.html`. Confirm the fixed public sample, 1% preset, recorded seed, source MPP, and completion state.

## 2. Review the overlay

Open:

```text
smoke-results/TumorQuantAI_LymphomaWSI_022/overlays/celltypes_overview_and_zoom.png
```

Check slide orientation, selected tissue, visual alignment, artifacts, and marker placement. HistoPLUS classes are predictions, not pathologist ground truth.

## 3. Review scale and sampling

Open:

```text
smoke-results/TumorQuantAI_LymphomaWSI_022/summary/summary.json
```

Confirm:

- source MPP is `0.261780`;
- target/model MPP is recorded separately;
- sampling is 1% of detected tissue tiles;
- the random seed is recorded;
- model revision, weight identity, container, and software identity are present;
- the sample completed successfully.

Counts from this run describe sampled tissue tiles and must not be multiplied by 100.

## 4. Review per-slide counts

Open:

```text
smoke-results/TumorQuantAI_LymphomaWSI_022/cell_types/class_counts.csv
```

A class count of zero is interpretable only because the sample completed. Review the overlay before treating any class difference as biological.

## 5. Review the aggregation audit

Open:

```text
smoke-results/aggregated_celltypes/sample_aggregation_audit.csv
```

Require exactly one included sample and no failed, incomplete, pending, or excluded sample.

## 6. Run the verifier

```bash
# Verify the one-slide output structure and sampling metadata.
python3 examples/quickstart/verify_outputs.py \
  --tutorial-root "$TQA_ROOT"
```

Continue to [the full 21-slide tutorial at 10%](../full_tutorial.md) only after this review passes.