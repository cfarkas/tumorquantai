# Review QC overlays

| | |
| --- | --- |
| **For** | Researchers reviewing image alignment after a completed sample |
| **Hands-on steps** | Open overview, annotated zoom, composite, summary, and audit |
| **Prerequisites** | At least one completed real-inference sample |
| **Download/storage** | No download; images and PDF already exist in the result |
| **Writes to** | Nothing unless `report` is rerun |

## Open the generated images

For each completed sample, the current worker writes:

| File | Review |
| --- | --- |
| `overlays/overview_with_zoom_box.png` | Whole-slide orientation and the selected zoom box |
| `overlays/zoom_overlay_celltypes.png` | High-resolution cell annotations |
| `overlays/celltypes_overview_and_zoom.png` | Combined overview and annotated zoom |
| `overlays/celltypes_overview_and_zoom.pdf` | Vector/text-friendly version of the combined figure |

The repository output name is `celltypes_overview_and_zoom.png`—not a guessed
singular or alternate overlay name.

Compare the images with `summary/summary.json`. Confirm the slide ID, source
MPP, target MPP, processed percentage, random seed, and zoom coordinates. Then
check `aggregated_celltypes/sample_aggregation_audit.csv` for inclusion.

Visual review should consider tissue orientation, focus/stain artifacts, tissue
selection, registration, cell-mark alignment, implausible dense/sparse regions,
and whether the displayed zoom is representative. It does not turn model
predictions into pathologist ground truth.

## Rebuild the navigator

```bash
tumorquantai report /data/results
```

Expected output is a self-contained `START_HERE.html` with relative links only
to files that exist.

## Stop and clean up

Image review does not modify results. Press **Ctrl+C** if report generation is
interrupted and rerun. Do not delete overlays while retaining derived tables
for a reproducible analysis.

**Next:** learn [counts versus fractions](../explanation/counts-fractions.md).
