# Create the restricted Zenodo draft

This procedure uploads the lymphoma collection as a **restricted, unpublished
draft**. The supplied command cannot publish it.

## Human release gates

Before any later publication, an accountable data owner must confirm:

- authority to redistribute the slide pixels;
- applicable ethics, consent, and institutional requirements;
- successful automated and human privacy review;
- the dataset-matched software tag exists at its reviewed immutable commit;
- approved creators, affiliations, description, keywords, and contact;
- the exact dataset license and restricted-access conditions; and
- the final file list and checksums.

A technical pass does not grant legal or ethical permission to publish.

## 1. Private preparation inputs

Create a mode-0600 CSV containing at least:

```csv
alias,source_mds_path
TumorQuantAI_LymphomaWSI_001,/private/source/slide_001/1.mds
```

Aliases must match `TumorQuantAI_LymphomaWSI_NNN`; source paths must be regular
`.mds` files. The local release workspace already has this protected mapping.
Never commit or upload it.

```bash
export RELEASE=/secure/TumorQuantAI_Lymphoma_Zenodo
chmod 600 "$RELEASE/private/alias_mapping_private.csv"

python bin/prepare_zenodo_mds.py \
  --alias-mapping "$RELEASE/private/alias_mapping_private.csv" \
  --staging-dir "$RELEASE/private/mds_staging" \
  --public-manifest "$RELEASE/public/generated/tumorquantai_lymphoma_mds_manifest.csv" \
  --private-mapping "$RELEASE/private/mds_source_mapping.csv" \
  --exclude-alias TumorQuantAI_LymphomaWSI_010 \
  --expected-count 21 \
  --source-mpp 0.261780 \
  --resume
```

The source files are read-only. The command writes deterministic neutral
non-pixel streams, checks the pixel-stream roster, computes schema-version-2
ordered aggregate SHA-256 digests over every `DSI0` stream name, length, and
byte, requires source and staged digests to match, retains sampled fingerprints
as supplemental diagnostics, reopens each MDS, scans source markers, and
writes separate public/private manifests.

Required MDS result:

- 21 staged files;
- 17,370,771,968 MDS bytes;
- mode 0600 for every staged MDS and private mapping; and
- schema-version-2 public manifest with exactly 21 rows.

## 2. Complete authorized metadata

`private/metadata.json` must contain no placeholder values:

```json
{
  "metadata": {
    "title": "TumorQuantAI lymphoma H&E whole-slide image tutorial dataset",
    "description": "Twenty-one privacy-sanitized H&E MDS whole-slide images for the TumorQuantAI v0.4.0 technical tutorial.",
    "upload_type": "dataset",
    "access_right": "restricted",
    "access_conditions": "Access requires approval from the accountable data controller and confirmation of the intended research use.",
    "license": "",
    "creators": [{"name": "Farkas, Carlos"}],
    "related_identifiers": [
      {
        "identifier": "https://github.com/cfarkas/tumorquantai/releases/tag/v0.4.0",
        "relation": "isSupplementedBy",
        "scheme": "url"
      }
    ]
  }
}
```

For the restricted draft, the legacy deposition API permits the license field
to be blank or omitted; non-empty access conditions remain mandatory. Do not
infer a license on behalf of the data owner. Set the exact authorized Zenodo
license ID before any later publication.

## 3. Create a limited token

In Zenodo, open **Applications → Personal access tokens** and create a token
with only `deposit:write`. `deposit:actions` is not required because this tool
has no publication action.

```bash
umask 077
read -rsp "Zenodo token: " ZENODO_TOKEN
printf '%s' "$ZENODO_TOKEN" > "$RELEASE/private/zenodo_token"
unset ZENODO_TOKEN
printf '\n'
chmod 600 "$RELEASE/private/zenodo_token"
```

Never paste the token into chat, a command argument, an issue, or a log.

## 4. Validate the exact plan

```bash
python bin/zenodo_mds_deposit.py \
  --public-manifest "$RELEASE/public/generated/tumorquantai_lymphoma_mds_manifest.csv" \
  --private-mapping "$RELEASE/private/mds_source_mapping.csv" \
  --metadata "$RELEASE/private/metadata.json" \
  --state "$RELEASE/private/zenodo_mds_deposit_state.json" \
  --token-file "$RELEASE/private/zenodo_token" \
  --plan
```

The current release plan must report:

- `mds_file_count: 21`;
- `mds_total_size_bytes: 17370771968`;
- `file_count: 22` (21 MDS plus the authoritative manifest);
- `total_size_bytes` equal to 17,370,771,968 plus the exact
  schema-version-2 manifest size reported by the plan;
- `restricted: true`; and
- `draft_only: true`.

## 5. Upload or resume

Run the same command without `--plan`:

```bash
python bin/zenodo_mds_deposit.py \
  --public-manifest "$RELEASE/public/generated/tumorquantai_lymphoma_mds_manifest.csv" \
  --private-mapping "$RELEASE/private/mds_source_mapping.csv" \
  --metadata "$RELEASE/private/metadata.json" \
  --state "$RELEASE/private/zenodo_mds_deposit_state.json" \
  --token-file "$RELEASE/private/zenodo_token" \
  --workers 4
```

The state is mode 0600 and is bound to the exact metadata and file hashes.
Repeating the command verifies matching remote files and uploads only missing
ones. A state from another release or a draft containing unexpected files is
rejected before metadata or files are changed.

`--workers 1` is the sequential default. Values from 2 through 4 use bounded
parallel uploads with an independent HTTPS session per worker. All pending
local files are verified before any remote replacement, and each successful
upload is recorded atomically, so the same command safely resumes after a
connection or worker failure.

## 6. Review the draft

Confirm in Zenodo:

- visibility is restricted and the record is still unpublished;
- 21 `.mds` files plus the public manifest are present;
- every MDS filename is a public alias;
- sizes and MD5 values match the manifest;
- no private mapping, source accession, label, sidecar, clinical file,
  unrelated project material, special stain, or token is present; and
- title, creators, description, license, access conditions, and the
  dataset-matched immutable software link are correct.

An unpublished deposition cannot be used by the public tutorial downloader.
After an authorized human publishes the record, place its final ID/DOI in the
tutorial and repeat the one-slide and four-slide acceptance paths from a clean
download. A published restricted record still requires authorized access.
