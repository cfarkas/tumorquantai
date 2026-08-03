# Full 21-slide public collection at 10%

The maintained complete procedure is now [Full tutorial: 21 public lymphoma WSIs at 10%](../full_tutorial.md).

It begins from a fresh clone and provides copy/paste commands for:

1. installing the tutorial environment;
2. selecting and verifying mounted storage;
3. downloading the authoritative Zenodo manifest;
4. downloading all 21 standard MDS filenames;
5. validating all 21 SHA-256 checksums;
6. converting L0 and L2 with resume support;
7. inspecting the exact 21-slide roster and source MPP;
8. running a deterministic 10% HistoPLUS analysis with `--preset fast`;
9. verifying all per-slide and cohort outputs.

```bash
# Open the maintained full-tutorial source from the repository.
sed -n '1,260p' docs/full_tutorial.md
```

The complete public dataset is Zenodo record `21466410`, DOI `10.5281/zenodo.21466410`. The 21-slide tutorial uses 10% of detected tissue tiles per slide. It does not use the `full` 100% preset.

Ten-percent counts are sampled-tile counts, not validated whole-slide estimates. Do not multiply them by ten.

Continue to the [maintained full tutorial](../full_tutorial.md).