# Breast IHC case linkage and privacy

This page explains how the reference breast-IHC analysis associated public
TumorQuantAI case aliases with the pathologist workbook, what was checked, and
which artifacts must remain outside GitHub.

!!! info "The short answer"
    TumorQuantAI did not guess a case identity from an image or marker value.
    Each public alias was assigned when the image dataset was released, and a
    protected release linkage retained the corresponding source `case_id`.
    The pathologist workbook was linked through its `Biopsia` identifier.
    Computational and pathologist values were joined only after both sides had
    the same public `case_alias`.

## Identity chain

There are three identifier domains:

```text
authorized source images
    private case_id
         │
         │ protected release linkage created before publication
         ▼
public image dataset
    TQA_BC_<public-alias>
         ▲
         │ exact identifier match or explicit reviewed crosswalk
         │
pathologist workbook
    sheet: Biopsias finales incluidas
    column: Biopsia
```

The protected release linkage contains one row per published patch, including
the original source `case_id` and its public `case_alias`. Repeated patch rows
are reduced to a unique case-to-alias relationship only after verifying that
each source case has one alias and each alias has one source case.

The clinical export then:

1. reads only `Biopsias finales incluidas`;
2. reads the workbook key only from `Biopsia`;
3. reads the release key only from `case_id`;
4. requires a unique one-to-one identifier solution;
5. assigns the already existing public alias to the matched pathologist row;
6. removes the biopsy identifier and all non-marker clinical fields; and
7. joins the minimum pathologist table to TumorQuantAI output by exact
   `case_alias`.

No ER, PR, HER2, Ki-67, diagnosis, age, or other clinical value participates
in identity matching.

## Reference-cohort linkage audit

The controlled audit for the 51-case reference cohort produced the following
aggregate result:

| Check | Result |
| --- | ---: |
| Protected release-linkage rows | 1,901 patch rows |
| Unique release `case_id` ↔ `case_alias` pairs | 51 |
| Included workbook rows | 51 |
| Identifier pairs matching exactly in the audit representation | 48 |
| Reviewed one-character discrepancies | 3 |
| Ambiguous, duplicate, or unmatched final cases | 0 |
| Final pathologist rows keyed by public alias | 51 |
| Marker values used to establish identity | 0 |

For the audit, the custodian compared a case-folded alphanumeric
representation of the two private identifier columns. Each of the three
remaining identifiers had exactly one one-character-different candidate, and
the complete result remained one-to-one. Those discrepancies were recorded in
the controlled mapping audit.

This Hamming-distance check is an audit description, **not** an automatic
TumorQuantAI matching rule. TumorQuantAI never performs fuzzy linkage. A
discrepancy must be reviewed by the data custodian and supplied as an explicit
private crosswalk before package ingestion.

## What the package enforces

`tumorquantai ihc anonymize-clinical` normalizes string identifiers by
case-folding, trimming leading and trailing whitespace, and collapsing
internal whitespace. Spreadsheet integers and integer-valued floats are
represented consistently. It does not silently remove arbitrary punctuation,
calculate edit distance, or search marker columns for a likely match.

When exact normalized identifiers do not agree, the optional
`--identifier-crosswalk` file must:

- be a regular, non-symlink file with exact mode `0600`;
- contain `linkage_id,clinical_id`;
- be non-empty and one-to-one;
- account for every supplied crosswalk row; and
- yield one unique, complete release-alias-to-workbook solution.

The command fails closed if the solution is missing, duplicated, ambiguous, or
incomplete. Provenance records the selected sheet and identifier columns,
whether a crosswalk was used, its row count and SHA-256 checksum, and
`marker_values_used_for_linkage: false`.

## Controlled mapping CSV

The cohort custodian also retains a direct-ID audit table:

```text
case_id_to_pathologist_biopsy_linkage_controlled.csv
```

Its schema is:

```text
case_alias
release_case_id
pathologist_biopsy_id
identifier_match_method
normalized_hamming_distance
```

This table answers exactly which source case and workbook biopsy produced each
public alias. Because it contains both original identifier systems, it is
more sensitive than the pseudonymized marker export. It must remain in a
mode-`0700` controlled directory as a mode-`0600` file. Its companion
provenance records the source checksums and aggregate matching audit.

The direct-ID table is not a TumorQuantAI report output and is never copied
into the agreement directory. Do not commit it, attach it to an issue, place
it in a public release, or upload it to Zenodo.

## File-by-file privacy boundary

| Artifact | Identifier content | Access |
| --- | --- | --- |
| Public Zenodo image archives and manifest | Public case and patch aliases | Public |
| TumorQuantAI source, tests, and documentation | No private case linkage | Public |
| Aggregate reference concordance CSVs | Marker-level summaries, no case rows | Public after review |
| Protected release linkage | Source IDs, source paths, and public aliases | Controlled; never Git |
| Original pathologist XLSX | Direct identifiers and clinical fields | Controlled; never Git |
| Direct-ID audit CSV | Both private ID systems plus public alias | Controlled; never Git |
| Six-field pathologist CSV | Public alias plus marker values | Pseudonymized; controlled |
| Paired agreement case CSVs | Public alias plus both raters' values | Pseudonymized; controlled |
| Full agreement directory | Includes the paired case CSVs | Controlled by default |

Pseudonymized is not the same as anonymous. Removing names and biopsy numbers
does not make case-level health data safe for unrestricted publication.

## Authoritative reference run

The reference values in the tutorial come from the final
`hdab-color-checked-watershed-membrane-proxy-v2` analysis, not from an earlier
unconstrained HED run. It completed 1,516 included IHC patches with no
processing failures and produced 203 case-marker rows. ER changed from an
all-positive unconstrained audit result (κ = 0) to both negative and positive
v2 calls (κ = 0.231 in this cohort).

On the controlled maintainer workstation, the retained authoritative
artifacts are:

```text
tumorquantai_ihc_results_v2_final/       # final computational run
private_analysis/
├── pathologist_markers_pseudonymized.csv
├── pathologist_markers_pseudonymized.csv.provenance.json
├── case_id_to_pathologist_biopsy_linkage_controlled.csv
├── case_id_to_pathologist_biopsy_linkage_controlled.csv.provenance.json
└── agreement_v2/                        # final concordance report
```

These are workspace artifacts, not files installed by a Git clone.
Superseded intermediate run directories were removed from the active
workspace. They are not sources for the published aggregate tables.

## What GitHub contains

GitHub contains the reproducible implementation, tests, English workflow
documentation, the linkage audit counts above, and reviewed aggregate
reference metrics. It intentionally does **not** contain:

- the original workbook;
- original case or biopsy identifiers;
- the alias secret or protected release linkage;
- the direct-ID mapping CSV or its provenance;
- the six-field case-level pathologist CSV;
- paired case-level concordance rows; or
- multi-gigabyte generated result directories.

Therefore, cleaning old generated runs or creating a controlled mapping CSV
does not create a Git change. Documentation and aggregate results can be
pushed; private linkage material cannot.

## Reproduction checklist

Before calculating agreement for another cohort:

- select the workbook sheet explicitly;
- select both identifier columns explicitly;
- verify one source case ↔ one public alias;
- resolve discrepancies through human review and a mode-`0600` crosswalk;
- verify that no marker value was used for identity;
- inspect the anonymization provenance before continuing;
- join the two raters only on exact public aliases;
- keep every case-level clinical or paired table under controlled access; and
- publish only separately reviewed aggregate outputs.

Continue with the
[breast-IHC quantification tutorial](../tutorials/breast-ihc-patches.md) or
inspect the [IHC output reference](outputs.md).
