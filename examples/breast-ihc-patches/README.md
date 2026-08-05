# Breast IHC TIFF patch example support

This directory accompanies the
[breast IHC raw-TIFF patch tutorial](../../docs/tutorials/breast-ihc-patches.md).
It contains command templates only. It does not contain TIFFs, private case
mappings, clinical data, checksums, or a public manifest. The public raw-only
dataset is [Zenodo record 21797920](https://zenodo.org/records/21797920), DOI
[`10.5281/zenodo.21797920`](https://doi.org/10.5281/zenodo.21797920), under
CC BY 4.0. Do not assign the lymphoma tutorial DOI to this collection or use
either dataset DOI as a TumorQuantAI software DOI.

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

Patch mode processes 100% of the discovered TIFF patch inputs. Review the
completion audit: failed or incomplete inputs are not numerical zero. Any
breast IHC categories are computational receptor-profile pre-score groups, not
diagnoses or pathologist sign-out.

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
