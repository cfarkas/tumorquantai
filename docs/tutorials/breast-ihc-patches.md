# Other example run: breast IHC raw TIFF patches at 100%

This example route runs HistoPLUS inference over authorized local raw TIFF
patches and writes per-input paper and QC figures. It processes the complete
discovered patch collection rather than a seeded percentage sample.

!!! warning "Example data are not public yet"
    The breast-IHC example collection, checksums, public manifest, and Zenodo
    DOI are pending data-governance review and publication. This page does not
    assign a DOI or public download URL. The published lymphoma tutorial DOI
    belongs only to the lymphoma WSI collection and must not be reused here.

!!! danger "Research use only"
    TumorQuantAI and HistoPLUS predictions are not diagnoses, pathologist
    ground truth, treatment recommendations, or clinically validated assay
    results. Breast IHC group labels must be reported as **computational
    receptor-profile pre-score groups**.

## What this route does

| Setting | Patch-mode behavior |
| --- | --- |
| Input | Local `.tif` or `.tiff` patch images that the research team is authorized to process |
| Physical scale | Reliable embedded TIFF MPP, or one verified common `--source-mpp` override |
| Processing depth | 100% of discovered patch inputs; no 1% or 10% sampling preset |
| Inference | The same gated, pinned HistoPLUS model used by the maintained workflow |
| Visual results | Whole-input/zoom QC overlays plus PNG/PDF paper figures |
| Numeric results | Per-input coordinates and counts plus completion-aware cohort tables |

Full patch processing does not make the collection a whole-slide analysis and
does not make separate marker images measurements of the same cells.

## 1. Install TumorQuantAI and configure model access

```bash
# Clone TumorQuantAI and install the Docker execution route.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
./tumorquantai install --docker
export PATH="$HOME/.local/bin:$PATH"

# Confirm runtime, storage, and authorized model readiness.
tumorquantai doctor --online
```

Use the execution method selected for the host. Follow
[HistoPLUS model access](../how-to/model-access.md) before inference.

## 2. Prepare privacy-safe TIFF patch names

Use research IDs and canonical English marker names. Do not place names, medical
record numbers, dates of birth, or private linkage values in paths or image
metadata.

```text
/path/to/breast-ihc-tiff-patches/
├── study_001_HE_01.tif
├── study_001_ER_01.tif
├── study_001_PR_01.tif
├── study_001_HER2_01.tif
└── study_001_KI67_01.tif
```

The filename describes the intended stain; it does not prove a result. Keep the
private case-linkage table outside the repository and publication package.

## 3. Establish source MPP

Every TIFF patch needs a trustworthy physical pixel size in micrometres per
pixel. Use embedded metadata only when it is complete and consistent with the
scanner/export record. If metadata are absent or unreliable, obtain the value
from the acquisition system or a traceable calibration and pass it explicitly.

Do not infer MPP from image dimensions, a rescaled or unverified screenshot, an
unrelated slide, or the HistoPLUS target MPP. A measured scale bar supports an
audit only when its stated length and original pixel geometry are verified. A
single `--source-mpp` override applies to the selected collection and therefore
requires a common source scale.

For release preparation, the manifest's per-image MPP must come from an
external calibration audit. Source TIFF resolution tags are not authoritative:
they may be absent or wrong. Record the audited value and its allowlisted
provenance in the private source manifest; the sanitizer embeds that value into
the sanitized TIFF and verifies the resulting resolution tags.

## 4. Run all patches on CPU

When every TIFF contains reliable embedded MPP, use:

```bash
# Process 100% of the discovered TIFF patches and request paper/QC figures.
tumorquantai --patches /path/to/breast-ihc-tiff-patches \
  --paper-figures \
  --output /path/to/breast-ihc-patch-results \
  --cpu
```

When embedded MPP is missing or unreliable, enter the verified common value and
pass it explicitly:

```bash
# Enter the verified common source MPP without copying another dataset's value.
read -rp "Verified source MPP in micrometres per pixel: " SOURCE_MPP

# Process the same complete collection with an explicit physical scale.
tumorquantai --patches /path/to/breast-ihc-tiff-patches \
  --paper-figures \
  --output /path/to/breast-ihc-patch-results \
  --source-mpp "$SOURCE_MPP" \
  --cpu
```

