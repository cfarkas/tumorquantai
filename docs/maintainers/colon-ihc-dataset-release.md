# Colon IHC dataset release

This procedure creates a **new restricted, unsubmitted Zenodo draft** for the
30-slide CD3/CD8/CK20 Motic cohort. It does not create a new version of an
existing record and it contains no publication action.

## Fixed release contract

The release must contain exactly:

- 30 sanitized MDS files;
- 40,580,793,856 MDS bytes;
- 10 CD3, 10 CD8, and 10 CK20 slides;
- 11 anonymous cases, of which 9 have all three markers;
- aliases matching `TQA_CIS_[A-Z2-7]{20}`;
- source MPP 0.261780 µm/pixel;
- sanitization profile `pixel-preserving-nonpixel-redaction-v2`.

Stop if any value differs. Do not weaken the constants to make an unexpected
roster pass.

## Never place these in Git or Zenodo

- original ZIP archives;
- original MDS names or parent-directory names;
- Motic `info.ini`, `info.xml`, JPG, PTS, or other sidecars;
- original label or macro streams;
- the HMAC alias secret;
- `case_slide_linkage.csv`;
- the sanitizer's private mapping;
- Zenodo token or draft state;
- any path containing the controlled storage layout.

The release uses DSI0 tissue pixels. A random alias is pseudonymization, not a
guarantee that visible tissue pixels are anonymous. Independent human review
of every overview remains mandatory.

## 1. Finish and review the analysis

Run the package-native workflow described in the
[colon IHC tutorial](../tutorials/colon-ihc-wsi-immunoscore.md). Confirm:

1. `public_slide_inventory.csv` has 30 rows and no source ID/path columns.
2. `tumorquantai_immunoscore_values.csv` has all 11 case aliases.
3. Missing marker sets are unavailable, not zero.
4. Every complete case has a registration composite.
5. The official consensus score is blank with the explicit unavailable status.
6. Every complete case has one case sheet and three marker-specific 300-dpi
   review sheets, with 36 rows in `paper_figure_manifest.csv`.
7. The pI0-pI4 field is explicitly provisional, uses the automatic-pass
   reference `n`, and is never copied into `consensus_immunoscore`.
8. `pathologist_review_template.csv` has blank decision/reviewer fields.
9. Every registration and CK20 compartment mask has been visually reviewed.

## 2. Create sanitized MDS copies

Keep staging and both mappings outside the repository. The input mapping is the
mode-0600 private linkage created by TumorQuantAI:

```bash
python3 bin/prepare_zenodo_mds.py --alias-profile colon-immunoscore --alias-mapping /controlled/private_release/case_slide_linkage.csv --staging-dir /controlled/release_draft/sanitized_mds --public-manifest /controlled/release_draft/tumorquantai_colon_immunoscore_mds_manifest.csv --private-mapping /controlled/private_release/sanitized_mds_private_mapping.csv --expected-count 30 --source-mpp 0.261780 --resume
```

For each source, the preparer:

1. reflinks or copies without modifying the source;
2. preserves every DSI0 stream byte-for-byte;
3. replaces label, macro, and all other non-pixel streams with deterministic,
   same-size generic neutral content that does not repeat the source stream
   name;
4. reopens source and staged OLE structures and compares every DSI0 byte;
5. computes full and sampled pixel fingerprints;
6. scans the entire staged file for original, lower-case, and upper-case
   private source-name markers in UTF-8, Latin-1, UTF-16LE, and UTF-16BE;
7. records source/staged hashes only in the mode-0600 private mapping.

The public manifest contains only aliases, geometry, physical scale, sanitized
file hashes, and pixel fingerprints.

## 3. Review visible pixels

Generate a DSI0 tissue overview and neutral-label/macro panel from every
sanitized MDS:

~~~bash
python3 bin/review_zenodo_immunoscore_pixels.py --staging-dir /controlled/release_draft/sanitized_mds --public-manifest /controlled/release_draft/tumorquantai_colon_immunoscore_mds_manifest.csv --output-dir /controlled/private_release/visual_review --workers 4 --resume
~~~

Inspect all five contact sheets and, when anything is ambiguous, the
corresponding 1600-pixel overview.
Record reviewer, date, and outcome in the controlled release log. Confirm:

- no glass label, handwriting, accession, name, date, barcode, or QR code is
  visible in DSI0 tissue pixels;
- the embedded label and macro streams show only neutral content;
- tissue appearance and pyramid geometry remain intact;
- marker and anonymous case mapping agree with the public inventory.

Do not upload when even one slide is unreviewed or ambiguous.

## 4. Build flat public artifacts

After the analysis and MDS manifest are final:

```bash
python3 bin/package_zenodo_immunoscore_release.py --public-manifest /controlled/release_draft/tumorquantai_colon_immunoscore_mds_manifest.csv --public-slide-inventory /controlled/results/tumorquantai_immunoscore/tables/public_slide_inventory.csv --analysis-results /controlled/results/tumorquantai_immunoscore --output-dir /controlled/release_draft/public_artifacts
```

The packager fails on private ID/path markers and creates:

- an anonymous case/slide/marker catalog;
- clear wide and long TumorQuantAI CSVs;
- numeric and visual registration QC;
- the blank pathologist accept/flag/exclude template, codebook, and offline dashboard;
- the paper-figure manifest and one deterministic ZIP containing 36 PNG/PDF/legend triplets;
- an English README and portable HTML report;
- method/provenance JSON;
- a release validation report;
- SHA-256 and MD5 rosters covering the MDS files and public artifacts.

The public artifact directory must be flat. Metadata, draft state, token, and
private mappings stay elsewhere.

