# Lymphoma teaching dataset

The TumorQuantAI teaching collection contains **21 H&E whole-slide images** in
Motic `.mds` format.

| Property | Value |
| --- | --- |
| MDS files | 21 |
| MDS bytes | 17,370,771,968 (17.371 GB) |
| Stain | H&E only |
| Source resolution | 0.261780 µm/pixel at level 0 |
| Public names | `TumorQuantAI_LymphomaWSI_NNN.mds` |
| Record | `<PUBLISHED_VERSION_RECORD_OR_VERSION_DOI>` |
| Planned software release | `v0.4.0` |
| Intended use | TumorQuantAI technical tutorial and reproducibility |

One structurally corrupt MDS and one probable repeat acquisition were excluded.
Different H&E sections from the same specimen remain separate slides.

## Privacy treatment

Preparation creates independent copies and writes only non-pixel OLE streams:

- embedded label and macro images are replaced by deterministic neutral images;
- acquisition, barcode, scanner, and other non-pixel streams are neutralized;
- the `DSI0` pixel-stream roster and count must remain unchanged;
- a streaming aggregate SHA-256 over every ordered `DSI0` stream name, length,
  and byte is computed for source and sanitized copies and must match;
- a deterministic per-level sampled fingerprint is retained as a supplemental
  diagnostic;
- each sanitized MDS is reopened and its dimensions are checked;
- source accession markers are scanned in ASCII and UTF-16; and
- the final file receives exact SHA-256 and MD5 checksums.

Every `DSI0` byte contributes to the full aggregate digest; the sampled
fingerprint is not the preservation gate. A real slide was additionally
cross-checked against the previous ASlide TIFF export as described in
[validation](VALIDATION_LYMPHOMA.md).

The record excludes private source mappings, original labels, sidecars,
clinical data, unrelated project material, special stains, model weights, and
tokens.

## Authoritative manifest

The Zenodo record includes
`tumorquantai_lymphoma_mds_manifest.csv` alongside the 21 MDS files. Its strict
schema version is `2`; unrecognized columns are rejected before upload. Each
row records:

- public alias and filename;
- exact size, SHA-256, and MD5;
- source MPP, pyramid-level count, and level dimensions;
- pixel-stream count, supplemental `pixel_sample_sha256`, and full aggregate
  `pixel_full_sha256` over all `DSI0` streams; and
- sanitization profile `pixel-preserving-nonpixel-redaction-v2`.

The downloader obtains this manifest from the same version-specific Zenodo
record. If a local
copy is supplied, it must match the record byte-for-byte.

## Limits

The collection has no diagnostic annotations or pathologist ground truth. It
is not a clinical benchmark and does not establish lymphoma subtype,
prognosis, treatment response, or clinical validity.

## Current release state

Local sanitization, staging, and checksums are complete. No Zenodo draft has
yet been created because the upload still requires a private access token. An
explicitly authorized dataset license is still required before publication. Any
draft created by the supplied tool remains restricted and unpublished;
publication requires separate human governance and privacy review.
