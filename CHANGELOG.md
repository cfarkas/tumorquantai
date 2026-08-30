# Changelog

## Unreleased

- Documented the complete breast-IHC identity chain, the 51-case linkage audit,
  explicit-crosswalk rule, controlled mapping CSV, privacy boundary, and
  authoritative retained v2 run without publishing direct identifiers.
- Added the versioned IHC v2 expected-brown optical-density cone, preventing
  magenta and near-neutral gray pixels from being silently counted as DAB.
  Nuclear-marker CSVs preserve the unconstrained HED percentages and H-scores
  as audit fields, while `--unconstrained-dab-color` explicitly reproduces the
  earlier measurement in a new analysis signature.
- Redesigned the per-patch HistoPLUS paper figure with a compact layout inspired
  by [STTT 2026 Figure
  6](https://www.nature.com/articles/s41392-026-02734-0#Fig6) and [Figure
  7](https://www.nature.com/articles/s41392-026-02734-0#Fig7), plus an external,
  layout-versioned text legend.
  The presentation version remains outside the scientific worker processing
  signature, preserving the legacy contract when a worker directly reuses its
  persistent output.
- Required the legend when a completion summary records the current layout while
  retaining the worker-level legacy exception for completed outputs without a
  layout version. This is not a Nextflow cache guarantee: staged worker-code or
  configuration changes can invalidate `PROCESS_SLIDE` after a software upgrade.
  Use a new output directory or a deliberate rerun when redesigned legacy figures
  are required and the original Nextflow cache cannot be reused.
- Clarified that stable patch mode reports HistoPLUS cell-type predictions; it
  does not score breast markers, infer receptor status, or measure cell-level
  co-expression across separately stained images.

## 1.0.0 — 2026-08-05

- Established the supported v1 command-line, run-provenance, and documented
  required-output contracts, with additive and corrective changes governed by
  the published compatibility policy.
- Added the `tumorquantai` command with installation routes for Docker,
  Singularity/Apptainer, Poetry, and Conda; offline doctor and demo commands;
  model-free inspection; safe smoke/fast/full presets; failure-aware status;
  portable reports; and a one-public-slide quickstart.
- Added the exact `--patches PATH --paper-figures --output DIR` TIFF route,
  per-input physical-scale validation, QC/ROI figures with scale bars,
  detected-cell count plots/tables, and failure-aware cohort aggregation.
- Added privacy-sanitized breast-IHC release preparation, deterministic ZIP64
  packaging, resumable large Zenodo uploads, one-action publication, and
  public-record reconciliation. The raw-only dataset is published separately
  as Zenodo record `21797920`, DOI `10.5281/zenodo.21797920`.
- Rebuilt the README and MkDocs site into task-oriented starts, tutorials,
  how-to guides, explanations, reference material, troubleshooting, and
  maintainer checks. The lymphoma tutorial remains matched to immutable
  software release `v0.4.0` and dataset DOI `10.5281/zenodo.21466410`.
- Added exact-head CI for documentation, installation, public-slide
  preparation, and Docker/Singularity/Poetry/Conda orchestration routes.
- Corrected direct Nextflow GPU profiles to select the pinned GPU runtime
  digest while preserving explicit container overrides.
- Adopted the MIT License for TumorQuantAI repository code and documentation;
  third-party software, model artifacts, containers, and datasets retain their
  separate licenses or terms.
- Preserved `run.sh`, direct Nextflow, worker overrides, scientific/output
  invariants, legacy token-file compatibility, and explicit
  failed-sample-versus-zero semantics.
- Hardened published weight provenance: filename, byte size, and SHA-256 remain,
  while private paths, device/inode numbers, and filesystem timestamps are no
  longer emitted.

## 0.4.0 — 2026-07-20

- Added the strict schema-version-2 raw-MDS lymphoma manifest and assembled a
  locally validated restricted-draft upload payload; no remote draft was created.
- Added trusted-origin, private-permission, resumable MDS downloads that safely
  expand from one to four to all 21 slides.
- Added an open MDS-to-BigTIFF converter with source/output hashes, geometry and
  MPP validation, atomic state, and safe interruption recovery.
- Added fail-closed 1/4/21 tutorial checkpoints, local-weight instructions, and
  an immutable `v0.4.0` software/dataset contract.
- Hardened sanitization resume, private mappings, draft state fingerprints,
  remote metadata checks, and exact 21-file/byte release invariants.
- Expanded pytest and CI coverage for manifest privacy, mocked Zenodo draft
  creation, real TIFF creation, resume, and tamper rejection.

## 0.3.0 — 2026-07-16

- Added an OncoTracer-style MkDocs Material site, a concise repository landing
  page, and task-based guides for first runs, MPP, run modes, recovery, and
  terminology.
- Renamed the project and public documentation to TumorQuantAI while retaining
  LazySlide and HistoPLUS as the named upstream engine and model.
- Added a privacy-sanitized lymphoma WSI Zenodo preparation, resumable download,
  integrity-verification, and guarded deposition workflow.
- Added an end-to-end tutorial covering discovery, a one-slide 1% smoke test,
  a four-slide 10% run, aggregation, spatial reports, and cohort PowerPoint.
- Added real-WSI acceptance documentation and public alias-only examples.
- Expanded automated checks for documentation, release metadata, privacy
  boundaries, and Zenodo tooling.
- Separated verified physical source MPP from target model MPP and included both
  in conversion, processing-signature, and result provenance.
- Added read-only local HistoPLUS weight-file support with content hashing.
- Added a validated 2 GB Docker shared-memory default after the four-slide
  acceptance run exposed DataLoader failures under Docker default `/dev/shm`.
- Added self-contained flat-document staging and a publication-time rejection
  of unresolved metadata or documentation placeholders.

## 0.2.0 — 2026-07-15

- Replaced the prototype worker with the production LazySlide/HistoPLUS engine.
- Changed Nextflow from one monolithic directory task to collision-safe
  per-slide tasks with fingerprints, retries, and independent cache state.
- Added strict L0 discovery, sample sheets, output-tree pruning, and dry-run
  manifests.
- Added validated cell-type-by-sample counts/fractions, tidy counts, and a
  failed-sample audit.
- Bundled spatial/embedding and cohort PowerPoint report tools.
- Added a non-root container, pinned model-wrapper commit, explicit CPU/GPU
  build tags, host doctor, tests, CI, schemas, and public documentation.
- Added privacy-aware clinical/HistoPLUS linkage, full private merged-data export,
  descriptive outcome stratification, and repeated nested-CV model comparisons.
- Added explicit `--full` (100%) and `--fast` (10% default) launcher modes with
  conflict checks and separate-output guidance.
- Pinned the HistoPLUS model revision and hardened L2, pyramidal-cache, optional
  artifact, and atomic completion-marker provenance for exact resume behavior.
- Hardened explicit sample IDs, manifest scope, zero-detection semantics, exact
  sampling resume, GPU concurrency, immutable images, and portable metadata paths.
- Removed the destructive GitHub publishing helper and project-specific command
  playbook.

## 0.1.0

- Initial prototype.
