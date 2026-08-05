# TumorQuantAI maintainer guide

TumorQuantAI is a research-use-only whole-slide workflow that wraps LazySlide
and the gated HistoPLUS model. It creates cell-type coordinates, QC overlays,
per-slide summaries, and cohort matrices. It is not a diagnostic device and is
not clinically validated.

## Entry points

- Main command-line interface: `./tumorquantai doctor|demo|inspect|run|status|report`
- Full raw-TIFF patch route: `./tumorquantai --patches PATH --paper-figures --output DIR`
- Public one-slide path: `./tumorquantai quickstart --output MOUNTED_PATH`
- Compatible expert interfaces: `./run.sh` and `nextflow run .`
- Scientific worker: `lazyslide_histoplus_wsi_celltype.py`
- Offline breast-IHC release helpers: `bin/prepare_breast_ihc_patch_release.py`
  and `bin/package_breast_ihc_patch_release.py` (no upload or publication)

Keep the main command-line interface a thin, testable wrapper. Do not duplicate or
silently change the biological/image-analysis engine.

## Scientific invariants

- Keep the HistoPLUS revision and CPU/GPU container identities immutable.
- Preserve source-slide/L2 fingerprints, provenance, deterministic sampling,
  and the recorded seed.
- Keep source MPP distinct from target MPP; fail closed when physical scale
  cannot be established.
- Preserve per-slide isolation, retry, resume, and cached-task reuse.
- Audit included, failed, incomplete, excluded, and pending samples explicitly.
- Never convert a failed or incomplete sample into numerical zero.
- Sampled-tile counts are not whole-slide counts and are never extrapolated by
  multiplying by `100 / percent_slide`.
- Keep output names and schemas backward compatible unless a migration and
  regression tests accompany a change.
- Preserve `run.sh`, direct Nextflow, worker overrides, and existing automation.

## Security, privacy, and storage

Never commit or publish tokens, model weights, weight paths, raw/private WSI,
PHI, patient-level data, clinical linkage tables, large generated results,
Nextflow work directories, model caches, downloaded MDS, or converted TIFFs.
Do not print token contents. Prefer `TUMORQUANTAI_HF_TOKEN_FILE`, then
`~/.config/tumorquantai/hf_token`; retain the deprecated legacy-file fallback.

Before downloads, conversion, or inference, verify the target with `findmnt -T`,
`df -hT`, and a write probe. Keep work beside the selected output on a mounted
storage filesystem. Never perform unrelated Docker, mount, Conda, or server
maintenance.

## Safe validation

Provision the schema validator once in an isolated environment. The package
download needs a package-index connection unless it is already cached; actual
validation is offline:

```bash
python -m venv /tmp/tqa-cffvalidate
/tmp/tqa-cffvalidate/bin/python -m pip install 'cffconvert==2.0.0'
```

These checks then need no gated model, GPU, real WSI, or network:

```bash
/tmp/tqa-cffvalidate/bin/cffconvert --infile CITATION.cff --validate
python scripts/check_repository_hygiene.py
python -m pytest -q
bash -n run.sh setup_server.sh build_and_push.sh
python -m compileall -q tumorquantai bin tests
./tumorquantai demo --output /tmp/tumorquantai-demo
./tumorquantai inspect tests/fixtures --source-mpp 0.261780 --output /tmp/tqa-inspection
nextflow config . -flat
mkdocs build --strict
git diff --check
```

Use only synthetic fixtures in ordinary CI. External GitHub, Zenodo, DOI, and
Hugging Face checks belong in scheduled/manual CI.

## Release, dataset, and licensing rules

Keep software release, documentation, and public tutorial metadata distinct.
The current software release is `v1.0.0`. The lymphoma tutorial remains
immutably matched to software `v0.4.0`, Zenodo record `21466410`, dataset DOI
`10.5281/zenodo.21466410`, sample `TumorQuantAI_LymphomaWSI_022`, and source
MPP `0.261780`. The separate raw breast-IHC patch dataset is Zenodo record
`21797920`, DOI `10.5281/zenodo.21797920`. Verify these identities against
their public records before changing them. Never assign either dataset DOI to
the software or invent performance, clinical-validation, or biological claims.

This repository has no declared open-source license. Source visibility is not
reuse permission. Do not add a license or license badge until the owner records
an explicit decision. Do not create a release or tag as part of routine fixes.