## 5. Prepare restricted draft metadata

Use a new mode-0600 JSON file:

```json
{
  "metadata": {
    "title": "TumorQuantAI colon cancer CD3, CD8, and CK20 whole-slide image dataset",
    "description": "De-identified Motic MDS serial-section WSIs with an anonymous marker catalog, pixel-preserving sanitization evidence, TumorQuantAI CK20-guided CD3/CD8 research densities, provisional within-cohort pI0-pI4 review labels, pathologist accept/flag templates, and registration QC. The provisional label is not the clinically validated consensus Immunoscore.",
    "upload_type": "dataset",
    "access_right": "restricted",
    "access_conditions": "Access requests require custodian review of research purpose, data protection, redistribution restrictions, and applicable ethics or institutional approvals.",
    "creators": [
      {"name": "Farkas, Carlos"}
    ],
    "keywords": [
      "digital pathology",
      "colorectal cancer",
      "immunohistochemistry",
      "CD3",
      "CD8",
      "CK20",
      "whole-slide imaging"
    ],
    "related_identifiers": [
      {
        "identifier": "https://github.com/cfarkas/tumorquantai",
        "relation": "isSupplementTo",
        "scheme": "url"
      }
    ]
  }
}
```

Do not add a license until the dataset custodian has documented the authority
to grant it. Restricted access is not a substitute for redistribution rights.

## 6. Create a new draft

Use a brand-new absent state path. The absence of state is what makes the
depositor call Zenodo's create-draft endpoint. Reusing an earlier state resumes
that earlier draft and is therefore forbidden for this release:

```bash
python3 bin/zenodo_immunoscore_deposit.py --public-manifest /controlled/release_draft/tumorquantai_colon_immunoscore_mds_manifest.csv --private-mapping /controlled/private_release/sanitized_mds_private_mapping.csv --public-dir /controlled/release_draft/public_artifacts --metadata /controlled/private_release/zenodo_colon_metadata.json --state /controlled/private_release/zenodo_colon_new_entry_state.json --plan
```

Review the network-free plan: exactly 30 MDS files, the fixed byte total, the
expected public artifacts, no more than 100 files, no file above 50 GB, and
less than 50,000,000,000 bytes in total. The 40,580,793,856-byte MDS roster
leaves room for the small reports and QC images under Zenodo's default record
quota. See Zenodo's [current file limits](https://help.zenodo.org/docs/deposit/manage-files/).

Then create and upload the new draft:

```bash
python3 bin/zenodo_immunoscore_deposit.py --public-manifest /controlled/release_draft/tumorquantai_colon_immunoscore_mds_manifest.csv --private-mapping /controlled/private_release/sanitized_mds_private_mapping.csv --public-dir /controlled/release_draft/public_artifacts --metadata /controlled/private_release/zenodo_colon_metadata.json --state /controlled/private_release/zenodo_colon_new_entry_state.json --token-file /controlled/private_release/zenodo_token --workers 4
```

The token file must be regular, owner-controlled, and mode 0600. The depositor
accepts only production or sandbox Zenodo HTTPS API origins. It verifies every
local hash before upload, resumes exact remote size/MD5 matches, rejects
unreviewed extra files, rechecks restricted metadata, and records state
atomically. Sequential mode opens a fresh HTTPS session for each file and stops
when a one-minute window advances by less than 8 MiB; rerun the exact command to recover
from a transient Zenodo stall. A response lost after remote commit is recovered
as `verified-existing` on the next run.

### Expanding public review artifacts in the same unsubmitted draft

Do this only when the raw 30-slide roster is unchanged and a reviewed report,
figure, or adjudication artifact was added while this exact draft was still
uploading. First stop every uploader for the draft, rebuild the release package,
review its checksum/roster diff, and run `--plan`. Then resume with both explicit
safety switches:

```bash
python3 bin/zenodo_immunoscore_deposit.py --public-manifest /controlled/release_draft/tumorquantai_colon_immunoscore_mds_manifest.csv --private-mapping /controlled/private_release/sanitized_mds_private_mapping.csv --public-dir /controlled/release_draft/public_artifacts --metadata /controlled/private_release/zenodo_colon_metadata.json --state /controlled/private_release/zenodo_colon_new_entry_state.json --token-file /controlled/private_release/zenodo_token --workers 4 --adopt-expanded-release --replace-mismatched
```

`--adopt-expanded-release` is not a general fingerprint override. It requires
the same restricted, editable deposition; rejects remote files outside the new
reviewed roster; requires every checkpoint to remain present and unchanged;
forbids removing checkpointed files; requires the authoritative MDS manifest to
be byte-for-byte unchanged; and refuses replacement of any MDS under all
circumstances. The unchanged manifest binds even WSIs that have not uploaded
yet. The command records the old and new release fingerprints in the private
state. Never run it concurrently with another uploader or use it to change the
WSI roster.

## 7. Stop at the draft

The command has no `--publish` option. After upload:

1. open the exact draft URL;
2. confirm it is restricted and unsubmitted;
3. compare the complete remote roster with both checksum files;
4. repeat the independent visible-pixel review from downloaded draft files;
5. obtain documented privacy, ethics, redistribution-rights, license, and
   metadata approval;
6. request a separate explicit publication decision.

Do not treat “uploaded” or “anonymized” as permission to publish. Zenodo record
metadata becomes public if the draft is eventually published even when file
visibility is restricted, so metadata itself also requires privacy review.

## GitHub boundary

GitHub receives only reusable source code, automated tests, and English
documentation. It does not receive raw/sanitized WSIs, case-level release
artifacts, private mappings, tokens, state, or controlled review logs.
