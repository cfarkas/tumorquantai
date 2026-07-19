# Security policy

## Reporting

Report security issues privately to the repository owner through GitHub's
private vulnerability reporting feature when available. Do not open a public
issue containing an access token, patient identifier, private path, or WSI.

## Data and credential safety

- Use a read-only Hugging Face token and store it outside the repository.
- Prefer `HF_TOKEN` or a mode-0600 token file; never pass the token value in a
  command line because commands can appear in shell history and process lists.
- The launcher mounts only configured input, output, and cache paths. Review
  generated Docker options before use on multi-user systems.
- Treat coordinates, thumbnails, overlays, reports, manifests, logs, and slide
  names as potentially sensitive clinical data.
- Container images do not contain model weights or study data by design.

## Supported versions

Security fixes are applied to the current default branch. Pin a reviewed commit
or release and an immutable container tag for production analyses.
