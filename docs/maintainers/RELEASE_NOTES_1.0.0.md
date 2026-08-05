# TumorQuantAI v1.0.0

Released 2026-08-05.

TumorQuantAI v1.0.0 is the first stable release of the research workflow. It
establishes the supported v1 command-line, recorded run-provenance, and
documented required-output contracts. It does not claim clinical validation,
diagnostic performance, or tumor classification.

## Highlights

- One `tumorquantai` command covers installation, environment checks, public
  quickstarts, inspection, reproducible WSI runs, status, and portable reports.
- Docker, Singularity/Apptainer, Poetry, and Conda orchestration routes preserve
  the existing direct Nextflow and `run.sh` interfaces.
- The patch route accepts local TIFF patches through
  `--patches PATH --paper-figures --output DIR`, validates physical scale, and
  writes per-patch QC/ROI figures with scale bars, detected-cell count
  plots/tables, and failure-aware cohort aggregation.
- Failed or incomplete samples remain distinct from completed biological-zero
  samples in summaries and cohort tables.
- Published model and runtime identities remain pinned. Direct Nextflow GPU
  profiles now select the pinned GPU runtime rather than inheriting the CPU
  image.
- Public examples cover the lymphoma WSI dataset and the separate raw-only
  breast-IHC TIFF-patch dataset.

See the repository `CHANGELOG.md` for the complete change history.

## Distribution scope

This release is distributed through the GitHub source archives for tag
`v1.0.0`. No standalone PyPI package, TumorQuantAI application container, or
model weights are part of this release. The repository's Poetry entry point is
a launcher for a repository checkout and must not be represented as a
standalone workflow wheel.

Scientific execution uses separately published, immutable CPU or GPU runtime
image digests. HistoPLUS is gated, its terms are separate, and users must obtain
their own authorized access. TumorQuantAI does not redistribute HistoPLUS
weights.

The repository's declared software-license state must be read independently
from dataset licenses. The CC BY 4.0 terms of either public example dataset do
not license TumorQuantAI code, dependencies, containers, or model weights.
At release-candidate preparation time, the software is **source visible; no
reuse permission is granted by an absent license**. Publication requires the
owner to explicitly approve that state or replace it with an owner-approved
software license and corresponding metadata.

## Compatibility and reproducibility

- Existing `run.sh`, direct Nextflow, worker override, and installed-command
  routes remain supported.
- The [v1 compatibility policy](../reference/compatibility.md) defines supported
  interfaces, additive changes, deprecation, and internal interfaces.
- The lymphoma public dataset remains immutably matched to TumorQuantAI
  `v0.4.0`; v1 does not rewrite that historical dataset contract.
- The lymphoma dataset DOI is `10.5281/zenodo.21466410`.
- The breast-IHC raw-patch dataset DOI is `10.5281/zenodo.21797920`.
- Neither dataset DOI is a software DOI.
- Source MPP, target MPP, source fingerprints, sampling identity, model
  revision, runtime identity, and completion/failure state remain explicit in
  run provenance.
- Published HistoPLUS weight identity retains filename, byte size, and SHA-256,
  but private filesystem paths, device/inode numbers, and filesystem timestamps
  are intentionally absent. Downstream readers must accept those removed fields
  as unavailable.

## Release validation boundary

Local release-candidate validation completed 480 CPU-only repository tests,
shell and Python syntax checks, the structural demo, fixture inspection,
CLI routes, repository hygiene over 198 source paths, canonical CFF validation,
a strict documentation build, Dockerfile static validation, and public
pre-release metadata checks. The exact checksum-verified Nextflow 25.10.2
runtime passed configuration resolution plus discovery-only, normal
failure-aware aggregation, and all-failed-cohort stub workflows.

Normal GitHub CI remains a mandatory exact-head publication gate. Its
public-data preparation and four orchestration routes run without gated-model
inference; those checks validate workflow structure rather than biology.

Exact-v1 HistoPLUS GPU inference was not rerun during release preparation
because the host NVIDIA device was reserved for an active Nanopore/Dorado
sequencing workload. This is a documented not-run boundary, not a passing
biological validation result. The existing real-run evidence remains subject
to its recorded software, model, runtime, data, and sampling identities.

## Research-use limitations

TumorQuantAI outputs are research measurements requiring visual QC and domain
review. TumorQuantAI does not classify tumors, infer histologic or molecular
subtype, or establish marker co-expression across differently stained patches.
Users remain responsible for lawful data use, physical-scale verification,
model authorization, and review of every failed, incomplete, or excluded case.
