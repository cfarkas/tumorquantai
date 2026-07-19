# Changelog

## 0.4.0 — 2026-07-18

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
