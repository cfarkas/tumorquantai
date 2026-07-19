# Lymphoma tutorial files

- `tumorquantai_lymphoma_mds_manifest.csv` is a repository copy of the strict
  schema-version-2 manifest for review and offline planning. During a real
  download, the authoritative copy comes from the same version-specific Zenodo record.
- `sample_sheet_first4.csv` selects aliases 022, 002, 006, and 016 for the
  fixed 10% fast tutorial.

The worked tutorial progresses from one slide at 1%, to these four slides at
10%, to all 21 slides at 100%. Download with
`bin/download_zenodo_mds.py`, convert with `bin/mds_to_tiff.py`, and run with
`./run.sh`. See the
[full tutorial](../../docs/TUTORIAL_LYMPHOMA_ZENODO.md).

Public files and documentation must use aliases only. Never add source
accessions, label images, private mappings, clinical data, or tokens here.
