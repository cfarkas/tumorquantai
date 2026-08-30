# Breast IHC TIFF patch example support

This directory accompanies the
[breast IHC raw-TIFF patch tutorial](../../docs/tutorials/breast-ihc-patches.md).
It contains command templates and links to an aggregate reference result. It
does not contain TIFFs, private case mappings, case-level clinical data,
checksums, or a public manifest. The public raw-only dataset is
[Zenodo record 21797920](https://zenodo.org/records/21797920), DOI
[`10.5281/zenodo.21797920`](https://doi.org/10.5281/zenodo.21797920), under
CC BY 4.0. Do not assign the lymphoma tutorial DOI to this collection or use
either dataset DOI as a TumorQuantAI software DOI.

## Package-native marker quantification

This route measures ER, PR, HER2, and Ki-67 staining and does not require
HistoPLUS:

```bash
tumorquantai ihc quantify /path/to/breast-ihc-downloads \
  --manifest /path/to/manifest/patch_manifest.csv \
  --output /path/to/breast-ihc-marker-results \
  --workers 12 \
  --save-cells
```

Open `START_HERE.html` and inspect every segmentation overlay. The concise
output is `tables/tumorquantai_marker_values.csv`; it includes all four marker
pre-scores, denominators, and QC status in one row per public case.

The [aggregate reference concordance CSV](../../docs/assets/data/breast_ihc_reference_concordance_metrics.csv)
contains no case rows. The private 51-row pathologist CSV and paired case
outputs are deliberately excluded from Git.

## Embedded-MPP CPU run

```bash
# Use this route only when every selected TIFF has reliable embedded MPP.
tumorquantai --patches /path/to/breast-ihc-tiff-patches \
  --paper-figures \
  --output /path/to/breast-ihc-patch-results \
  --cpu
```

## Explicit-MPP CPU run

```bash
# Enter one verified common source MPP for the selected TIFF collection.
read -rp "Verified source MPP in micrometres per pixel: " SOURCE_MPP

# Process all discovered patches and write paper/QC figures.
tumorquantai --patches /path/to/breast-ihc-tiff-patches \
  --paper-figures \
  --output /path/to/breast-ihc-patch-results \
  --source-mpp "$SOURCE_MPP" \
  --cpu
```

## Expected per-input paper outputs

Each completed input retains the established filenames:

```text
<sample>/paper_figures/
├── celltypes_paper_figure.png
├── celltypes_paper_figure.pdf
├── celltypes_paper_figure_legend.txt
├── celltype_counts_barplot.png
└── celltype_counts_barplot.pdf
```

The compact paper figure places all HistoPLUS cell-type counts and within-input
percentages at left (panel **a**), with the scale-calibrated overview and QC
inset using the configured cell-type overlay stacked at right (panels **b** and
**c**). Its visual references are [STTT 2026 Figure
6](https://www.nature.com/articles/s41392-026-02734-0#Fig6) and [Figure
7](https://www.nature.com/articles/s41392-026-02734-0#Fig7); this does not import
their methods or biological claims. The text legend carries the
sample ID, panel explanations, source/denominator, scale and ROI, pinned model
identity, and research-use caveats. The legend is required when the completion
summary records the current paper-layout version. Direct reuse of the same
persistent worker output preserves the legacy completion contract when a summary
has no layout version, but standard Nextflow resume also keys staged code and
configuration. An upgrade can invalidate `PROCESS_SLIDE` and re-enter inference.
Inspect `--resume --dry-run` for Nextflow `-resume` and the original work
directory; preserve the exact software/work cache or use `--cpu` if reuse is
uncertain. Use a new output directory or a deliberate rerun when redesigned
figures are wanted for legacy outputs.

Patch mode processes 100% of the discovered TIFF patch inputs. Review the
completion audit: failed or incomplete inputs are not numerical zero. These are
HistoPLUS cell-type outputs, not breast-marker scores or receptor-status calls.
Any downstream breast IHC categories are computational receptor-profile
pre-score groups, not diagnoses or pathologist sign-out, and separate stains do
not establish cell-level co-expression.

For mixed-scale inputs, `tumorquantai status`, status JSON,
`START_HERE.html`, and the text run summary report the distinct per-input MPP
values and identify their provenance as per-input embedded TIFF metadata.

## Offline release-draft sanitizer

`bin/prepare_breast_ihc_patch_release.py` is a local-only preparation utility;
it cannot deposit, upload, or publish data. Its private source-selection CSV
requires `case_id`, `marker`, `field_id`, `source_path`, `include`,
`microns_per_pixel`, and `mpp_provenance`. Keep that manifest, the
exact-mode-`0600` alias secret, and the mode-`0600` private linkage outside
both the repository and the public staging directory.

The per-image MPP must be externally audited; source TIFF resolution tags may
be absent or wrong. Safe canonical provenance values include
`measured_scale_bar_calibration`, `documented_magnification_extrapolation`, and
`externally_verified_calibration`. Known cohort forms are canonicalized, and
the public `patch_manifest.csv` records only the canonical English value.
Source TIFFs with a non-default `Orientation` tag are rejected rather than
silently transformed.

The mandatory first invocation uses `--dry-run` and new output/linkage targets.
After it passes, rerun the same command without `--dry-run`. The utility strips
non-allowlisted TIFF metadata, fully verifies equality of decoded source and
output RGB pixels, and embeds and re-verifies the manifest's per-image MPP.
Independent visible-pixel, privacy, rights, ethics, and governance review is
still required.

The resulting local draft contains aliased TIFFs, public manifests and counts,
a validation report, and SHA-256/MD5 checksum lists. Original identifiers and
paths remain only in the private linkage.

## Deterministic local packaging

Run `bin/package_breast_ihc_patch_release.py --dry-run` against the completed
sanitized draft before allowing it to create a new package directory. Supply
the exact sanitized case and TIFF counts, review the reported disk estimate,
then repeat the same command without `--dry-run`.

The packager retains the source and uses deterministic `ZIP_STORED` archives,
so the TIFF payload is duplicated on disk. It validates exact source and output
rosters and checksums, canonical MPP provenance, and TIFF metadata and scale.
It also fully decodes each sanitized TIFF to recompute its decoded-RGB SHA-256
and reopens every archive to verify member metadata, size, CRC32, SHA-256, and
MD5. It has no network, deposit, upload, or publication capability.

Here, deterministic means identical validated inputs under the same supported
packager tool/runtime produce exact archive bytes despite different source
filesystem timestamps or modes. It does not promise byte identity across
arbitrary Python versions or ZIP implementations.

For this published cohort, 51 cases and 1,901 sanitized TIFFs become 51
forced-ZIP64 case archives plus `TQA_BreastIHC_manifest_bundle.zip`,
`packaging_report.json`, `SHA256SUMS`, and `MD5SUMS`: exactly 55 top-level
files totaling 74,958,557,152 bytes. The required record quota, privacy,
governance, rights, metadata, and publication reviews were completed for
record 21797920. A new release requires its own independent reviews and quota.

The same templates are available as plain text in [`commands.txt`](commands.txt).
