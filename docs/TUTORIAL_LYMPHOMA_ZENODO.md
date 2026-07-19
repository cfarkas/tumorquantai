# Lymphoma MDS tutorial: one slide to the full collection

This tutorial starts with the privacy-sanitized H&E MDS dataset on Zenodo and
ends with cell-type-by-slide count and fraction tables. It has three
checkpoints:

1. **Smoke test:** one slide and 1% of tissue tiles.
2. **Fast tutorial:** four fixed slides and 10% of tissue tiles.
3. **Full tutorial:** all 21 slides and 100% of tissue tiles.

Each checkpoint has a separate inference output. Downloads and MDS-to-TIFF
conversion can be expanded and resumed in place.

!!! warning "Research use only"
    TumorQuantAI predictions are not diagnoses or pathologist ground truth.
    Review image quality, MPP, selected tissue, overlays, failures, and the
    aggregation audit before interpreting results.

## Requirements

- Linux, Java 17+, Nextflow 24.10+, and Docker 24+;
- authorized access to the HistoPLUS model token or weight file;
- an NVIDIA GPU for practical inference time;
- approximately 30 GB free for the one/four-slide paths; and
- at least 300 GB free for conversion, work files, and the full run.

The record contains 21 sanitized MDS files totaling 17,370,771,968 bytes.
Converting all L0/L2 levels can approach 142 GB.

## 1. Install the dataset-matched TumorQuantAI release

The version-specific Zenodo record identifies the matching immutable software
tag. Substitute that exact tag below; do not use a moving `main` branch or
guess a tag that has not been published:

```bash
export TUMORQUANTAI_RELEASE="<IMMUTABLE_TAG_NAMED_IN_VERSION_RECORD>"

git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
git checkout --detach "$TUMORQUANTAI_RELEASE"

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

./setup_server.sh --check
./run.sh --doctor
```

Keep the reported Git commit with your results.

## 2. Set paths and record access

The downloader requires the **published version-specific Zenodo record ID,
version DOI, or version record URL** for this release. Do not use a concept DOI,
because it can resolve to another dataset version. The downloader cannot use an
unpublished Zenodo draft.

```bash
export ZENODO_RECORD_ID="<PUBLISHED_VERSION_RECORD_ID_OR_VERSION_DOI>"
export DATA_ROOT="$PWD/tutorial-data"
export RUN_ROOT="$PWD/tutorial-runs"
export MDS_MANIFEST="$PWD/examples/lymphoma/tumorquantai_lymphoma_mds_manifest.csv"
mkdir -p "$RUN_ROOT"
```

Every download below supplies this manifest. The downloader requires the copy
in the checked-out software tag to match the authoritative manifest in the
version record byte-for-byte.

Define this fail-closed audit helper once in the same shell. It rejects a
missing or malformed aggregation audit, any excluded slide, or an unexpected
included-slide count:

```bash
check_aggregation_audit() {
  python - "$1" "$2" <<'PY'
import csv
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected = int(sys.argv[2])
if not path.is_file():
    raise SystemExit(f"Missing aggregation audit: {path}")
with path.open("r", encoding="utf-8-sig", newline="") as handle:
    reader = csv.DictReader(handle)
    if reader.fieldnames is None or "included" not in reader.fieldnames:
        raise SystemExit(f"Malformed aggregation audit: {path}")
    rows = list(reader)
included = sum(
    str(row.get("included", "")).strip().casefold() == "true" for row in rows
)
excluded = len(rows) - included
if included != expected or excluded != 0:
    raise SystemExit(
        f"Audit failed: included={included}, excluded={excluded}, expected={expected}"
    )
print(f"Audit passed: included={included}, excluded={excluded}")
PY
}
```

For a published restricted record, use a personal Zenodo token belonging to an
account with access:

```bash
mkdir -p "$HOME/.config/tumorquantai"
chmod 700 "$HOME/.config/tumorquantai"
umask 077
read -rsp "Zenodo token: " ZENODO_TOKEN
printf '%s' "$ZENODO_TOKEN" > "$HOME/.config/tumorquantai/zenodo_token"
unset ZENODO_TOKEN
printf '\n'
chmod 600 "$HOME/.config/tumorquantai/zenodo_token"
export ZENODO_TOKEN_FILE="$HOME/.config/tumorquantai/zenodo_token"
```

The commands below include `--token-file`. Omit that option only if the final
record's files are public. Never put a token value in a command, notebook, log,
issue, or Git commit.

## 3. Download and convert one slide

Download alias 022. The authoritative manifest is downloaded from the same
Zenodo record and every MDS is checked by size, MD5, and SHA-256:

```bash
python bin/download_zenodo_mds.py \
  --record "$ZENODO_RECORD_ID" \
  --manifest "$MDS_MANIFEST" \
  --token-file "$ZENODO_TOKEN_FILE" \
  --output-dir "$DATA_ROOT" \
  --sample-id TumorQuantAI_LymphomaWSI_022 \
  --expected-count 1
```

