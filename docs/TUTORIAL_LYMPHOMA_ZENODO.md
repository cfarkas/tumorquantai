# Public lymphoma WSI tutorials

The public tutorial dataset is [Zenodo record 21466410](https://zenodo.org/records/21466410), DOI [`10.5281/zenodo.21466410`](https://doi.org/10.5281/zenodo.21466410).

Use the maintained tutorials:

1. [QuickStart Example 1: one public WSI](quick_start.md) — fixed sample 022, model-free preparation, and optional seeded 1% inference.
2. [Full tutorial: all 21 public lymphoma WSIs at 10%](full_tutorial.md) — exact downloads, checksum validation, L0/L2 conversion, roster inspection, seeded 10% inference, and output verification.
3. [Other example: four public WSIs at 10%](tutorials/four-public-slides.md) — an intermediate cohort checkpoint.

`tumorquantai quickstart` is deliberately bounded to one WSI. The 21-slide tutorial uses `tumorquantai run ... --preset fast`, which processes a deterministic 10% of detected tissue tiles per slide.

The collection has no diagnostic annotations or pathologist ground truth and is not a clinical benchmark.