Patch mode fails closed when it cannot establish physical scale. Reliable
embedded MPP is resolved independently for every patch, so mixed 4×, 10×, and
40× exports may remain in one run. A single explicit `--source-mpp` override
is valid only when every selected TIFF shares that verified scale. CPU
inference can be substantially slower than GPU inference; stopping and
repeating the identical command preserves normal resume behavior.

## 5. Confirm complete processing

```bash
# Review completed, failed, incomplete, excluded, and pending patch inputs.
tumorquantai status /path/to/breast-ihc-patch-results

# Regenerate the portable results index after inference finishes.
tumorquantai report /path/to/breast-ihc-patch-results
```

Open `START_HERE.html`, then verify that the aggregation audit accounts for the
entire intended TIFF roster. Full mode means every discovered input was
scheduled; it does not mean every input succeeded. Failed or incomplete patches
remain explicit and never become numerical zero.

When patch inputs contain mixed embedded scales, `tumorquantai status`, its
JSON `source_mpp_values` and `source_mpp_provenance` fields, `START_HERE.html`,
and the text run summary report the distinct per-input MPP values and identify
their provenance as per-input embedded TIFF metadata. Review these values before
interpreting scale bars or counts.

## 6. Review paper and QC outputs

For every completed patch, inspect:

1. `<sample>/overlays/celltypes_overview_and_zoom.png` for tissue, alignment,
   the connected zoom, contours, and scale bars.
2. `<sample>/paper_figures/celltypes_paper_figure.png` and `.pdf` for the
   publication-oriented composition.
3. `<sample>/paper_figures/celltype_counts_barplot.png` and `.pdf` for the
   plotted detected-cell counts.
4. `<sample>/cell_types/class_counts.csv` and the coordinate table for the
   plotted source values.
5. `<sample>/summary/summary.json` for completion, resolved MPP, model identity,
   input fingerprint, device, and provenance.
6. `aggregated_celltypes/sample_aggregation_audit.csv` before interpreting any
   cohort matrix.

See the [output schema](../reference/outputs.md) for the complete path list.

## 7. Describe breast IHC groups conservatively

If a downstream presentation arranges marker-specific patch results by ER, PR,
HER2, or Ki-67 patterns, call the categories **computational receptor-profile
pre-score groups**. Keep continuous values and their numerators/denominators
visible. Do not imply that differently stained patches are cell-level
co-expression measurements.

An equivocal HER2 pre-score remains equivocal and requires appropriate
independent clinical testing. A missing or failed marker is not negative. Do
not infer histologic type, intrinsic molecular subtype, prognosis, treatment
eligibility, or clinical accuracy from these research outputs.

## 8. Prepare an offline release draft

`bin/prepare_breast_ihc_patch_release.py` prepares a new, local sanitized
draft from an explicitly selected set of authorized TIFF patches. It has no
network, deposit, upload, or publication capability. The source manifest,
alias secret, and private linkage are private materials and must remain outside
both the repository and the public staging directory.

The private source-selection CSV has these required columns:

| Column | Required content |
| --- | --- |
| `case_id` | Private source case identifier |
| `marker` | Canonical English marker: `H&E`, `ER`, `PR`, `HER2`, or `Ki-67` |
| `field_id` | Private source field or patch identifier |
| `source_path` | Authorized `.tif` or `.tiff` source path, absolute or relative to the manifest |
| `include` | Exactly `true` or `false` |
| `microns_per_pixel` | Verified physical scale for this individual image |
| `mpp_provenance` | Allowlisted English provenance for the audited scale |

For example, the following is a schema illustration, not a usable manifest.
Replace every placeholder and keep the completed CSV private:

```csv
case_id,marker,field_id,source_path,include,microns_per_pixel,mpp_provenance
PRIVATE_CASE_ID,H&E,PRIVATE_FIELD_ID,/path/to/authorized/source-patch.tif,true,VERIFIED_PER_IMAGE_MPP,measured_scale_bar_calibration
```

