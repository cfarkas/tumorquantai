# CK20-guided CD3/CD8 reference

## Command contracts

These commands are equivalent:

```bash
tumorquantai --inmunoscore INPUT [OPTIONS]
tumorquantai ihc immunoscore INPUT [OPTIONS]
```

The compatibility flag deliberately uses the spelling `--inmunoscore`.
The canonical English subcommand is `ihc immunoscore`.

Required arguments:

| Argument | Contract |
| --- | --- |
| `INPUT` | Regular directory containing Motic bundles named with one exact CD3, CD8, or CK20 token and a regular `1.mds` |
| `--output DIR` | New directory, or an existing TumorQuantAI Immunoscore-proxy output with matching state |
| `--alias-secret-file FILE` | Regular, owner-owned, single-linked, mode-0600 file containing at least 32 bytes |
| `--private-linkage CSV` | Controlled CSV outside output; created atomically at mode 0600 or exactly verified as owner-controlled and single-linked on resume |

Analysis options:

| Option | Default | Effect |
| --- | ---: | --- |
| `--workers` | min(3, CPUs) | Complete cases processed concurrently; accepted range 1–8 |
| `--source-mpp` | scanner sidecar | Optional assertion that must match every Motic `info.ini` scale |
| `--target-analysis-mpp` | 0.55 | Selects the nearest MDS pyramid level |
| `--overview-max-edge` | 2048 | Bounded registration overview edge |
| `--block-tiles` | 4 | Tile count along each streamed analysis-block edge |
| `--minimum-registration-dice` | 0.35 | Automatic pass threshold; lower values remain review-only |
| `--immune-weak-dab-od` | 0.16 | CD3/CD8 expected-brown DAB threshold |
| `--ck20-minimum-dab-od` | 0.08 | CK20 expected-brown epithelial-proxy threshold |
| `--ck20-target-mpp` | 2.0 | Streams CK20 at the nearest pyramid level before projection |
| `--ck20-minimum-projected-fraction` | 0.02 | Fine-scale positive-pixel fraction required in an overview pixel |
| `--ck20-minimum-component-um2` | 1,000 | Removes smaller connected proxy regions, with a four-overview-pixel floor |
| `--ck20-epithelium-expansion-um` | 8.0 | Expands retained CK20 regions before compartment assignment |
| `--no-qc` | false | Omits composite PNGs; numerical QC fields remain |
| `--no-resume` | false | Disables reuse and refuses a non-empty output |
| `--fail-fast` | false | Stops after the first complete-case failure |
| `--dry-run` | false | Discovers marker sets and verifies MPP without writing |

## Exact input grouping

The regular expression is:

```text
^(?P<case_id>.+)-(?P<marker>CD3|CD8|CK20)-(?P<suffix>.+)$
```

Matching is case-insensitive for the marker only. The source case ID is the
exact non-empty prefix before the marker token. Duplicate marker slides within
one source case fail closed. Cases missing one or more markers are retained in
`unavailable_cases.csv` and never converted to zero.

HMAC domains are separated for cases and slides:

```text
case:  TQA_CI_<20 base32 characters>
slide: TQA_CIS_<20 base32 characters>
```

The secret and private IDs are never written under `--output`.

## Analysis signature

The signature is SHA-256 over:

- `tumorquantai_ck20_immunoscore_proxy_v1`;
- `serial-wsi-registration-ck20-streamed-compartment-cd3-cd8-v2`;
- every serialized `ImmunoscoreConfig` setting.

Completed cases are reused only when their status is complete, the signature
matches, and requested QC artifacts exist. Before case reuse, every source MDS
size and SHA-256 must exactly match the separate private linkage.

## Clear case-value CSV

`tables/tumorquantai_immunoscore_values.csv` has one row for every discovered
anonymous case:

| Field group | Fields |
| --- | --- |
| Identity | `case_alias` |
| TumorQuantAI densities | CD3 epithelium, CD3 stroma, CD8 epithelium, CD8 stroma, all in positive cells/mm² |
| Internal ranks | One mid-rank percentile per density, four-value mean, and internal low/intermediate/high group |
| Consensus boundary | Blank `consensus_immunoscore` and an explicit unavailable status |
| QC | `qc_status` and semicolon-separated `qc_flags` |

The percentile for a value among the passing cases is:

~~~text
100 × (number below + 0.5 × number tied) / number of passing cases
~~~

Review, failed, and incomplete cases do not enter the percentile reference.

## Cohort density summary CSV

`tables/cohort_density_summary.csv` reports `n`, mean, sample standard
deviation, median, first and third quartiles, minimum, and maximum for each of
the four density measurements. Every row names its denominator population:

- `automatic_qc_pass` includes only pass-status cases;
- `all_numerically_available` includes pass and review cases.

Failed and incomplete cases enter neither population. An undefined sample
standard deviation (fewer than two values) is blank rather than zero.

## Long density CSV

`tables/case_compartment_densities.csv` contains:

```text
case_alias
marker
compartment
positive_cell_count
segmented_nucleus_count
analyzed_area_mm2
positive_cell_density_per_mm2
mapped_positive_cell_fraction
analysis_mpp
registration_tissue_dice
qc_status
qc_flags
```

Compartments are `ck20_epithelium_proxy`, `ck20_stroma_proxy`, and
`common_tissue`. Area is measured in the CK20 overview coordinate system after
intersection with registered immune-slide tissue and the streamed valid-block
footprint.

## Registration CSV

`tables/registration_qc.csv` records the moving marker, CK20 reference, method,
feature matches, inliers, inlier fraction, tissue Dice, registered tissue
fraction, QC status, and six affine matrix elements. The affine matrix maps
moving-overview coordinates to CK20-overview coordinates.

Each case `measurement.json` also records the source, selected-level, and
overview dimensions; overview X/Y µm/pixel; CD3/CD8 analysis levels; streamed
CK20 level and realised MPP; fine-scale and projected DAB fractions; block
counts; and effective CK20 morphology in pixels and approximate micrometres.
CK20 is detected at the level nearest 2.0 µm/pixel and area-projected to the
bounded overview. Coordinates use numeric pyramid scale plus explicit resize,
not ratios of differently padded tile canvases. The final mask remains a
coarse WSI compartment and must be reviewed near boundaries.

## QC semantics

| Status | Meaning |
| --- | --- |
| `pass` | Feature-based registration Dice met the threshold, mapped-positive fraction was at least 0.50, compartment area met the minimum, and the marker produced segmented nuclei |
| `review` | Numerical output exists but one or more automatic conditions require visual review |
| `failed` | Case processing raised an error; no numerical zero is emitted |
| `unavailable` | The source case lacks at least one required marker |

Automated pass is not pathologist approval. Every serial-section composite and
CK20 proxy mask must be reviewed before research interpretation.
The feature-free `tissue-bbox` registration fallback and a marker with zero
segmented nuclei are always forced to `review`, regardless of tissue Dice or
analysed area. A CK20 result with an empty epithelial or stromal compartment is
also forced to review as `degenerate_ck20_compartment`. The QC policy version
is recorded in case and run metadata.

## Clinical boundary

The package does not create tumour-core or invasive-margin masks, import the
validated 700-case reference distribution, or emit an official score.
`consensus_immunoscore_status` is always:

```text
unavailable_requires_pathologist_validated_CT_IM_and_external_reference
```

See the [complete tutorial](../tutorials/colon-ihc-wsi-immunoscore.md) for
method rationale, review order, and Zenodo privacy controls.
