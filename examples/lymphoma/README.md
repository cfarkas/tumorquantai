# Lymphoma tutorial files

- `tumorquantai_lymphoma_mds_manifest.csv` is a repository copy of the strict
  schema-version-2 manifest for review and offline planning. During a real
  download, the authoritative copy comes from public Zenodo record `21466410`
  (DOI `10.5281/zenodo.21466410`).
- `sample_sheet_first4.csv` selects aliases 022, 002, 006, and 016 for the
  fixed 10% fast tutorial.

The prominent beginner tutorial uses only alias 022 at 1%. The advanced
progression then uses these four slides at 10% and all 21 at 100%. Download
with `bin/download_zenodo_mds.py`, convert with `bin/mds_to_tiff.py`, and run
with `./tumorquantai` or the compatible `./run.sh`. See the
[full tutorial](../../docs/TUTORIAL_LYMPHOMA_ZENODO.md).

Public files and documentation must use aliases only. Never add source
accessions, label images, private mappings, clinical data, or tokens here.