`mpp_provenance` is not free text. Use one of the safe English provenance
categories `measured_scale_bar_calibration`,
`documented_magnification_extrapolation`, or
`externally_verified_calibration`. Known cohort-specific objective/binning
forms are normalized to corresponding canonical English values. The canonical
value is published in `patch_manifest.csv` and summarized in
`validation_report.json`; private instrument, vendor, date, or operator notes
must not be placed in this column.

This provenance describes how the external audit established
`microns_per_pixel`; it does not claim that the source TIFF's resolution tags
were present or correct.

Source TIFFs may omit the TIFF `Orientation` tag or use its default top-left
value. The sanitizer rejects a non-default orientation rather than silently
changing pixel coordinates or visual orientation during re-encoding.

Create the alias secret in a private location. The utility requires a regular,
non-symlink file owned by the current user, with exactly mode `0600`, at least
32 random bytes, and no additional hard links. Retain a protected backup when
stable aliases must be reproduced.

```bash
# Create private release material outside the repository and public staging.
install -d -m 700 /path/outside/repository/private-release-material
umask 077
dd if=/dev/urandom \
  of=/path/outside/repository/private-release-material/alias-secret.bin \
  bs=32 count=1 status=none
chmod 600 /path/outside/repository/private-release-material/alias-secret.bin
```

A dry run is mandatory before local draft creation. Choose new public-output
and private-linkage targets that do not already exist, replace the two count
placeholders with the exact included-case and included-file integers, and run:

```bash
# Validate the complete private selection and plan without writing either output.
python3 bin/prepare_breast_ihc_patch_release.py \
  --source-manifest /path/outside/repository/private-source-selection.csv \
  --alias-secret-file /path/outside/repository/private-release-material/alias-secret.bin \
  --public-output /path/outside/repository/breast-ihc-public-draft \
  --private-linkage /path/outside/repository/private-release-material/private-linkage.csv \
  --expected-cases REPLACE_WITH_INCLUDED_CASE_COUNT \
  --expected-files REPLACE_WITH_INCLUDED_TIFF_COUNT \
  --dry-run
```

The dry run validates the selection and prints a safe summary without private
IDs or paths. It writes neither the public draft nor the private linkage. Only
after it passes, rerun the same inputs without `--dry-run`:

```bash
# Create the local sanitized draft after the mandatory dry run passes.
python3 bin/prepare_breast_ihc_patch_release.py \
  --source-manifest /path/outside/repository/private-source-selection.csv \
  --alias-secret-file /path/outside/repository/private-release-material/alias-secret.bin \
  --public-output /path/outside/repository/breast-ihc-public-draft \
  --private-linkage /path/outside/repository/private-release-material/private-linkage.csv \
  --expected-cases REPLACE_WITH_INCLUDED_CASE_COUNT \
  --expected-files REPLACE_WITH_INCLUDED_TIFF_COUNT
```

The local public draft contains only the following release-side structure:

```text
breast-ihc-public-draft/
├── patches/<case_alias>/<patch_alias>_<MARKER>.tif
├── patch_manifest.csv
├── case_marker_counts.csv
├── validation_report.json
├── SHA256SUMS
└── MD5SUMS
```

For each selected image, the utility fully decodes the source and sanitized
TIFF, verifies identical decoded RGB pixels, strips descriptions, dates,
software, vendor, OME, shaped, and other non-allowlisted metadata, and computes
checksums. It carries that row's verified `microns_per_pixel` value into the
sanitized TIFF resolution tags, then reads and verifies the embedded scale.
Different rows may therefore retain different physical scales. Metadata
stripping does not detect identifiers burned into pixels, so independent
visible-pixel, privacy, ethics, rights, and governance review remains required.

The public `patch_manifest.csv` records each image's audited MPP, canonical
`mpp_provenance`, and domain-separated decoded-RGB SHA-256. The private linkage
retains both the original and canonical provenance values.

The HMAC-derived aliases appear in the public draft. Original identifiers,
source paths, and the alias mapping appear only in the separately created
mode-`0600` private linkage. `validation_report.json` records that the result
is draft-only and that no network, upload, or publication action occurred.

