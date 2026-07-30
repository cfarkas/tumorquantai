# Public lymphoma teaching dataset

The TumorQuantAI teaching collection contains 21 privacy-sanitized H&E
whole-slide images in Motic MDS format.

| Property | Value |
| --- | --- |
| Public record | [21466410](https://zenodo.org/records/21466410) |
| DOI | [`10.5281/zenodo.21466410`](https://doi.org/10.5281/zenodo.21466410) |
| Dataset version on record | v2 |
| Dataset license | Creative Commons Attribution 4.0 International (CC BY 4.0) |
| Dataset-matched software | `v0.4.0` |
| MDS files | 21 |
| MDS bytes | 17,370,771,968 |
| Source resolution | 0.261780 µm/pixel at level 0 |
| Public names | `TumorQuantAI_LymphomaWSI_NNN.mds` |
| Intended use | Technical tutorial and reproducibility |

One structurally corrupt source and one probable repeat acquisition were
excluded during curation. The collection has no diagnostic annotations or
pathologist ground truth and does not establish lymphoma subtype, prognosis,
treatment response, or clinical validity.

## Authoritative manifest

The record includes `tumorquantai_lymphoma_mds_manifest.csv`. Strict
schema-version-2 rows contain the public alias/filename, exact size/SHA-256/MD5,
source MPP, pyramid geometry, pixel-stream identities, and sanitization profile.
The downloader fetches this manifest from record 21466410 and requires any
repository copy to match byte-for-byte.

## Privacy treatment

Preparation replaced label, macro, acquisition, barcode, scanner, and other
non-pixel streams with deterministic neutral content while requiring the
ordered full aggregate SHA-256 over every `DSI0` pixel stream name, length, and
byte to match. Private mappings, source labels, clinical data, model weights,
tokens, and unrelated material are not in the record.

The record metadata declares CC BY 4.0. Follow its attribution and notice
requirements for any permitted reuse or derivative. This repository does not
redistribute slide-derived tutorial thumbnails.

See the [dataset consistency contract](maintainers/DATASET_CONSISTENCY.md) and
[technical validation record](VALIDATION_LYMPHOMA.md).
