# Other example run: breast IHC raw TIFF patches at 100%

This example route runs HistoPLUS inference over authorized local raw TIFF
patches and writes per-input paper and QC figures. It processes the complete
discovered patch collection rather than a seeded percentage sample.

!!! info "Public raw patch dataset"
    The raw-only breast-IHC collection is public under CC BY 4.0 at
    [Zenodo record 21797920](https://zenodo.org/records/21797920), with dataset
    DOI [`10.5281/zenodo.21797920`](https://doi.org/10.5281/zenodo.21797920).
    Its 55 files comprise 51 case archives containing 1,901 TIFF patches plus
    four auxiliary files: one manifest bundle, one packaging report, and two
    checksum rosters (74,958,557,152 bytes total). Generated paper and QC
    figures are not part of the deposit; create them locally with this
    workflow. This DOI identifies the breast-IHC dataset, not TumorQuantAI
    software. The separate lymphoma tutorial retains its own dataset DOI.

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
| Visual results | Whole-input/zoom QC plus a compact PNG/PDF cell-type paper figure and external text legend |
| Numeric results | Per-input HistoPLUS cell coordinates, counts, and fractions plus completion-aware cohort tables |

Full patch processing does not make the collection a whole-slide analysis and
does not make separate marker images measurements of the same cells. Stable
patch mode predicts HistoPLUS cell types; a stain token in a filename is input
provenance, not an ER/PR/HER2/Ki-67 score. This route does not quantify marker
intensity, infer receptor status, or establish cell-level co-expression across
separately stained patches.

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
   the connected zoom, configured cell-type overlay, and scale bars.
2. `<sample>/paper_figures/celltypes_paper_figure.png` and `.pdf` for the
   publication-oriented composition.
3. `<sample>/paper_figures/celltypes_paper_figure_legend.txt` for the slide ID,
   panel descriptions, count source and denominator, scale/ROI/model provenance,
   and research-use limitations.
4. `<sample>/paper_figures/celltype_counts_barplot.png` and `.pdf` for the
   standalone detected-cell count chart.
5. `<sample>/cell_types/class_counts.csv` and the coordinate table for the
   plotted source values.
6. `<sample>/summary/summary.json` for completion, resolved MPP, model identity,
   input fingerprint, device, figure-layout version, and provenance.
7. `aggregated_celltypes/sample_aggregation_audit.csv` before interpreting any
   cohort matrix.

The compact paper figure uses a visual grammar inspired by [STTT 2026 Figure
6](https://www.nature.com/articles/s41392-026-02734-0#Fig6) and [Figure
7](https://www.nature.com/articles/s41392-026-02734-0#Fig7):

| Panel | Content |
| --- | --- |
| **a** | Every detected HistoPLUS cell type, with raw count and percentage of all cells detected in that input |
| **b** | Scale-calibrated whole-input overview with the selected ROI outlined |
| **c** | Enlarged QC inset with the configured cell-type overlay and its own scale bar |

The artwork has bold lowercase panel letters and necessary graph labels, but no
sample title or explanatory prose. Those details belong in the companion text
legend. The visual reference concerns layout only; it does not transfer methods,
performance, or biological claims from another study.

Before manuscript submission, separately check the [Nature Research figure
specifications](https://research-figure-guide.nature.com/figures/preparing-figures-our-specifications/).
The generated PNG/PDF files are not a guarantee of journal-production
compliance.

For newly rendered outputs, `run_metadata.json` records the portable legend
path and paper-figure layout version. When the completion summary records the
current layout version, a missing or empty legend prevents completion/resume
reuse. Because the layout version is separate from the scientific worker
processing signature, direct reuse of the same persistent worker output retains
the legacy completion contract for a summary without a layout version. Standard
`tumorquantai` execution uses Nextflow, whose cache also keys staged worker code
and configuration; a software upgrade may invalidate `PROCESS_SLIDE` and
re-enter HistoPLUS inference. Preview the complete command with
`--resume --dry-run`, then confirm the expanded engine command uses Nextflow
`-resume` and the original work directory. Preserve the exact software/work
cache, or choose `--cpu` when reuse is uncertain. To obtain the redesigned
figure for a legacy result, choose a new output directory or a deliberate rerun.
The count denominator is all
HistoPLUS-detected cells in the analyzed input, not tissue area, all cells in a
case, or an extrapolated whole-slide total.

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
published cohort package contains exactly 55 files and 74,958,557,152 bytes, so
it required additional record storage while remaining within the file-count
limit. A new release still requires its own measured-size check, quota where
needed, visible-pixel/privacy review, governance approval, and publication
authorization.

## 10. Create or resume the open Zenodo draft

`bin/zenodo_breast_ihc_deposit.py` is the draft-only uploader for this exact
release. It accepts only the 51 verified case ZIPs and the four verified
auxiliary files described above. It revalidates the complete package locally,
including both checksum rosters, the manifest bundle, every case archive and
member, and the packaging report before it reads a credential or contacts
Zenodo.

Prepare a separate JSON metadata file with a title, description, license, at
least one named creator, `"upload_type": "dataset"`, and
`"access_right": "open"`. Keep the state and token outside the package. The
token file must have mode `0600` and needs only the Zenodo `deposit:write`
scope. Start from this deliberately incomplete template; replace the creator
and license placeholders with reviewed, authorized values:

```json
{
  "title": "TumorQuantAI breast IHC raw TIFF patch dataset",
  "description": "Sanitized raw breast-IHC TIFF patches and verification manifests for research workflows.",
  "upload_type": "dataset",
  "access_right": "open",
  "license": "REPLACE_WITH_AUTHORIZED_CANONICAL_LICENSE_ID",
  "creators": [
    {"name": "REPLACE_WITH_REAL_FAMILY_NAME, REAL_GIVEN_NAME"}
  ],
  "keywords": ["digital pathology", "immunohistochemistry"]
}
```

The uploader rejects unresolved placeholders. It canonicalizes known legacy
license aliases before fingerprinting. If optional `language` is present, use
the canonical three-letter code. Related identifiers require an explicit
supported scheme and canonical relation; omit optional empty arrays instead of
writing `[]`.

First run the network-free plan:

```bash
python3 bin/zenodo_breast_ihc_deposit.py \
  --package-dir /path/outside/repository/breast-ihc-upload-package \
  --metadata /path/outside/repository/zenodo-metadata.json \
  --state /path/outside/repository/private-release-material/zenodo-state.json \
  --plan
```

If the package is larger than the record's available quota, create and verify
the open-access draft without uploading files, then request quota for that
deposition:

```bash
python3 bin/zenodo_breast_ihc_deposit.py \
  --package-dir /path/outside/repository/breast-ihc-upload-package \
  --metadata /path/outside/repository/zenodo-metadata.json \
  --state /path/outside/repository/private-release-material/zenodo-state.json \
  --token-file /path/outside/repository/private-release-material/zenodo-token \
  --create-only
```

An approved account allocation is not sufficient by itself. Open that exact
draft in Zenodo, choose **Manage storage**, allocate the additional quota to
that specific draft, and select **Apply**. Confirm that the draft's resulting
storage allocation covers the complete measured package. Only then run the
same command without `--create-only` and record the confirmed total quota in
bytes when it exceeds 50 GB:

```bash
python3 bin/zenodo_breast_ihc_deposit.py \
  --package-dir /path/outside/repository/breast-ihc-upload-package \
  --metadata /path/outside/repository/zenodo-metadata.json \
  --state /path/outside/repository/private-release-material/zenodo-state.json \
  --token-file /path/outside/repository/private-release-material/zenodo-token \
  --confirmed-quota-bytes REPLACE_WITH_CONFIRMED_TOTAL_QUOTA_BYTES
```

The state is mode `0600` and is bound to the exact metadata and 55 local file
hashes. Repeating the command resumes by remote size and MD5. Each bucket
upload attempt is exactly one PUT, with no blind transport retry. After a
failed or ambiguous PUT, the uploader rereads the exact draft and reconciles
the complete remote roster by filename, size, and MD5. It retries the target
only when that reconciliation confirms the file is absent; an exact committed
file is accepted. A pending or mismatched file, an unexpected file, or the
loss of a previously verified file stops the run rather than triggering
another PUT, deletion, or replacement. Before an upload attempt,
`--replace-mismatched` permits an explicitly reviewed replacement only after
every local file is rehashed. Production and sandbox are the only accepted
origins; use `--api-url https://sandbox.zenodo.org/api` for a sandbox exercise.
The command cannot publish. Inspect the resulting draft in Zenodo and retain
the separate governance and publication approvals.

## 11. Publish the independently authorized draft

`bin/zenodo_breast_ihc_publish.py` is a separate publish-only command. It
cannot create a deposition, change metadata, upload, replace, or delete files.
Use it only after the draft uploader has verified all 55 remote files and the
data steward has approved the irreversible public release.

First obtain the exact release fingerprint and canonical license without a
credential or network request:

```bash
python3 bin/zenodo_breast_ihc_publish.py \
  --package-dir /path/outside/repository/breast-ihc-upload-package \
  --metadata /path/outside/repository/zenodo-metadata.json \
  --state /path/outside/repository/private-release-material/zenodo-state.json \
  --deposition-id REPLACE_WITH_EXACT_DEPOSITION_ID \
  --plan
```

Create a new JSON authorization file containing exactly the following keys.
Copy the license and fingerprint verbatim from the plan, identify the actual
authorizer, and use a timezone-aware ISO-8601 time:

```json
{
  "deidentification_review_complete": true,
  "pixel_content_privacy_review_complete": true,
  "public_redistribution_authorized": true,
  "dataset_rights_confirmed": true,
  "license_confirmed": true,
  "metadata_review_complete": true,
  "publish_irreversibility_acknowledged": true,
  "authorized_by": "REPLACE_WITH_DATA_STEWARD_NAME",
  "authorized_at": "2026-08-04T12:00:00-04:00",
  "license": "REPLACE_WITH_EXACT_CANONICAL_LICENSE_FROM_PLAN",
  "release_fingerprint_sha256": "REPLACE_WITH_EXACT_FINGERPRINT_FROM_PLAN"
}
```

Keep the authorization, token, and state as three distinct files outside the
package, each owned by the current user with exact mode `0600`. The token needs
both Zenodo `deposit:write` and `deposit:actions`. Publication requires the
explicit `--publish` action:

```bash
python3 bin/zenodo_breast_ihc_publish.py \
  --package-dir /path/outside/repository/breast-ihc-upload-package \
  --metadata /path/outside/repository/zenodo-metadata.json \
  --state /path/outside/repository/private-release-material/zenodo-state.json \
  --deposition-id REPLACE_WITH_EXACT_DEPOSITION_ID \
  --authorization /path/outside/repository/private-release-material/publication-authorization.json \
  --token-file /path/outside/repository/private-release-material/zenodo-actions-token \
  --publish
```

Immediately before the one permitted publish request, the command atomically
records `publish-intent` in the state. It does not retry that POST. If the
outcome is ambiguous, rerunning the same command performs read-only
reconciliation and will not issue a second publish request. The state becomes
`published` only after the published deposition and anonymous public record
both match the exact metadata and 55-file size/MD5 roster, and the public DOI
and URLs have been verified.

## Dataset publication status

The raw-only example is published under CC BY 4.0 at
[Zenodo record 21797920](https://zenodo.org/records/21797920), dataset DOI
[`10.5281/zenodo.21797920`](https://doi.org/10.5281/zenodo.21797920). The exact
deposit contains 55 files: 51 case archives holding 1,901 TIFF patches, one
manifest bundle, one packaging report, and two checksum rosters, totaling
74,958,557,152 bytes. It does not contain the locally generated paper or QC
figures. Cite this DOI only for the breast-IHC
dataset and cite the TumorQuantAI software separately.

The repository support folder is `examples/breast-ihc-patches/`.
