# Curator guide for a future Zenodo dataset version

The current public dataset is Zenodo record `21466410`, DOI
`10.5281/zenodo.21466410`, dataset version v2, matched to TumorQuantAI
`v0.4.0`. Public walkthroughs use the standard direct Zenodo filenames and
generated URL/checksum lists. The compatible downloader utility also requires
no Zenodo credential.

This page is only for an authorized curator creating a **future successor
version draft**. It does not describe the current public record and does not
authorize a publication action.

## Non-negotiable boundaries

- Obtain accountable owner, governance, privacy, and rights approval before
  remote changes.
- Keep source WSI, labels, private mappings, clinical data, credentials, and
  logs outside the repository.
- Work on a verified mounted storage filesystem with restrictive permissions.
- Stage only 21 sanitized MDS files plus the authoritative public manifest.
- Require full ordered `DSI0` aggregate identity between source and sanitized
  copies, in addition to geometry and whole-file checksums.
- The helper may create/verify a restricted draft; it must not make it public.
- A future version needs an explicit dataset rights/license decision.
- Do not alter or assign the dataset DOI to TumorQuantAI software.

## Local staging

Use `bin/prepare_zenodo_mds.py --help` and reviewed, private source/mapping
paths. Its plan must report:

- exactly 21 safe public aliases and 17,370,771,968 MDS bytes for this fixed
  collection, unless a separately reviewed future version contract changes it;
- schema-version-2 public manifest;
- deterministic neutral non-pixel content;
- matching full pixel-stream aggregate checksums;
- no source markers or unexpected sidecars; and
- mode-0600 staged files and private mapping.

Review the staged public tree and private mapping separately. The private
mapping must never be uploaded.

## Remote draft

Only after local review, use `bin/zenodo_mds_deposit.py --help` with a
mode-0600 token file outside the repository. Never put a token value in a
command, environment dump, issue, or log. The tool validates trusted Zenodo
origins and cannot make a record public.

Verify the remote draft through structured API metadata:

- restricted draft state;
- exact file roster, sizes, and MD5 values;
- authoritative manifest identity;
- title, creators, description, keywords, related TumorQuantAI release, and
  research-use limitation; and
- no private mapping, model weight, token, clinical field, or source label.

## Human publication gate

Making a future record version public remains a manual owner/governance action
outside these tools. Before that decision, complete an independent privacy and
rights review, reproduce public download/conversion checks from the draft,
verify one-slide technical acceptance when authorized, and record exact
software/container/model identities.

After a future version is public, update
[dataset consistency](maintainers/DATASET_CONSISTENCY.md), tutorials, tests,
and release notes in one reviewed change. Ordinary quickstart must continue to
use an immutable version-specific record rather than an ambiguous latest
concept record.
