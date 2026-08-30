# IHC v1-to-v2 migration

IHC schema v2 corrects a color-specific failure in the original research
engine. A numerical inverse-HED DAB channel is not, by itself, proof that a
pixel is brown: magenta and nearly neutral gray fields can receive substantial
positive DAB concentration. In the 51-case breast-IHC example this made every
v1 ER case cross the 1% research threshold.

## What changed

| Contract | v1 | v2 |
| --- | --- | --- |
| Schema | `tumorquantai_ihc_v1` | `tumorquantai_ihc_v2` |
| Engine | `hdab-watershed-membrane-proxy-v1` | `hdab-color-checked-watershed-membrane-proxy-v2` |
| Scoring DAB | Unconstrained inverse HED | Expected-brown optical-density cone |
| Legacy audit value | Not retained separately | Retained in all nuclear-marker tables |
| Cell table | `mean_dab_od` only | Color-checked `mean_dab_od` plus `unconstrained_mean_dab_od` |

The default color cone requires both adjacent-channel optical-density
differences to be at least `max(0.02, 0.15 × unconstrained DAB OD)`. These
settings are part of the analysis signature.

`dab_positive_percent`, `h_score`, `marker_pre_score`, nuclear-marker
categories, HER2 membrane-proxy inputs, and QC overlays now use the
color-checked DAB channel. The following audit fields expose the unconstrained
measurement:

- `unconstrained_dab_negative_cells`
- `unconstrained_dab_weak_cells`
- `unconstrained_dab_moderate_cells`
- `unconstrained_dab_strong_cells`
- `unconstrained_dab_positive_cells`
- `unconstrained_dab_positive_percent`
- `unconstrained_h_score`
- `unconstrained_mean_dab_od` in optional cell CSVs

The wide CSV includes
`tumorquantai_<marker>_unconstrained_dab_percent` for ER, PR, and Ki-67.

## Rerun instead of resuming in place

v1 and v2 have different engine, schema, settings, and analysis signatures.
Do not point v2 at a v1 result directory. Use a new output:

```bash
tumorquantai ihc quantify /path/to/downloads \
  --manifest /path/to/manifest/patch_manifest.csv \
  --output /path/to/breast-ihc-results-v2 \
  --workers 12 \
  --save-cells
```

Keep the v1 directory unchanged if a historical reproduction is required.

## Explicit earlier-method reproduction

To reproduce the unconstrained color behavior while using the new auditable
schema, pass:

```bash
tumorquantai ihc quantify /path/to/downloads \
  --manifest /path/to/manifest/patch_manifest.csv \
  --output /path/to/breast-ihc-results-unconstrained \
  --unconstrained-dab-color
```

This makes the scoring and unconstrained channels identical and records
`unconstrained-hed-v1-compatible` in `dab_color_model`. It intentionally has a
different signature from the default v2 run.

## Interpretation boundary

The correction removes a known non-brown color artifact. It does not identify
invasive tumour cells, create a tumour ROI, verify laboratory controls, repair
field sampling, or validate a clinical assay. ER and PR clinical percentages
refer to tumour nuclei; these public selected fields still use all accepted
segmented nuclei. Compare versions as research methods and inspect every QC
overlay.

The public reference cohort exposed the artifact and was used to audit the
correction. Its before-and-after metrics are method-development results, not an
independent validation set.
