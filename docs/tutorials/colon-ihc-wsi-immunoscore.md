# Colon IHC whole-slide quantification

<div class="tqa-ihc-banner" markdown>
<span class="tqa-kicker">DIRECT MOTIC WSI WORKFLOW</span>

## Register CD3 and CD8 to CK20, then measure compartment densities

TumorQuantAI reads Motic MDS pyramids directly. It creates stable anonymous
aliases, aligns serial sections, uses CK20 to form epithelial and stromal
proxies, streams immune-cell detection across each WSI, and writes clear CSV
tables plus visual registration QC.

<a class="tqa-button" href="#run-the-cohort">Run the cohort</a>
<a class="tqa-button tqa-button-secondary" href="#what-the-numbers-mean">Interpret the outputs</a>
</div>

<div class="tqa-metric-grid">
  <div class="tqa-metric"><strong>30</strong><span>Motic MDS slides</span></div>
  <div class="tqa-metric"><strong>11</strong><span>source cases discovered</span></div>
  <div class="tqa-metric"><strong>9</strong><span>complete CD3/CD8/CK20 sets</span></div>
  <div class="tqa-metric"><strong>0.261780</strong><span>µm/pixel at source level</span></div>
</div>

!!! danger "Research proxy—not clinical Immunoscore"
    This workflow does **not** calculate the clinically validated consensus
    Immunoscore. The required pathologist-reviewed tumour core (CT), invasive
    margin (IM), and validated external reference population are absent.
    TumorQuantAI therefore leaves `consensus_immunoscore` blank and reports its
    status as unavailable. The four density measurements and internal
    percentiles are research outputs only.

## What this workflow answers

<div class="tqa-summary-grid">
  <div class="tqa-summary-card" markdown>
  ### Where are CD3/CD8-positive objects?

  CD3 and CD8 WSIs are registered independently to the CK20 serial section.
  Positive-cell centroids are mapped into the common CK20 coordinate space.
  </div>
  <div class="tqa-summary-card" markdown>
  ### Epithelial or stromal proxy?

  Expected-brown CK20 DAB defines an epithelial proxy. Remaining common tissue
  is reported as a stromal proxy. Both masks and every registration require
  visual review.
  </div>
  <div class="tqa-summary-card" markdown>
  ### How dense is the infiltrate?

  TumorQuantAI reports CD3 and CD8 positive-cell counts, analysed area, and
  cells/mm² for each proxy compartment, with automatic QC and auditable
  settings.
  </div>
</div>

## Why this is not the consensus assay

The validated colon-cancer Immunoscore measures CD3 and CD8 cell densities in
the tumour core and invasive margin. The invasive margin is a 720 µm region
centred on the tumour boundary, and four density percentiles are referenced to
a validated 700-case population before they are averaged. Pathologist review
of the tumour and margin regions is part of that process.

This dataset instead contains adjacent CD3, CD8, and CK20 sections. CK20 helps
separate epithelial from non-epithelial tissue, but it does not establish CT
and IM. CK20 expression is linked to epithelial differentiation and can vary
between the tumour centre and leading edge, so it cannot define the entire
invasive boundary. TumorQuantAI makes the distinction explicit:

| Output | Region definition | Reference distribution | Intended use |
| --- | --- | --- | --- |
| Consensus Immunoscore | Pathologist-validated CT and 720 µm IM | Validated external 700-case cohort | Not available here |
| TumorQuantAI CK20-guided proxy | CK20-positive epithelial proxy and CK20-negative common-tissue proxy | This cohort only | Research exploration and QC |

