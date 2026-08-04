# Failed sample versus biological zero

These states are deliberately different:

| State | Evidence | Matrix behavior |
| --- | --- | --- |
| Completed with a missing class | Valid `summary.json` and count table; class absent | Zero for that class |
| Completed with no detections | Valid completion marker, header-only count table, `zero_detections: true`, `n_cells: 0` | Verified all-zero sample column |
| Failed | Failure/return status or missing required completion artifacts | No numeric column; retained in audit |
| Incomplete or pending | Discovered/selected but not validly completed | No numeric column; retained in audit/status |

The aggregator requires `summary/summary.json` and
`cell_types/class_counts.csv` and cross-checks counts against `n_cells` and
`zero_detections`. A malformed empty folder cannot silently enter as zero.

Always read `aggregated_celltypes/sample_aggregation_audit.csv` alongside the
matrices. `status` reports completed, failed, incomplete, excluded, and pending
samples and identifies the first log to inspect:

```bash
tumorquantai status /data/results
```

This distinction prevents technical absence from becoming a false biological
measurement.

**Next:** use [resume](../how-to/resume.md) for failed/incomplete samples.
