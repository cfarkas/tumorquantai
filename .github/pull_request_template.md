## Problem

<!-- What user or maintainer problem does this solve? -->

## Before/after journey

<!-- Give the shortest reproducible workflow before and after. -->

## Implementation

<!-- Key decisions, especially CLI/output/provenance changes. -->

## Compatibility and scientific safeguards

- [ ] `run.sh`, direct Nextflow, and worker overrides remain supported
- [ ] Model/container identity, fingerprints, MPP, sampling/seed, resume, and
      failure audit semantics are preserved
- [ ] Failed/incomplete samples cannot become biological zero
- [ ] Output/schema changes are absent or have a tested migration

## Validation

<!-- List exact commands and pass/fail/not-run results. -->

- [ ] Existing and new Python tests
- [ ] CLI help/demo/inspection/status/report tests
- [ ] Shell syntax and Nextflow configuration/stub tests
- [ ] Strict MkDocs build and internal-link/placeholder checks
- [ ] `git diff --check` and secret/forbidden-artifact scan

## Real-data status

<!-- Separate download, checksum, conversion, inspection, and inference.
State NOT RUN with the prerequisite when gated access/resources were absent. -->

## Safety

- [ ] No tokens, weights, WSI, PHI, patient tables, private manifests, large
      outputs, caches, or generated site files are included
- [ ] Any local data/work paths were on a verified storage mount
- [ ] Screenshots are synthetic or clearly permitted for redistribution

## Manual follow-ups

<!-- Genuine owner governance/release decisions only. Do not merge or release automatically. -->
