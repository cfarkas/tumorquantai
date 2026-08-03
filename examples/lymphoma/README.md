# Lymphoma tutorial files

- `tumorquantai_lymphoma_mds_manifest.csv` is a repository copy of the strict
  schema-version-2 manifest for review and offline planning. During a real
  download, the authoritative copy comes from public Zenodo record `21466410`,
  digital object identifier (DOI) `10.5281/zenodo.21466410`.
- `sample_sheet_first4.csv` selects aliases 022, 002, 006, and 016 for the
  fixed 10% fast tutorial.

The first checkpoint uses only alias 022 at 1%, followed by four slides at 10%
and all 21 at 100%. The `zenodo_*.urls.txt` and `checksums_*.sha256` files
use the standard direct `TumorQuantAI_LymphomaWSI_NNN.mds` filenames for
one-, four-, and 21-slide selections. Convert with `bin/mds_to_tiff.py`, then
run with `./tumorquantai` or the compatible `./run.sh`. See the
[public tutorials](../../docs/TUTORIAL_LYMPHOMA_ZENODO.md).

Public files and documentation must use aliases only. Never add source
accessions, label images, private mappings, clinical data, or tokens here.