Inspect the conversion plan:

```bash
python bin/mds_to_tiff.py \
  --input "$DATA_ROOT/raw" \
  --manifest "$MDS_MANIFEST" \
  --output-dir "$DATA_ROOT/slides" \
  --levels 0 2 \
  --sample-id TumorQuantAI_LymphomaWSI_022 \
  --expected-count 1 \
  --dry-run
```

Convert it:

```bash
python bin/mds_to_tiff.py \
  --input "$DATA_ROOT/raw" \
  --manifest "$MDS_MANIFEST" \
  --output-dir "$DATA_ROOT/slides" \
  --levels 0 2 \
  --sample-id TumorQuantAI_LymphomaWSI_022 \
  --expected-count 1 \
  --resume
```

The converter verifies the MDS checksum and pyramid geometry from the Zenodo
manifest. It writes `slides/mds_conversion_manifest.json`, hashes each TIFF,
and uses that state for safe resume.

## 4. Configure HistoPLUS access

HistoPLUS weights are gated. Request access on the
[HistoPLUS model page](https://huggingface.co/Owkin-Bioptimus/histoplus) and wait
until it is approved; creating a token does not grant model access. Create the
private configuration directory even if the Zenodo record was public and no
Zenodo token was needed:

```bash
mkdir -p "$HOME/.config/tumorquantai"
chmod 700 "$HOME/.config/tumorquantai"
```

For a Hugging Face read token belonging to the approved account:

```bash
umask 077
read -rsp "Hugging Face token: " HF_READ_TOKEN
printf '%s' "$HF_READ_TOKEN" > "$HOME/.config/tumorquantai/hf_token"
unset HF_READ_TOKEN
printf '\n'
chmod 600 "$HOME/.config/tumorquantai/hf_token"
export TUMORQUANTAI_HF_TOKEN_FILE="$HOME/.config/tumorquantai/hf_token"
```

This tutorial uses the default 20x HistoPLUS configuration. If your
organization provides an authorized local artifact, it must be the matching
20x file named exactly `histoplus_cellvit_segmentor_20x.pt`:

```bash
export HISTOPLUS_WEIGHT_FILE="/secure/path/histoplus_cellvit_segmentor_20x.pt"
test -r "$HISTOPLUS_WEIGHT_FILE"
test "$(basename "$HISTOPLUS_WEIGHT_FILE")" = \
  "histoplus_cellvit_segmentor_20x.pt"
sha256sum "$HISTOPLUS_WEIGHT_FILE"
```

Record its approved SHA-256 with the results. In each inference command, use
`--histoplus-weight-file "$HISTOPLUS_WEIGHT_FILE"` instead of
`--hf-token-file "$TUMORQUANTAI_HF_TOKEN_FILE"`. Do not substitute a 40x or
arbitrarily named weight file.

## 5. Discover and smoke-test one slide

Discovery does not run the model:

```bash
./run.sh \
  --input-dir "$DATA_ROOT/slides" \
  --sample-sheet "$DATA_ROOT/slides/samples.csv" \
  --include TumorQuantAI_LymphomaWSI_022 \
  --output-dir "$RUN_ROOT/discovery-one" \
  --dry-run

awk 'NR > 1 {n++} END {exit(n == 1 ? 0 : 1)}' \
  "$RUN_ROOT/discovery-one/workflow_metadata/slides.tsv"
```

Run 1% of tissue tiles:

```bash
./run.sh \
  --input-dir "$DATA_ROOT/slides" \
  --sample-sheet "$DATA_ROOT/slides/samples.csv" \
  --include TumorQuantAI_LymphomaWSI_022 \
  --output-dir "$RUN_ROOT/smoke-one-slide" \
  --work-dir "$RUN_ROOT/work-smoke" \
  --fast \
  --percent-slide 1 \
  --slide-mpp 0.261780 \
  --mpp 0.5 \
  --hf-token-file "$TUMORQUANTAI_HF_TOKEN_FILE" \
  --fail-fast \
  --profile auto

check_aggregation_audit \
  "$RUN_ROOT/smoke-one-slide/aggregated_celltypes/sample_aggregation_audit.csv" \
  1
```

Review the overlay, `summary/summary.json`, and
`aggregated_celltypes/sample_aggregation_audit.csv` before expanding.

## 6. Expand to the fixed four-slide tutorial

The downloader verifies alias 022 already present and adds the other three:

```bash
python bin/download_zenodo_mds.py \
  --record "$ZENODO_RECORD_ID" \
  --manifest "$MDS_MANIFEST" \
  --token-file "$ZENODO_TOKEN_FILE" \
  --output-dir "$DATA_ROOT" \
  --sample-id TumorQuantAI_LymphomaWSI_022 \
  --sample-id TumorQuantAI_LymphomaWSI_002 \
  --sample-id TumorQuantAI_LymphomaWSI_006 \
  --sample-id TumorQuantAI_LymphomaWSI_016 \
  --expected-count 4

python bin/mds_to_tiff.py \
  --input "$DATA_ROOT/raw" \
  --manifest "$MDS_MANIFEST" \
  --output-dir "$DATA_ROOT/slides" \
  --levels 0 2 \
  --sample-id TumorQuantAI_LymphomaWSI_022 \
  --sample-id TumorQuantAI_LymphomaWSI_002 \
  --sample-id TumorQuantAI_LymphomaWSI_006 \
  --sample-id TumorQuantAI_LymphomaWSI_016 \
  --expected-count 4 \
  --resume
```

Confirm discovery finds exactly four:

```bash
./run.sh \
  --input-dir "$DATA_ROOT/slides" \
  --sample-sheet examples/lymphoma/sample_sheet_first4.csv \
  --output-dir "$RUN_ROOT/discovery-four" \
  --dry-run

awk 'NR > 1 {n++} END {exit(n == 4 ? 0 : 1)}' \
  "$RUN_ROOT/discovery-four/workflow_metadata/slides.tsv"
```

Run the fixed 10% tutorial:

```bash
./run.sh \
  --input-dir "$DATA_ROOT/slides" \
  --sample-sheet examples/lymphoma/sample_sheet_first4.csv \
  --output-dir "$RUN_ROOT/fast-four-slides" \
  --work-dir "$RUN_ROOT/work-fast" \
  --fast \
  --percent-slide 10 \
  --slide-mpp 0.261780 \
  --mpp 0.5 \
  --hf-token-file "$TUMORQUANTAI_HF_TOKEN_FILE" \
  --fail-fast \
  --profile auto

check_aggregation_audit \
  "$RUN_ROOT/fast-four-slides/aggregated_celltypes/sample_aggregation_audit.csv" \
  4
```

Fast raw counts describe sampled tiles. Do not multiply them by `100 / 10`.

## 7. Expand conversion to all 21 slides

This downloads the remaining files and rewrites the local raw roster to all
verified slides:

```bash
python bin/download_zenodo_mds.py \
  --record "$ZENODO_RECORD_ID" \
  --manifest "$MDS_MANIFEST" \
  --token-file "$ZENODO_TOKEN_FILE" \
  --output-dir "$DATA_ROOT" \
  --expected-count 21

cd "$DATA_ROOT"
sha256sum --check checksums.sha256
cd -
```

Convert all 21. Existing TIFFs are reused only after their state and SHA-256
are verified:

```bash
python bin/mds_to_tiff.py \
  --input "$DATA_ROOT/raw" \
  --manifest "$MDS_MANIFEST" \
  --output-dir "$DATA_ROOT/slides" \
  --levels 0 2 \
  --expected-count 21 \
  --resume
```

Repeat the same command after an interruption. Do not delete
`slides/mds_conversion_manifest.json`.

Confirm discovery finds exactly 21:

```bash
./run.sh \
  --input-dir "$DATA_ROOT/slides" \
  --sample-sheet "$DATA_ROOT/slides/samples.csv" \
  --output-dir "$RUN_ROOT/discovery-full" \
  --dry-run

awk 'NR > 1 {n++} END {exit(n == 21 ? 0 : 1)}' \
  "$RUN_ROOT/discovery-full/workflow_metadata/slides.tsv"
```

## 8. Run the full analysis

This can take days. Use distinct full output/work directories:

```bash
./run.sh \
  --input-dir "$DATA_ROOT/slides" \
  --sample-sheet "$DATA_ROOT/slides/samples.csv" \
  --output-dir "$RUN_ROOT/full-21-slides" \
  --work-dir "$RUN_ROOT/work-full" \
  --full \
  --slide-mpp 0.261780 \
  --mpp 0.5 \
  --hf-token-file "$TUMORQUANTAI_HF_TOKEN_FILE" \
  --fail-fast \
  --profile auto

check_aggregation_audit \
  "$RUN_ROOT/full-21-slides/aggregated_celltypes/sample_aggregation_audit.csv" \
  21
```

Repeat the exact command after interruption; Nextflow resume is enabled by
default.

## 9. Aggregate and review

Aggregation normally runs automatically. It can be repeated explicitly:

```bash
python bin/aggregate_histoplus_celltypes.py \
  --input-root "$RUN_ROOT/fast-four-slides" \
  --expected-percent-slide 10

python bin/aggregate_histoplus_celltypes.py \
  --input-root "$RUN_ROOT/full-21-slides" \
  --expected-percent-slide 100
```

The main outputs are:

- `celltype_counts_by_sample.csv`: cell types as rows, slides as columns;
- `celltype_fractions_by_sample.csv`: within-slide fractions;
- `celltype_counts_long.csv`: tidy data for statistics; and
- `sample_aggregation_audit.csv`: included, missing, and failed slides.

Keep smoke, fast, and full outputs separate. Before interpretation, inspect
overlays, failed-slide logs, source/target MPP, sampling percentage, model and
container provenance, and the aggregation audit.
