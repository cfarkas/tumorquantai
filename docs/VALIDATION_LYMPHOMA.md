# Lymphoma tutorial validation

## Dataset selection

| Check | Result |
| --- | --- |
| H&E MDS discovered | 23 |
| Exact binary duplicates | 0 |
| Structurally corrupt source excluded | 1 |
| Probable repeat acquisition excluded | 1 |
| Final selected MDS files | 21 |
| Final selected MDS bytes | 17,370,771,968 |
| Source MPP | 0.261780 µm/pixel |
| Special stains and unrelated project data | Excluded |

Every selected source previously opened and exported with ASlide. The original
MDS files contain internal label and metadata streams, so filename aliasing
alone was not considered sufficient privacy sanitization.

## Sanitized staging

All 21 selected files are staged locally with mode 0600. Preparation profile
`pixel-preserving-nonpixel-redaction-v2`:

1. creates an independent copy;
2. writes deterministic neutral replacements to every non-`DSI0` stream;
3. confirms the OLE stream roster did not change;
4. computes an ordered streaming aggregate SHA-256 over every `DSI0` stream
   name, length, and byte in both copies and requires equality;
5. retains deterministic per-level pixel samples as a supplemental fingerprint;
6. reopens the staged MDS and verifies levels and dimensions;
7. scans ASCII and UTF-16 source markers; and
8. records final whole-file SHA-256 and MD5 checksums.

On resume, label, macro, and metadata streams must exactly match the
deterministic neutral replacements. A readable but non-neutral image is
rejected. Every `DSI0` byte contributes to the full aggregate preservation
digest; the sampled fingerprint is retained only as an additional diagnostic.

The schema-version-2 public manifest has 21 rows, and the private source
mapping has 21 rows. The latter is mode 0600 and must never be uploaded.

## MDS reader and TIFF conversion

The open reader recovered all nine levels and the same dimensions as ASlide
for the pilot sanitized slide. ASlide also opened the sanitized copy and read a
test region without external sidecars.

The real alias-022 conversion produced:

| Level | Dimensions | Reported MPP |
| --- | --- | --- |
| L0 | 37,888 × 26,112 | 0.2617808 |
| L2 | 9,728 × 6,656 | 1.0471209 |

A central 512 × 512 L0 pixel block was byte-identical to the previous ASlide
export (`SHA-256
93cdd0a8e499425b1081ac4676184fcabc518a9fce1c654e03cd5d1a5b182a08`).

The converter now binds each output to the source MDS hash, geometry, MPP,
compression settings, TIFF hash, and converter version. Interrupted conversion
can reuse only entries that pass those checks. The generated sample sheet is
derived from verified complete L0/L2 pairs.

## Automated tests

The test suite covers:

- strict schema, checksum, alias, path, and extra-column rejection;
- trusted Zenodo origins and private token/file permissions;
- exact public/private manifest linkage;
- fixed 21-file/byte release invariants;
- restricted draft metadata and end-to-end mocked draft upload;
- deterministic neutral label/macro generation and full `DSI0` aggregate
  preservation;
- MDS level ordering and canonical sample IDs;
- real TIFF creation from a synthetic pixel source;
- conversion interruption/resume and checksum-tamper rejection; and
- fail-closed 1/4/21 expected slide counts.

Repository CI installs `pytest` and `olefile` and runs the full pytest suite.

## Existing inference acceptance

Aliases 022, 002, 006, and 016 previously completed a 10% sampled
TumorQuantAI run and aggregation. Alias 022 completed the one-slide smoke path.
These are technical workflow checks, not clinical validation. No new full
21-slide inference was run because it can take days.

## Remaining external release checks

- provide a Zenodo token with `deposit:write`;
- provide the exact authorized dataset license before publication;
- create and verify the restricted, unpublished Zenodo draft;
- complete accountable human ownership, governance, and privacy review;
- publish only after that authorization;
- run download → conversion → one/four-slide acceptance from the final record;
  and
- record the exact TumorQuantAI tag/commit, container, and model identity.
