# CK20-guided CD3/CD8 reference

## Command contracts

These commands are equivalent:

```bash
tumorquantai --inmunoscore INPUT [OPTIONS]
tumorquantai ihc immunoscore INPUT [OPTIONS]
```

The compatibility flag deliberately uses the spelling `--inmunoscore`.
The canonical English subcommand is `ihc immunoscore`.

The public reference input is Zenodo record
[`22177196`](https://zenodo.org/records/22177196), DOI
[`10.5281/zenodo.22177196`](https://doi.org/10.5281/zenodo.22177196).

Common required arguments:

| Argument | Contract |
| --- | --- |
| `INPUT` | Regular directory containing either flat public MDS files or private Motic case-marker bundles |
| `--output DIR` | New directory, or an existing TumorQuantAI Immunoscore-proxy output with matching state |

Choose exactly one identity mode:

| Mode | Required option(s) | Contract |
| --- | --- | --- |
| Published public input | `--public-slide-catalog CSV` | Exact published catalog schema and flat MDS roster; existing public aliases are preserved and no private linkage is created |
| Private source input | `--alias-secret-file FILE` and `--private-linkage CSV` | Secret is owner-owned, single-linked, mode 0600, and at least 32 bytes; controlled linkage stays outside output and is created or exactly verified at mode 0600 |

The public option and private option pair are mutually exclusive.

Analysis options:

| Option | Default | Effect |
| --- | ---: | --- |
| `--workers` | min(3, CPUs) | Complete cases processed concurrently; accepted range 1–8 |
| `--source-mpp` | catalog or scanner sidecar | Optional assertion that must match every published catalog value or private Motic `info.ini` scale |
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

## Published public-catalog grouping

`--public-slide-catalog` accepts the exact columns in
`tumorquantai_colon_immunoscore_slide_catalog.csv`:

```text
case_alias, slide_alias, marker, zenodo_filename, size_bytes, sha256, md5,
source_mpp, source_format, sanitization_profile
```

The loader requires `TQA_CI_` and `TQA_CIS_` base32 aliases, CD3/CD8/CK20
markers, one slide per case/marker, a safe flat filename equal to
`<slide_alias>.mds`, valid checksum syntax, an exact byte-size match, positive
finite MPP, the published Motic DSI0 source format and sanitization profile,
and equality between catalogued and discovered MDS paths. A full run hashes
each MDS and requires its SHA-256 to match before case analysis. Dry-run checks
the catalog and sizes but deliberately does not hash 40.7 GB of payloads.

Public mode preserves the catalogued aliases as the analysis identities. It
does not infer grouping from stain intensity or regenerate aliases from a new
secret.

## Private source-bundle grouping

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
size and SHA-256 must exactly match either the published catalog or the
separate private linkage, according to the selected identity mode.

## Clear case-value CSV

`tables/tumorquantai_immunoscore_values.csv` has one row for every discovered
public case alias:

| Field group | Fields |
| --- | --- |
| Identity | `case_alias` |
| TumorQuantAI densities | CD3 epithelium, CD3 stroma, CD8 epithelium, CD8 stroma, all in positive cells/mm² |
| Internal ranks | One percentile per density against the automatic-QC-pass reference, four-value mean, and internal low/intermediate/high group |
| Provisional analogue | `ck20_guided_provisional_immunoscore` (`pI0`–`pI4`), explicit status, and internal reference `n` |
| Consensus boundary | Blank `consensus_immunoscore` and an explicit unavailable status |
| QC | `qc_status` and semicolon-separated `qc_flags` |

The percentile for any numerically available case against the passing-case
reference is:

~~~text
100 × (number below + 0.5 × number tied) / number of passing cases
~~~

Review cases receive provisional percentiles against that reference so a
pathologist can accept or flag them, but they never enter the reference.
Failed and incomplete cases are unscored.

## Provisional pI0-pI4 analogue

TumorQuantAI averages the four internal percentiles and applies these published
five-category percentile bands:

| Output | Mean internal percentile |
| --- | ---: |
| `pI0` | 0–10 |
| `pI1` | >10–25 |
| `pI2` | >25–70 |
| `pI3` | >70–95 |
| `pI4` | >95–100 |

The mandatory `p` prefix means **provisional**. The calculation substitutes
CK20 epithelial/stromal proxies for CT/IM and this run's automatic-QC-pass
cases for the validated external reference. It is useful for prioritizing
expert review, not for prognosis, diagnosis, or treatment. The separate
`consensus_immunoscore` field remains blank.

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

## Paper figures and pathologist adjudication

Every complete case produces four 300-dpi review sheets:

```text
cases/<case_alias>/paper_figures/
├── case_summary_paper_figure.png
├── case_summary_paper_figure.pdf
├── case_summary_paper_figure_legend.txt
└── <slide_alias>_<marker>_paper_figure.{png,pdf}
```

The case sheet shows the CK20 reference, compartment overlay, CD3/CD8
registration blends, physical scale bars, exact densities, provisional-score
gauge, and algorithm QC. Marker sheets provide one review image per input WSI.
They are overview-scale registration/compartment figures—not cell-outline
overlays—and therefore do not replace cellular review in a slide viewer.
`tables/paper_figure_manifest.csv` records every PNG, PDF, external legend,
layout version, and DPI.

Open `PATHOLOGIST_REVIEW.html` locally to review each case and export
`pathologist_review_completed.csv`. Allowed decisions are:

| Decision | Meaning |
| --- | --- |
| `accept` | Technical representation accepted after visual review |
| `flag` | Correction or adjudication required; original values remain unchanged |
| `exclude` | Exclude from the reviewed analysis population |

The blank `tables/pathologist_review_template.csv` and
`tables/pathologist_review_codebook.csv` make the same contract available to
Excel/R workflows. Reviewer decisions are additive fields: they never replace
the TumorQuantAI prediction or automatic QC.

## Clinical boundary

The package does not create tumour-core or invasive-margin masks, import the
validated 700-case reference distribution, or emit an official score. It may
emit the explicitly provisional pI analogue described above.
`consensus_immunoscore_status` is always:

```text
unavailable_requires_pathologist_validated_CT_IM_and_external_reference
```

See the [complete tutorial](../tutorials/colon-ihc-wsi-immunoscore.md) for
method rationale, review order, and Zenodo privacy controls.
