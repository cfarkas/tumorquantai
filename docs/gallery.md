# Results and workflow gallery

These explanatory figures show how TumorQuantAI organizes a run. They are diagrams, not model-validation results or clinical examples.

## Whole-slide workflow

![TumorQuantAI whole-slide workflow](assets/tumorquantai-hero.svg)

A primary H&E WSI is discovered with its physical scale, divided into tissue tiles, processed with HistoPLUS, and summarized as reviewable overlays, coordinates, per-slide counts, and cohort tables.

## QuickStart Example 1

![One-slide quickstart flow](assets/tutorial/quickstart_wsi_flow.svg)

Public download, checksum validation, L0/L2 conversion, and inspection are model-free. Authorized HistoPLUS access is needed only for the optional final 1% analysis.

## Full 21-slide tutorial

![Full 21-slide lymphoma workflow](assets/tutorial/full_lymphoma_flow.svg)

The complete public tutorial uses all 21 lymphoma WSIs with the `fast` preset: a deterministic 10% of detected tissue tiles per slide. Every slide must have an overlay, summary, class-count table, and audit status.

## Input organization

![Portable WSI input layout](assets/tutorial/input_layout.svg)

Use one L0 primary TIFF and one L2 companion per sample. The source MPP must come from scanner or export provenance.

## Sampling presets

![Sampling presets](assets/tutorial/sampling_presets.svg)

The same seed and configuration reproduce sampled tile selection. Sampled-tile counts are not whole-slide estimates.

## Output review order

![Output map](assets/tutorial/output_map.svg)

Start with `START_HERE.html`, review every overlay, confirm summary provenance, then inspect the aggregation audit before using count or fraction matrices.

## Raw TIFF patch paper figure

```text
┌───────────────────────────┬────────────────────────────────────┐
│ a  HistoPLUS counts + %   │ b  scale-calibrated overview      │
│    (all detected classes) ├────────────────────────────────────┤
│                           │ c  configured-overlay QC inset    │
└───────────────────────────┴────────────────────────────────────┘
```

`celltypes_paper_figure.png` and `.pdf` use this compact, full-width panel
organization, inspired by the visual grammar of
[STTT 2026 Figure 6](https://www.nature.com/articles/s41392-026-02734-0#Fig6)
and [Figure 7](https://www.nature.com/articles/s41392-026-02734-0#Fig7).
Bold lowercase panel letters remain in the artwork; the sample ID and prose
move to `celltypes_paper_figure_legend.txt`. The QC inset uses the configured
cell-type overlay. Counts and percentages are
HistoPLUS cell-type predictions for the analyzed input, not breast-marker
scores or receptor-status calls. The layout reference imports no validation or
biological claim.

For a manuscript submission, separately review the [Nature Research figure
specifications](https://research-figure-guide.nature.com/figures/preparing-figures-our-specifications/);
these example exports are not a journal-production compliance guarantee.

## Real output filenames

A completed slide normally provides:

```text
<sample>/
├── overlays/
│   └── celltypes_overview_and_zoom.png
├── paper_figures/
│   ├── celltypes_paper_figure.png
│   └── celltypes_paper_figure_legend.txt
├── summary/
│   └── summary.json
└── cell_types/
    ├── class_counts.csv
    └── cell_type_coordinates.csv
```

The completed cohort normally provides:

```text
aggregated_celltypes/
├── sample_aggregation_audit.csv
├── celltype_counts_by_sample.csv
└── celltype_fractions_by_sample.csv
```

See [Output files](outputs.md) for interpretation and [Research limitations](explanation/research-limitations.md) before using the measurements.
