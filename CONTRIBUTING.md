# Contributing

Focused issues and pull requests are welcome. TumorQuantAI repository code and
documentation are available under the MIT License. Third-party dependencies,
containers, models, weights, and datasets retain their separate terms. See
`LICENSE` and `docs/maintainers/LICENSE_DECISION.md`.

## Before opening a change

- Use neutral synthetic fixtures. Never add raw/private WSI, PHI, patient-level
  tables, credentials, model weights, private manifests, or institutional
  paths.
- Keep large downloads, converted TIFFs, Nextflow work, caches, and generated
  results outside the checkout on a verified mount.
- Do not change class IDs/names/palettes, output schemas, model/container
  identity, MPP behavior, sampling, or failure semantics without a tested,
  documented compatibility decision.
- Preserve `run.sh`, direct Nextflow, worker overrides, and existing automation.
- A failed or incomplete sample must never become numerical zero.

## Development workflow

1. Create a focused branch from the intended base.
2. Add or update lightweight tests; public CI must not require a GPU, gated
   model, real WSI, token, or network download.
3. Keep `./tumorquantai --help` and docs synchronized.
4. Run the relevant checks:

   ```bash
   python -m venv /tmp/tqa-cffvalidate
   /tmp/tqa-cffvalidate/bin/python -m pip install 'cffconvert==2.0.0'
   /tmp/tqa-cffvalidate/bin/cffconvert --infile CITATION.cff --validate
   python scripts/check_repository_hygiene.py
   python -m pytest -q
   python -m py_compile tumorquantai lazyslide_histoplus_wsi_celltype.py bin/*.py
   bash -n run.sh setup_server.sh build_and_push.sh
   nextflow config -flat >/dev/null
   ./tumorquantai demo --output /tmp/tumorquantai-demo
   python -m mkdocs build --strict --site-dir /tmp/tumorquantai-site
   git diff --check
   ```

5. Review generated output names against the worker/fixtures and scan the diff
   for secrets, PHI, weights, WSI, data artifacts, and absolute private paths.

Use synthetic data for screenshots. Do not add derivatives of public slides
unless their applicable license clearly permits redistribution.

## Pull request notes

State:

- problem and before/after user journey;
- compatibility and scientific-invariant impact;
- exact tests run and results;
- whether real public-slide/model inference was not run and why;
- storage paths used for any local data; and
- genuine manual governance/release follow-ups.

Do not create a release, tag, or choose a repository license in an ordinary
feature pull request.
