# Developer guide

TumorQuantAI has three public execution layers:

```text
./tumorquantai          beginner CLI and safety checks
        |
        v
./run.sh                compatible shell launcher
        |
        v
main.nf                 Nextflow slide discovery, per-slide processing, and aggregation
```

The worker is `lazyslide_histoplus_wsi_celltype.py`. Public MDS download and conversion are handled by scripts in `bin/`.

## Clone and create a development environment

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai

# Create and activate a development environment.
python3 -m venv .venv
. .venv/bin/activate

# Install lightweight test and documentation dependencies.
python -m pip install --upgrade pip
python -m pip install -r requirements-tutorial.txt
python -m pip install -r requirements-docs.txt
python -m pip install pytest jsonschema pyyaml pandas matplotlib scipy scikit-learn openpyxl
```

## Run the tests

```bash
# Compile Python entry points and helper scripts.
python -m py_compile tumorquantai lazyslide_histoplus_wsi_celltype.py bin/*.py scripts/*.py

# Check shell syntax.
bash -n run.sh setup_server.sh build_and_push.sh

# Run the unit and documentation tests.
python -m pytest -q
python scripts/check_docs_language.py
python scripts/check_oncotracer_style_docs.py

# Build GitHub Pages strictly.
python -m mkdocs build --strict
```

## Run model-free acceptance checks

```bash
# Exercise the structural demo.
./tumorquantai demo --output /tmp/tumorquantai-demo

# Inspect the repository fixtures without inference.
./tumorquantai inspect tests/fixtures \
  --output /tmp/tumorquantai-inspection \
  --source-mpp 0.261780

# Parse the Nextflow configuration.
nextflow config -flat >/dev/null
```

## Scientific invariants

Changes must preserve these behaviors:

- source MPP is validated or supplied explicitly;
- primary L0 and companion L2 files are not confused;
- sampling is deterministic for the same input, seed, and configuration;
- model revision and local-weight content identity are recorded;
- each slide is isolated for retry and cache reuse;
- failed or incomplete slides are excluded from numeric matrices and retained in the audit;
- public reports redact credential values and sensitive local paths;
- tokens and model weights are never copied into results;
- output schemas change only with explicit migration notes and tests.

## Documentation invariants

Primary examples must:

- begin with `git clone https://github.com/cfarkas/tumorquantai.git` followed by `cd tumorquantai`;
- use brief `#` comments in Bash command boxes;
- keep data and work outside the repository;
- expose the only path that a beginner must edit;
- use copy/paste-valid Bash syntax;
- distinguish model-free preparation from gated HistoPLUS inference;
- describe QuickStart Example 1 as one WSI at 1%;
- describe the full lymphoma tutorial as 21 WSIs at 10%;
- avoid presenting sampled-tile counts as whole-slide estimates.

## Add a CLI option

1. Add the public option in `tumorquantai`.
2. Validate it before launching `run.sh`.
3. Forward it explicitly to the engine.
4. Record it in the run manifest when it changes scientific interpretation.
5. Add parser, validation, and execution tests.
6. Document it in `reference/cli.md`, `reference/parameters.md`, and the relevant tutorial.

Protected low-level options must not be silently overridden through expert passthrough.

## Add or change an output

1. Update the writer.
2. Update aggregation behavior where relevant.
3. Preserve failed-versus-zero semantics.
4. Update `reference/outputs.md` and `outputs.md`.
5. Add fixture-based tests.
6. Record the change in `CHANGELOG.md`.

## Public data files

The authoritative public tutorial manifest is stored on Zenodo record `21466410`. Repository URL and checksum lists are generated from that manifest. Do not manually edit generated files without regenerating and verifying them.

```bash
# Regenerate public URL and checksum artifacts.
python scripts/generate_zenodo_download_files.py

# Probe the generated public URLs without downloading full slides.
python scripts/check_zenodo_wsi_urls.py
```

## Pull requests

A scientific or user-facing change should include:

- purpose and scope;
- exact commands tested;
- test results;
- data and resource scope;
- whether model inference ran;
- whether output schemas changed;
- research-use limitations;
- screenshots only when they contain no private data.

See [`CONTRIBUTING.md`](https://github.com/cfarkas/tumorquantai/blob/main/CONTRIBUTING.md) and the pull-request template for repository policy.