See the consensus validation
[in *The Lancet*](https://doi.org/10.1016/S0140-6736(18)30789-X),
the [analytical validation protocol](https://pmc.ncbi.nlm.nih.gov/articles/PMC7253006/),
the [CK20 spatial-expression caveat](https://pmc.ncbi.nlm.nih.gov/articles/PMC4128715/),
and the [VALIS serial-WSI registration paper](https://doi.org/10.1038/s41467-023-40218-9).

## Install

```bash
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai

./tumorquantai install --conda
export PATH="$HOME/.local/bin:$PATH"

tumorquantai --inmunoscore --help
```

The command is package-native and does not invoke HistoPLUS or Nextflow.
`tumorquantai ihc immunoscore` is the canonical subcommand;
`tumorquantai --inmunoscore` is the requested top-level compatibility form.

## Prepare the private input

Keep original archives, extracted scanner bundles, alias secrets, and linkage
tables outside Git:

```text
controlled-colon-ihc/
├── archives/                         # original ZIPs
├── private_source/
│   └── extracted/inmunoscore/
│       └── <private-case>-CD3-.../
│           ├── 1.mds
│           └── info.ini
├── private_release/
│   ├── alias_secret.bin              # mode 0600, at least 32 random bytes
│   └── case_slide_linkage.csv         # created by the run; mode 0600
└── results/
```

Create the one-time secret without printing it:

```bash
install -d -m 700 /controlled/colon-ihc/private_release
head -c 32 /dev/urandom > /controlled/colon-ihc/private_release/alias_secret.bin
chmod 600 /controlled/colon-ihc/private_release/alias_secret.bin
```

Do not regenerate this file between runs. The same secret and source IDs
produce the same aliases; another secret produces unrelated aliases.

## How cases are linked

TumorQuantAI does not infer case identity from staining intensity, filenames
that merely look similar, or pathologist values. It uses an exact rule:

1. The immediate bundle name must match
   `<source-case-id>-CD3|CD8|CK20-<scanner-suffix>`.
2. The exact text before the marker token is the private case ID.
3. HMAC-SHA-256 with the owner-controlled secret creates one
   `TQA_CI_...` case alias.
4. The complete bundle name independently creates a `TQA_CIS_...` slide alias.
5. A source case may have at most one slide for each marker.

The controlled CSV records the complete evidence chain:

```text
case_alias
slide_alias
source_case_id
source_slide_id
marker
source_mds_path
source_mds_size_bytes
source_mds_sha256
```

Only `case_alias`, `slide_alias`, marker, and non-identifying acquisition facts
appear in public results. The private linkage is required for exact audit and
must never be uploaded to Zenodo or committed to Git.

## Run the cohort

Set paths once:

```bash
TQA_MDS=/controlled/colon-ihc/private_source/extracted/inmunoscore
TQA_RESULTS=/controlled/colon-ihc/results/tumorquantai_immunoscore
TQA_SECRET=/controlled/colon-ihc/private_release/alias_secret.bin
TQA_LINKAGE=/controlled/colon-ihc/private_release/case_slide_linkage.csv
```

### 1. Inventory-only preview

```bash
tumorquantai --inmunoscore "$TQA_MDS" \
  --output "$TQA_RESULTS" \
  --alias-secret-file "$TQA_SECRET" \
  --private-linkage "$TQA_LINKAGE" \
  --workers 3 \
  --dry-run
```

The preview reads the private Motic `info.ini` scale and reports complete and
incomplete marker sets. It does not hash WSIs, create linkage, or write output.

### 2. Quantify

Remove only `--dry-run`:

```bash
tumorquantai --inmunoscore "$TQA_MDS" \
  --output "$TQA_RESULTS" \
  --alias-secret-file "$TQA_SECRET" \
  --private-linkage "$TQA_LINKAGE" \
  --workers 3
```

The run is resumable by default. It verifies the exact private linkage before
reusing a completed case and refuses a non-empty foreign output directory.
Use `--no-resume` only when intentionally starting with a new empty output.

## What TumorQuantAI does

<div class="tqa-run-strip">
<span><strong>Read</strong> DSI0 pixels only</span>
<span><strong>Register</strong> CD3/CD8 → CK20</span>
<span><strong>Segment</strong> expected-brown H–DAB objects</span>
<span><strong>Report</strong> counts, area, cells/mm², QC</span>
</div>

### 1. Read the Motic pyramid safely

The package opens only `DSI0` pixel tile streams from each MDS compound file.
Label, macro, and acquisition streams are inaccessible to the quantifier.
Physical scale comes from the private Motic `info.ini`; an optional
`--source-mpp` assertion must agree with it exactly.

The analysis level nearest 0.55 µm/pixel is selected by default. For scans at
0.261780 µm/pixel this is the 0.5 pyramid level, 0.523560 µm/pixel.

### 2. Register serial sections

Bounded overviews are formed from DSI0 tiles. SIFT and ORB feature candidates,
partial/full affine transforms, and a tissue-bounding-box fallback are scored
by tissue Dice. The best geometrically valid transform is retained. A Dice
below `--minimum-registration-dice` never becomes a silent zero; it produces a
review status. The feature-free tissue-bounding-box fallback is also always
review-only, even when its global tissue Dice is high.

### 3. Form CK20-guided proxy compartments

Direct stain separation on a 2048-pixel WSI overview can average focal brown
glands into the background. TumorQuantAI therefore streams the CK20 pyramid at
the level nearest 2.0 µm/pixel (2.094240 µm/pixel for this cohort), performs
colour-checked H–DAB separation in each block, and area-projects the fraction
of expected-brown pixels into the bounded registration overview. An overview
pixel enters the raw proxy when at least 2% of its contributing fine pixels
pass the 0.08 DAB-OD threshold.

Connected regions smaller than 1,000 µm² are removed, subject to a four-pixel
minimum at the realised overview resolution. Retained regions are closed and
expanded by 8 µm to form `ck20_epithelium_proxy`; common registered tissue
outside the mask is `ck20_stroma_proxy`. Pyramid coordinates are converted by
their numeric level scale and the explicit overview resize—not by padded tile
canvas ratios. This matters because MDS levels can have different amounts of
white edge padding.

Every `measurement.json` records the selected CK20 level, realised µm/pixel,
block counts, fine-pixel DAB fraction, projected-fraction threshold and range,
raw/final compartment fractions, overview scale, and effective morphology.
Treat these assignments as coarse CK20-guided WSI compartments, not
cellular-resolution tumour or invasive-margin annotations.

### 4. Stream CD3/CD8 object detection

Each immune WSI is processed in bounded blocks, so the full 100,000-pixel-scale
image is never materialized in memory. Counterstained and DAB-positive objects
are watershed-segmented. A 3 µm expanded-cell region is positive when either:

```text
mean expected-brown DAB OD ≥ 0.16
OR
at least 8% of expanded-cell pixels have DAB OD ≥ 0.16
```

An 8 µm strip is excluded at block boundaries from cell centres and the
corresponding analysed footprint to reduce clipped/duplicate objects.
A marker with no segmented nuclei remains numerically auditable but is forced
to review status; it cannot enter the pass-only cohort statistics or ranks.

### 5. Map and quantify

Every retained centroid is transformed from the immune analysis level through
the moving overview into CK20 coordinates. This transform uses the numeric MDS
pyramid scale plus any explicit overview resize so differing tile padding does
not shift cells. Counts are divided by the matching common-tissue compartment
area:

```text
positive-cell density = mapped positive cells / analysed compartment area (mm²)
```

The four headline TumorQuantAI values are:

```text
tumorquantai_cd3_ck20_epithelium_density_per_mm2
tumorquantai_cd3_ck20_stroma_density_per_mm2
tumorquantai_cd8_ck20_epithelium_density_per_mm2
tumorquantai_cd8_ck20_stroma_density_per_mm2
```

### 6. Rank this cohort without impersonating validation

Only automatic-QC-pass cases receive deterministic mid-rank percentiles.
TumorQuantAI averages the four internal percentiles and labels the internal
rank as low (≤25), intermediate (>25–70), or high (>70). These thresholds make
the current cohort easier to inspect; they are not a clinical score and are
not comparable to the validated reference distribution.

## Review the results

Open:

```text
results/tumorquantai_immunoscore/START_HERE.html
```

Review in this order:

1. Confirm the expected complete and incomplete marker sets.
2. Open every `registration_qc.png`.
3. Reject or correct implausible serial-section registration.
4. Review the CK20 epithelial proxy across both tumour centre and leading edge.
5. Check analysed area and mapped-positive-cell fraction.
6. Only then interpret the density tables.

The output map is:

```text
tumorquantai_immunoscore/
├── START_HERE.html
├── cases/<case_alias>/
│   ├── measurement.json
│   └── registration_qc.png
├── tables/
│   ├── public_slide_inventory.csv
│   ├── tumorquantai_immunoscore_values.csv
│   ├── cohort_density_summary.csv
│   ├── case_compartment_densities.csv
│   ├── registration_qc.csv
│   └── unavailable_cases.csv
└── workflow_metadata/
    ├── immunoscore_run.json
    └── failures.json                    # only when a case failed
```

### What the numbers mean

| File | Use it for | Important boundary |
| --- | --- | --- |
| `tumorquantai_immunoscore_values.csv` | One clear row per anonymous case and all four density values | Internal percentiles are blank for review/failed/incomplete cases |
| `cohort_density_summary.csv` | Mean, sample SD, median, quartiles, and range for each density under pass-only and all-numeric populations | Population and `n` are explicit; review cases never silently enter pass-only statistics |
| `case_compartment_densities.csv` | Counts, areas, densities, mapping fraction, MPP, and QC in long format | A technically completed row can still require review |
| `registration_qc.csv` | Transform method, feature matches, inliers, tissue Dice, and affine matrix | Automated Dice does not replace visual review |
| `unavailable_cases.csv` | Missing-marker and failed-case audit | Missing is never encoded as biological zero |

## Zenodo privacy boundary

The release workflow creates new MDS files under non-semantic HMAC-derived
slide aliases. It
preserves every DSI0 pixel stream byte-for-byte and replaces all label, macro,
and non-pixel OLE streams with deterministic same-size generic neutral content.
The replacement payload never repeats a source stream name. Each staged file
is then checked for:

- exact DSI0 stream names and bytes;
- full and sampled DSI0 fingerprints;
- deterministic non-pixel replacement;
- absence of case and bundle-name variants in UTF-8, Latin-1, UTF-16LE, and
  UTF-16BE;
- decodability and pyramid geometry;
- visual tissue-pixel review.

The original ZIPs, sidecars, source filenames, alias secret, private linkage,
and private sanitizer mapping remain outside the deposit. A new Zenodo entry
is created as a **restricted, unsubmitted draft**. TumorQuantAI contains no
publication action for this dataset; publication requires a separate human
rights/privacy/metadata decision after visual review.

## Limitations to carry into every report

- Serial sections are not cell-for-cell identical.
- CK20 is an epithelial aid, not a complete colorectal tumour-boundary marker.
- The DAB thresholds are deterministic research settings, not assay
  calibration.
- Automatic tissue Dice can miss local misregistration.
- No tumour core or invasive margin has been reviewed.
- Internal ranks are cohort-relative and will change with cohort composition.
- Outputs must not guide patient care.

For the exact CLI contract and CSV schemas, see
[CK20-guided CD3/CD8 reference](../reference/colon-ihc-immunoscore.md).
