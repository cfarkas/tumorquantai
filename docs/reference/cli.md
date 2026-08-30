# CLI reference

`tumorquantai` is the main command-line interface. It wraps the existing
`run.sh` and Nextflow workflow rather than reimplementing inference. The
installed command's `--help` output is authoritative.

## Synopsis

```text
tumorquantai install (--docker | --singularity | --poetry | --conda)
                      [--prefix DIR | --system]
                      [--no-nextflow-download] [--dry-run]

tumorquantai doctor [--input PATH] [--output PATH] [--work-dir PATH]
                     [--online] [--json]

tumorquantai demo [--output DIR]

tumorquantai convert INPUT --output DIR
                       [--manifest CSV] [--levels INT ...]
                       [--sample-id ID]... [--expected-count INT]
                       [--source-mpp FLOAT]
                       [--resume | --overwrite] [--dry-run]

tumorquantai inspect INPUT --output DIR
                        [--source-mpp FLOAT] [--sample-sheet CSV]
                        [--pattern GLOB]... [--include GLOB] [--exclude GLOB]

tumorquantai run INPUT --output DIR
                    [--preset smoke|fast|full] [--source-mpp FLOAT]
                    [--sample ID]
                    [--docker | --singularity | --conda]
                    [--profile auto|gpu|cpu|local | --cpu | --gpu]
                    [--seed INT] [--sample-sheet CSV]
                    [--pattern GLOB]... [--include GLOB] [--exclude GLOB]
                    [--work-dir DIR]
                    [--dry-run] [--no-resume]
                    [--local-weight FILE] [--token-file FILE]
                    [-- EXPERT_NEXTFLOW_ARGS]

tumorquantai status OUTPUT [--json]
tumorquantai report OUTPUT [--json]

tumorquantai quickstart [--output PATH]
                         [--dry-run | --download-only | --convert-only |
                          --no-inference]
                         [--docker | --singularity | --conda]
                         [--profile auto|gpu|cpu|local | --cpu | --gpu]
                         [--seed INT] [--local-weight FILE]

tumorquantai --patches TIFF_PATH --paper-figures --output DIR
             [--source-mpp FLOAT]
             [--docker | --singularity | --conda]
             [--profile auto|gpu|cpu|local | --cpu | --gpu]
```

## Commands

### `install`

Installs the global `tumorquantai` command, creates an isolated launcher
environment, records the cloned repository location, and prepares one execution
method. Choose exactly one route:

- `--docker`: install the command and validate Docker.
- `--singularity` or `--apptainer`: install the command and validate Singularity/Apptainer.
- `--poetry`: create the Poetry-managed launcher; Docker is its default scientific backend.
- `--conda`: install the command and validate Miniforge/Conda.

Additional options:

- `--prefix DIR`: install under a user-selected prefix; the default is `~/.local`.
- `--system`: install under `/usr/local` and `/etc`, normally with `sudo`.
- `--no-nextflow-download`: keep an administrator-provided Nextflow installation.
- `--dry-run`: print the installation plan without changing files.

### `doctor`

Offline by default. Always checks the operating system, architecture,
Java/Nextflow, Docker CLI/daemon, NVIDIA visibility, CPU fallback, writable
caches, and configured model readiness. Without paths, its storage/cache probe
uses the current path. `--input` checks the chosen input; `--output` plus
optional `--work-dir` checks the intended output/work mount and free space.
`--online` checks pinned public release, dataset, and model metadata; it does
not prove that an account/token is authorized. `--json` omits secrets and
minimizes sensitive paths.

### `demo`

Runs bundled fixtures and a stub worker. It needs no model, GPU, Docker,
credentials, or public-data download. Every result is labelled structural and
non-biological.

### `convert`

Runs the maintained Motic MDS converter through the Python environment created by `tumorquantai install`. It verifies manifest-bound inputs, writes resumable L0/L2 TIFF files and `samples.csv`, and removes the need for a separate tutorial virtual environment.

### `inspect`

