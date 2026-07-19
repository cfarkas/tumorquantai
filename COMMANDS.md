# Command cookbook

```bash
# Prerequisites
./setup_server.sh --check

# Discovery only
./run.sh --input-dir /data/exported --output-dir /data/results-discovery --dry-run

# One-slide 1% smoke test (fast mode with an explicit percentage)
./run.sh --input-dir /data/exported --output-dir /data/results-fast-smoke \
  --include 'case_001*' --fast --percent-slide 1

# Conservative 10% cohort run (--fast defaults to 10)
./run.sh --input-dir /data/exported --output-dir /data/results-fast \
  --fast --celltypes-batch-size 2 --num-workers 2 \
  --max-parallel-slides 1 \
  --cpus 8 --memory '32 GB'

# Full tissue-tile run (enforces 100%)
./run.sh --input-dir /data/exported --output-dir /data/results-full --full

# Resume repeats the same mode and output root
./run.sh --input-dir /data/exported --output-dir /data/results-fast --fast

# Intentional model-revision override: full immutable commits only
./run.sh --input-dir /data/exported --output-dir /data/results-full-alt-revision --full \
  --histoplus-revision cde2eee81af9e39b03802fc33d4f284733b5ee5e

# Independent aggregation
python bin/aggregate_histoplus_celltypes.py \
  --input-root /data/results-fast --expected-percent-slide 10

# Spatial reports
python bin/lazyslide_histoplus_post_spatial_report.py \
  --output-root /data/results-fast --roi-detail-pages --use-npy-polygons

# Cohort PowerPoint
python bin/build_cohort_pptx.py \
  --root /data/results-fast --out /data/results-fast/reports/cohort_report.pptx \
  --compact-first-pages --clean-cache --force-render

# Exploratory clinical + HistoPLUS ML (private inputs; see docs/CLINICAL_ML.md)
python bin/clinical_histoplus_ml.py --help

# Documentation site
python -m pip install --requirement requirements-docs.txt
python -m mkdocs build --strict

# Tests
python -m pytest -q
bash -n run.sh setup_server.sh build_and_push.sh
nextflow config -flat >/dev/null
```
