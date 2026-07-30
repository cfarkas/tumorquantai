# Dataset and Zenodo consistency

## Fixed public contract

| Field | Required value |
| --- | --- |
| Record | `21466410` |
| DOI | `10.5281/zenodo.21466410` |
| Record title | TumorQuantAI lymphoma H&E whole-slide image tutorial dataset |
| Dataset version | v2 on the record |
| Dataset license | CC BY 4.0 |
| Dataset-matched software | `v0.4.0` |
| Files | 21 MDS plus `tumorquantai_lymphoma_mds_manifest.csv` |
| MDS bytes | `17,370,771,968` |
| Beginner sample | `TumorQuantAI_LymphomaWSI_022` |
| Beginner file | `TumorQuantAI_LymphomaWSI_022.mds` |
| Beginner size | `125350400` bytes |
| Beginner MD5 | `94bb5b08ccf1957f8c42a579e8b33cfb` |
| Beginner SHA-256 | `db2988b5c6bc791510cec4127106509e604e577feafdb15b94c149043ed7067a` |
| Beginner source MPP | `0.261780` |
| Conversion | L0 and L2 only |
| Smoke sampling | seeded 1% |

The dataset DOI identifies the dataset, not TumorQuantAI software. `v0.4.0` is
the engine release named by the dataset record; later usability-only source
must preserve the scientific contract and record its own commit.

## Release consistency checks

Before changing public instructions:

1. Fetch the authoritative manifest from version-specific record 21466410.
2. Require byte identity with
   `examples/lymphoma/tumorquantai_lymphoma_mds_manifest.csv`.
3. Verify schema version 2, 21 unique safe aliases/files, exact aggregate bytes,
   and size/MD5/SHA-256 fields.
4. Verify alias 022's size, hashes, level geometry, and source MPP.
5. Confirm quickstart cannot select more than alias 022.
6. Keep external-network verification scheduled/manual rather than on ordinary
   pull requests.

Any record replacement or dataset version change requires an explicit,
reviewed compatibility update. Do not silently follow a concept/latest DOI to
different bytes.

For the current record, the authoritative manifest identity is 10,108 bytes,
MD5 `ad9a9472e8beb302f8b9ba2b3359bacc`, and SHA-256
`48ca87237c867bf34fe0214f229fd04633ae8bd83555275932f698057231ad20`.

## Rights and scientific scope

The public record is downloadable without a Zenodo credential and its
structured metadata declares CC BY 4.0. Preserve required attribution/notices
and review the exact record terms before redistribution. This repository does
not need a slide-derived thumbnail for its demo or documentation.

The collection has no diagnostic annotations or pathologist ground truth. It
is a technical tutorial/reproducibility dataset, not a clinical benchmark.
