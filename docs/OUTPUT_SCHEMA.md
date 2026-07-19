# Output and aggregation schema

## Per-slide count table

`<sample>/cell_types/class_counts.csv`:

| Column | Type | Meaning |
|---|---|---|
| `class_id` | integer | Canonical HistoPLUS class ID; `-1` is the sentinel for an unmapped raw class |
| `class_name` | string | Canonical display name |
| `count` | positive integer | Cells detected in processed tissue tiles |

The count sum must equal `summary/summary.json:n_cells`.
A slide with no detections has a header-only count table, `n_cells: 0`, and
`zero_detections: true`. The aggregator requires that flag to agree exactly
with the observed total, so a failed or malformed empty result cannot silently
become a biological zero.

## Coordinate table

`cell_type_coordinates.csv` or `.csv.gz` contains:

```text
cell_id,class_id,class_name,centroid_x,centroid_y,bbox_x0,bbox_y0,bbox_x1,bbox_y1
```

Coordinates are level-0 pixel coordinates. The companion NPY payload preserves
polygons, palette metadata, and numeric arrays for efficient reports.

When requested, the large `cell_type_coordinates.json` and
`cell_types_qupath.json` exports each have a sibling `.integrity.json`
sidecar containing the expected SHA-256. Resume rejects a missing, empty, or
mismatched requested export instead of accepting a partial prior write.

## Converted-input provenance

A retained `pyramidal_input/<L0 filename>` has a sibling
`<L0 filename>.provenance.json`. The worker reuses the conversion only when
the source identity and conversion settings match; otherwise it rebuilds it.

## Count matrix

`aggregated_celltypes/celltype_counts_by_sample.csv`:

- rows: the union of cell types discovered in completed samples
- first metadata columns: `class_id`, `cell_type`
- remaining columns: stable sample IDs
- missing type in a completed sample: integer zero
- failed/incomplete sample: no numeric column; retained in the audit CSV

## Fraction matrix

The same orientation, with each value divided by all detected cells in that
sample. Nonempty sample columns sum to 1; verified no-detection columns contain
zero and sum to 0.

## Sampling semantics

When `percent_slide < 100`, counts refer to the sampled tissue tiles. They are
not validated full-slide estimates and are not automatically multiplied by
`100 / percent_slide`. The summary records percentage, seed, and sampled/total
tile counts for auditability.

## Completion and audit

A Nextflow result is considered complete for aggregation only when both the
summary and class-count table exist. `sample_aggregation_audit.csv` lists every
discovered sample and records inclusion, completion, totals, sampling metadata,
paths, and any batch return code available.
Paths to published artifacts are relative to the result root so they remain
valid after Nextflow work directories are cleaned. Input/model provenance paths
may remain absolute because they refer to external resources.