Discovers candidate primary slides/companions, duplicate risks, format/pyramid
metadata when available, source MPP or its absence, and storage estimates.
Writes a reviewable manifest without HistoPLUS inference.

### `run`

Maps `smoke` to one selected seeded 1% slide and fail-fast behavior, `fast` to
seeded 10% by default, and `full` to 100% of detected tissue tiles. Resume is
on unless `--no-resume` is used. The expanded command is printed with secrets
redacted. Default work is `OUTPUT/.tumorquantai-work`.

`--cpu` forces CPU execution and `--gpu` selects the NVIDIA execution profile;
the two flags cannot be combined. They are concise aliases for `--profile cpu`
and `--profile gpu`. The existing `--profile auto|gpu|cpu|local` option remains
backward compatible. Run `doctor` before GPU work: the CLI checks host and
container visibility, while the worker retains its established device
resolution if CUDA later becomes unavailable.

Use `--token-file` only with a token file, never a token value. `--local-weight`
references an authorized local file read-only. Arguments after `--` are an
expert Nextflow-parameter escape hatch. Existing launcher options remain
available by invoking `run.sh` directly; `run.sh --help` and direct Nextflow
remain supported.

### `status`

Reads existing metadata, per-sample summaries, and the aggregation audit.
Reports completed, failed, incomplete, excluded, and pending samples, and
prints exact local filesystem paths for the first log and resume command when
available. This human output is for the machine running the workflow; redact it
before sharing.

### `report`

Writes a self-contained `START_HERE.html` plus JSON summary. Links are relative
and included only when the target exists. User-derived text is HTML-escaped;
secret contents, credential locations, and absolute sensitive paths are
excluded. `status --json` uses the same share-oriented path redaction.

### `quickstart`

Prepares only public alias 022 from Zenodo record 21466410, converts L0/L2,
inspects MPP `0.261780`, and optionally runs seeded 1% inference when authorized
model access is already configured. It never expands to four or 21 slides.
When `--output` is omitted, the output is created beside the cloned repository
as `tumorquantai-quickstart-one-wsi`.

### Package-native breast IHC marker quantification

The `ihc` command group quantifies ER, PR, HER2, and Ki-67 staining without
HistoPLUS access. It reads the published case ZIPs directly, validates the
manifest and decoded pixels, writes QC overlays and auditable tables, and
resumes matching patch checkpoints:

```bash
tumorquantai ihc quantify /path/to/breast-ihc-downloads \
  --manifest /path/to/manifest/patch_manifest.csv \
  --output /path/to/breast-ihc-results \
  --workers 12 \
  --save-cells
```

`tables/tumorquantai_marker_values.csv` is the concise 51-row wide export.
`tables/case_marker_measurements.csv` is the long case-marker audit table.
Missing markers are empty and explicitly marked `unavailable`; they are never
converted to zero. The default v2 engine requires the expected brown-DAB
optical-density ordering and exports the unconstrained HED value separately.
For an explicit earlier-method reproduction, use
`--unconstrained-dab-color` with a new output directory. Expert color-cone
controls are `--minimum-dab-color-margin-od` (default `0.02`) and
`--minimum-dab-color-ratio` (default `0.15`).

See [IHC v1-to-v2 migration](ihc-v2-migration.md) before comparing old and new
result directories.

The optional private agreement route first creates an English, six-column
minimum marker table and then calculates marker-wise concordance:

```bash
tumorquantai ihc anonymize-clinical /private/path/review.xlsx \
  --sheet "Biopsias finales incluidas" \
  --linkage /private/path/private-linkage.csv \
  --clinical-id-column Biopsia \
  --linkage-id-column case_id \
  --output /private/path/pathologist-markers-pseudonymized.csv

tumorquantai ihc compare /path/to/breast-ihc-results \
  --pathologist-csv /private/path/pathologist-markers-pseudonymized.csv \
  --output /private/path/agreement \
  --bootstrap-iterations 10000
```