The sanitized tree is an input to local packaging, not an upload payload. Do
not upload or publish it; the sanitizer cannot perform either action.

## 9. Package the sanitized draft locally

`bin/package_breast_ihc_patch_release.py` converts one completed sanitized
draft into deterministic local upload files. It retains and never modifies the
source tree. The package output must be a new directory outside the repository
and separate from the sanitized source tree.

A packager dry run is mandatory. Replace both count placeholders with the exact
counts recorded by the completed sanitized draft:

```bash
# Validate the exact draft roster and report disk/upload plans without writing.
python3 bin/package_breast_ihc_patch_release.py \
  --source-draft /path/outside/repository/breast-ihc-public-draft \
  --package-output /path/outside/repository/breast-ihc-upload-package \
  --expected-cases REPLACE_WITH_SANITIZED_CASE_COUNT \
  --expected-files REPLACE_WITH_SANITIZED_TIFF_COUNT \
  --dry-run
```

The dry run validates the entire source roster and reports the upload-file
count and conservative additional-disk estimate. It writes no package output.
Only after that exact plan passes, repeat it without `--dry-run`:

```bash
# Create the deterministic local package after the mandatory dry run passes.
python3 bin/package_breast_ihc_patch_release.py \
  --source-draft /path/outside/repository/breast-ihc-public-draft \
  --package-output /path/outside/repository/breast-ihc-upload-package \
  --expected-cases REPLACE_WITH_SANITIZED_CASE_COUNT \
  --expected-files REPLACE_WITH_SANITIZED_TIFF_COUNT
```

For this cohort, the validated planning values are **51 cases** and **1,901
sanitized TIFFs**. Use `--expected-cases 51 --expected-files 1901` only for
that exact roster. Its package has 55 top-level upload files:

```text
breast-ihc-upload-package/
├── TQA_BC_<case-alias>.zip                 # 51 ZIP64 case archives
├── TQA_BreastIHC_manifest_bundle.zip       # 1 manifest bundle
├── packaging_report.json                   # 1 packaging report
├── SHA256SUMS                              # 1 upload checksum file
└── MD5SUMS                                 # 1 upload checksum file
```

The manifest bundle contains `patch_manifest.csv`, `case_marker_counts.csv`,
`validation_report.json`, the sanitized draft's `SHA256SUMS` and `MD5SUMS`, and
the generated `archive_manifest.csv`. The outer checksum files cover all 51
case archives, the manifest bundle, and the packaging report.

Case archives use forced ZIP64 and `ZIP_STORED`; no TIFF recompression occurs.
For identical validated inputs and the same supported packager tool/runtime,
fixed member order, timestamps, modes, and ZIP settings produce exact archive
bytes independently of source filesystem metadata. This is not a guarantee of
byte identity across arbitrary Python versions or ZIP implementations.
`ZIP_STORED` also duplicates the retained TIFF payload on disk. Confirm the
dry-run value of `estimated_additional_disk_bytes` before packaging.

Before writing, the packager verifies the exact allowlisted source roster,
manifest and case-marker counts, sanitizer report, source checksums, aliases,
TIFF headers, metadata allowlist, per-image MPP, and canonical MPP provenance.
It fully decodes every sanitized TIFF and recomputes its domain-separated RGB
SHA-256 instead of trusting the manifest value alone. After writing, it reopens
every archive and verifies its exact member roster, fixed member metadata,
ZIP64 requirement, stored sizes, CRC32, SHA-256, and MD5. It then verifies the
exact 55-file output roster and both upload checksum files and confirms that
the sanitized source roster remains unchanged.

The packager has no network, deposit, upload, or publication capability.
Zenodo's default planning limits remain 50 GB and 100 files per record. The
55-file cohort package is within the default file-count limit, but measured
package size, any quota request, visible-pixel/privacy review, data-governance
approval, and the publication decision remain pending.

## Dataset publication status

The future public example must not be documented as downloadable until its
governance review, privacy review, manifest, checksums, repository metadata, and
Zenodo record have been completed and verified together. Until then, use only
authorized local TIFF patches and cite the TumorQuantAI software separately
from any private dataset.

The repository support folder is `examples/breast-ihc-patches/`.
