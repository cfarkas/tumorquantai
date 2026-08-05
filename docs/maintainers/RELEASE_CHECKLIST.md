# Release checklist

Use this checklist for the `v1.0.0` release candidate and future releases.
Release preparation does not itself authorize a merge, tag, or publication.

## Code and compatibility

- [ ] Existing `run.sh`, direct Nextflow, worker overrides, and automation pass.
- [ ] Scientific invariants remain covered: immutable model/container identity,
      source fingerprints, deterministic sampling, source/target MPP,
      fail-closed scale, per-slide isolation, failure audit, and zero semantics.
- [ ] Output filenames/schemas are unchanged or a tested migration is present.
- [ ] `tumorquantai --help` and all subcommand help pass.
- [ ] Demo, fixture inspection, status/report fixtures, and preset mapping pass.

## Documentation

- [ ] README demo works from a clean clone in three commands.
- [ ] Generated/verified CLI reference matches `--help`.
- [ ] `python -m mkdocs build --strict` passes.
- [ ] Internal links and output filenames are checked.
- [ ] No draft-era publication text or unresolved placeholders remain.
- [ ] Citation separates software, dataset, LazySlide, and HistoPLUS.
- [ ] `cffconvert --infile CITATION.cff --validate` passes with pinned
      `cffconvert==2.0.0`; the dataset DOI is not assigned to the software.
- [ ] The exact MIT `LICENSE`, CFF/package identifiers, README, and release-note
      wording remain aligned.

## Dataset consistency

- [ ] Record `21466410` and DOI `10.5281/zenodo.21466410` resolve.
- [ ] Dataset metadata still identifies software `v0.4.0` as its matched engine.
- [ ] Alias 022 is `125350400` bytes with source MPP `0.261780`.
- [ ] Repository manifest matches the authoritative record manifest.
- [ ] Public quickstart selects only alias 022 and requires no Zenodo token.
- [ ] Breast-IHC record `21797920` and DOI `10.5281/zenodo.21797920`
      resolve with 55 unique files totaling `74,958,557,152` bytes under
      CC BY 4.0.
- [ ] Both dataset DOIs remain separate from the software citation and license.

## Safety and CI

- [ ] Tests require no GPU, gated model, real WSI, or public-data download.
- [ ] Pre-release external checks pass with
      `python scripts/check_external_resources.py --pre-release`.
- [ ] No tokens, weights, WSI, PHI, patient tables, large outputs, or caches are
      tracked.
- [ ] `git diff --check` and forbidden-artifact/secret scans pass.
- [ ] Real one-slide validation status is stated exactly; not-run prerequisites
      are not reported as test failures.

## Release action

- [ ] Owner reviews changelog/version and authorizes the release.
- [ ] The owner-approved MIT software-license decision is recorded exactly.
- [ ] Distribution scope is explicit; `v1.0.0` is a GitHub source release
      unless separately validated standalone packages or containers exist.
- [ ] Create a tag only after all above checks and normal review.
- [ ] After publication, the default external check reconciles the public
      non-draft/non-prerelease GitHub release for the new tag.
- [ ] Do not assign the dataset DOI to software.
- [ ] Merge, tag, and publish only with explicit owner authorization and the
      exact-head checks above; never infer authorization from a usability PR.
