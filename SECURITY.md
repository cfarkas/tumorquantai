# Security policy

## Report privately

Use GitHub's private vulnerability reporting feature when it is enabled for
this repository. Do not open a public issue containing an access token, model
weight, raw WSI, PHI, patient identifier, private path, private manifest,
patient-level table, or sensitive log. No unverified email address is provided.

For a non-security bug, use the bug template only after reviewing and
redacting `./tumorquantai doctor --json` and
`./tumorquantai status OUTPUT --json`.

## Credential, model, and data safety

- Prefer `TUMORQUANTAI_HF_TOKEN_FILE` or the mode-0600
  `~/.config/tumorquantai/hf_token`. The legacy path remains supported.
- Never put a token value in command arguments, a sample sheet, notebook,
  issue, log, report, container image, or Git.
- Keep authorized local weights outside the repository/results and mount them
  read-only. TumorQuantAI records identity, not contents.
- Treat slide names, coordinates, thumbnails, overlays, manifests, reports,
  logs, and matrices as potentially sensitive.
- Keep source input read-only and use neutral aliases.
- Verify mounts/free space before downloads, conversion, or inference. Do not
  alter Docker storage/mount configuration as a troubleshooting shortcut.

Doctor/report redaction reduces accidental disclosure but is not a guarantee;
review every attachment before sharing.

## Supported versions

Security fixes target the current default branch. For reproducible analyses,
pin a reviewed TumorQuantAI commit/release, immutable container digest, and
immutable HistoPLUS revision. Include those identities in a private report.
