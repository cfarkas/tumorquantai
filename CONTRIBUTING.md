# Contributing

Contributions are welcome through focused pull requests.

1. Do not include patient identifiers, private WSI data, credentials, model
   weights, generated results, or institutional filesystem paths.
2. Create a branch and add tests for behavior changes.
3. Keep CLI documentation and `--help` output aligned.
4. Run:

   ```bash
   python -m pytest -q
   python -m py_compile lazyslide_histoplus_wsi_celltype.py bin/*.py
   bash -n run.sh setup_server.sh build_and_push.sh
   nextflow config -flat >/dev/null
   ```

5. For inference changes, document the model weight/revision, hardware, input
   type, sampling settings, and one-slide acceptance results. A full GPU/model
   run is not part of public CI because HistoPLUS is gated.

Avoid changing class IDs, names, palettes, or output schemas without a versioned
migration note. Do not make failed samples look like zero-cell biology.