If reviewed identifiers require correction, `--identifier-crosswalk` accepts
only an exact-mode-`0600`, one-to-one CSV with `linkage_id,clinical_id`.
TumorQuantAI never uses marker values to infer identity. The wide paired case
CSV remains pseudonymized health data and must stay under controlled access.
`concordance_metrics.csv` contains the complete aggregate kappa, error,
correlation, concordance, category-margin, and specific-agreement report.

See the [complete marker-quantification tutorial](../tutorials/breast-ihc-patches.md).

### Optional HistoPLUS raw TIFF cell typing

`--patches TIFF_PATH` selects the dedicated raw-TIFF patch route. `TIFF_PATH`
may identify an authorized local TIFF patch input or collection prepared for
the example. This route is invoked at the top level rather than through the
`run` subcommand:

```bash
# Process all discovered TIFF patches on CPU and render paper/QC figures.
tumorquantai --patches /path/to/breast-ihc-tiff-patches \
  --paper-figures \
  --output /path/to/breast-ihc-patch-results \
  --cpu
```

Patch mode is full processing: it schedules 100% of the discovered patch
inputs and does not apply the `smoke` or `fast` percentage-sampling presets.
`--paper-figures` requests the publication-oriented PNG/PDF exports in addition
to the ordinary per-input coordinates, counts, summary, and visual QC outputs.
The established `celltypes_paper_figure.png`/`.pdf` filenames now use a compact
layout inspired by [STTT 2026 Figure
6](https://www.nature.com/articles/s41392-026-02734-0#Fig6) and [Figure
7](https://www.nature.com/articles/s41392-026-02734-0#Fig7): all HistoPLUS cell-type counts and
within-input percentages at left, with the overview and QC inset using the
configured cell-type overlay stacked at right.
`celltypes_paper_figure_legend.txt` stores the sample ID, panel details,
count source/denominator, scale/ROI/model provenance, and research-use caveats.
For a completion summary recording the current layout version, the legend is
required for completion/resume reuse. The layout version is outside the
scientific worker processing signature, so direct reuse of the same persistent
worker output preserves the legacy completion contract for a summary without a
layout version. This is not a top-level resume guarantee: Nextflow also keys the
staged worker code and configuration, so an upgrade may invalidate
`PROCESS_SLIDE` and re-enter inference. Inspect the intended command with
`--resume --dry-run`; confirm that the expanded Nextflow command uses `-resume`
and the original work directory. Preserve the exact software/work cache, or use
`--cpu` when reuse is uncertain. To obtain redesigned legacy figures, choose a
new output directory or a deliberate rerun.

This stable route performs HistoPLUS cell typing. It does not quantify breast
marker staining, infer receptor status, or measure co-expression across
separately stained images. The layout reference is visual only and imports no
external method, performance result, or biological claim.

Every patch must have a defensible physical scale. TumorQuantAI uses reliable
embedded TIFF micrometres-per-pixel metadata when present and fails closed when
physical scale cannot be established. In that case, pass a verified value with
`--source-mpp FLOAT`. A single override is appropriate only when every selected
patch has the same source scale; split mixed-scale inputs into separate runs or
use per-input verified metadata.

For mixed embedded scales, `tumorquantai status`, shareable JSON status,
`START_HERE.html`, and the text run summary preserve the distinct per-input MPP
values and the `per-input embedded TIFF metadata` provenance. Review these
reported values before interpreting scale-dependent outputs.

`--cpu` forces CPU inference. The same gated HistoPLUS authorization and model
provenance requirements apply as for WSI inference. Normal resume requires the
same output and Nextflow work directory, but cache reuse is not guaranteed after
software or configuration changes. Preview the complete command with
`--resume --dry-run` before removing `--dry-run`; do not reuse one output
directory with different patch sets or MPP values.

Breast IHC presentation categories are computational receptor-profile
pre-score groups, not diagnoses, intrinsic subtypes, treatment groups, or
pathologist sign-out. An equivocal HER2 pre-score remains unresolved and
requires the appropriate independent clinical work-up.

The public raw-only breast-IHC example dataset is available under CC BY 4.0 at
[Zenodo record 21797920](https://zenodo.org/records/21797920), with dataset DOI
[`10.5281/zenodo.21797920`](https://doi.org/10.5281/zenodo.21797920). Its 55
files comprise 51 case archives containing 1,901 TIFF patches plus four
auxiliary files: one manifest bundle, one packaging report, and two checksum
rosters (74,958,557,152 bytes total). Generated paper and QC figures are not
part of the deposit. This is a dataset DOI, not a TumorQuantAI
software DOI. See [the complete patch tutorial](../tutorials/breast-ihc-patches.md).

### Offline release-draft utility

`bin/prepare_breast_ihc_patch_release.py` is a separate, local-only sanitizer;
it is not an inference command. It reads a private source-selection CSV with
the required columns `case_id`, `marker`, `field_id`, `source_path`, `include`,
`microns_per_pixel`, and `mpp_provenance`. The manifest's per-image MPP is
preserved in each sanitized TIFF rather than replaced by one collection-wide
value.

The MPP must be externally audited rather than copied uncritically from source
TIFF tags, which may be missing or wrong. `mpp_provenance` accepts safe English
categories for measured scale-bar calibration, documented magnification
extrapolation, or externally verified calibration. The sanitizer canonicalizes
known values and publishes only the canonical value in `patch_manifest.csv`;
arbitrary provenance text is rejected.

Source TIFFs may omit `Orientation` or use its default top-left value. A
non-default TIFF orientation is rejected rather than silently transformed.

Keep the source manifest, alias secret, and private linkage outside the
repository and the public staging directory. The alias secret must be a
current-user-owned regular file of at least 32 random bytes, exact mode `0600`,
with no symlink or additional hard link. The private linkage is also created
with mode `0600` and must never be included in the public draft.

Run the utility with `--dry-run` first, using new output and linkage targets:

```bash
# Validate and plan the offline draft before creating any output.
python3 bin/prepare_breast_ihc_patch_release.py \
  --source-manifest /path/outside/repository/private-source-selection.csv \
  --alias-secret-file /path/outside/repository/private-release-material/alias-secret.bin \
  --public-output /path/outside/repository/breast-ihc-public-draft \
  --private-linkage /path/outside/repository/private-release-material/private-linkage.csv \
  --expected-cases REPLACE_WITH_INCLUDED_CASE_COUNT \
  --expected-files REPLACE_WITH_INCLUDED_TIFF_COUNT \
  --dry-run
```

After the dry run passes, repeat the identical command without `--dry-run` to
create the local draft. Sanitization strips non-allowlisted TIFF metadata,
fully decodes source and output images to verify identical RGB pixels, embeds
and re-verifies each row's MPP, and writes manifests, counts, checksums, and a
validation report. It does not detect visible identifiers burned into pixels.

This utility has no network, deposit, upload, or publication capability. See the
[release-draft procedure](../maintainers/breast-ihc-dataset-release.md#1-prepare-an-offline-release-draft).

### Deterministic local release packaging

`bin/package_breast_ihc_patch_release.py` validates a completed sanitized draft
and creates one deterministic ZIP64 archive per case plus four auxiliary upload
files. The source is retained unchanged, and the new package directory must be
outside the repository and separate from the source draft.

Run the mandatory dry run with exact roster counts first:

```bash
# Validate the sanitized draft and estimate additional disk use without writing.
python3 bin/package_breast_ihc_patch_release.py \
  --source-draft /path/outside/repository/breast-ihc-public-draft \
  --package-output /path/outside/repository/breast-ihc-upload-package \
  --expected-cases REPLACE_WITH_SANITIZED_CASE_COUNT \
  --expected-files REPLACE_WITH_SANITIZED_TIFF_COUNT \
  --dry-run
```

After it passes, repeat the identical command without `--dry-run` to create the
local package. For this exact cohort, the roster is 51 cases and 1,901 TIFFs,
so the packager creates 51 case archives plus the manifest bundle,
`packaging_report.json`, `SHA256SUMS`, and `MD5SUMS`: 55 upload files.

Case archives use forced ZIP64 with `ZIP_STORED`. The utility validates the
exact sanitized roster and checksums, then verifies each written ZIP member's
roster, metadata, size, CRC32, SHA-256, and MD5 and the final upload checksum
roster. It also validates canonical MPP provenance and fully decodes each
sanitized TIFF to recompute and compare its decoded-RGB SHA-256. Retaining the
sanitized source means packaging duplicates the stored TIFF bytes and needs the
additional disk space reported by the dry run.

Archive-byte determinism is scoped to identical validated inputs and the same
supported packager tool/runtime. Fixed ZIP metadata makes source filesystem
timestamps and modes irrelevant, but no cross-version guarantee is made for
arbitrary Python or ZIP implementations.

The packager has no network, deposit, upload, or publication capability.
Zenodo's default limits are 50 GB and 100 files per record. The published
cohort's 55 files total 74,958,557,152 bytes and therefore required additional
record storage while remaining within the file-count limit. New releases still
require measured-size and quota checks plus independent privacy, governance,
and publication review. See the
[local packaging procedure](../maintainers/breast-ihc-dataset-release.md#2-package-the-sanitized-draft-locally).

### Draft-only breast-IHC Zenodo uploader

`bin/zenodo_breast_ihc_deposit.py` accepts exactly the verified 55-file core
package for the 51-case, 1,901-patch release. Its `--plan` mode performs the
complete local validation without reading a token or using the network:

```bash
python3 bin/zenodo_breast_ihc_deposit.py \
  --package-dir /path/outside/repository/breast-ihc-upload-package \
  --metadata /path/outside/repository/zenodo-metadata.json \
  --state /path/outside/repository/private-release-material/zenodo-state.json \
  --plan
```

Network modes require a mode-`0600` token file with `deposit:write`, and accept
only `https://zenodo.org/api` or `https://sandbox.zenodo.org/api`. Use
`--create-only` to establish the open-access draft without uploading while a
quota request is pending. For additional storage, open that specific draft in
Zenodo, use **Manage storage** to allocate the approved quota to the draft, and
select **Apply**; account-level approval alone is not enough. A normal run
uploads or resumes by size and MD5. Each bucket upload attempt is one PUT; after
a failure or ambiguous response, the command reconciles the exact remote
filename/size/MD5 roster and retries only when the target is confirmed absent.
Pending or mismatched files stop the run. Packages above 50 GB also require the
confirmed total allocation through `--confirmed-quota-bytes`. The state is
mode `0600` and fingerprint-bound. There is no publish option. See the
[draft upload procedure](../maintainers/breast-ihc-dataset-release.md#3-create-or-resume-the-open-zenodo-draft).

### Publish-only breast-IHC Zenodo command

`bin/zenodo_breast_ihc_publish.py` publishes only an existing, fully uploaded
draft created by the command above. It requires the exact deposition ID, the
fingerprint-bound mode-`0600` state, an independent exact-schema mode-`0600`
authorization, and a distinct mode-`0600` token with `deposit:write` and
`deposit:actions`. Exactly one of `--plan` or `--publish` is required.

```bash
python3 bin/zenodo_breast_ihc_publish.py \
  --package-dir /path/outside/repository/breast-ihc-upload-package \
  --metadata /path/outside/repository/zenodo-metadata.json \
  --state /path/outside/repository/private-release-material/zenodo-state.json \
  --deposition-id REPLACE_WITH_EXACT_DEPOSITION_ID \
  --plan
```

The plan reads no token and uses no network. The explicit `--publish` form also
requires `--authorization` and `--token-file`. It revalidates the local package,
state, editable remote draft, open metadata, and exact 55-file size/MD5 roster,
then sends one non-retried publish action. It verifies the published deposition,
anonymous public record, DOI, and URLs before atomically marking the state
published. See the
[publication procedure](../maintainers/breast-ihc-dataset-release.md#4-publish-the-independently-authorized-draft).

## Advanced compatibility

`./run.sh`, direct `nextflow run main.nf`, existing worker-script overrides,
and existing automation remain supported. See [advanced tools](../TOOLS.md).
