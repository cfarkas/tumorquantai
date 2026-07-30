# Input manifest schema

The existing discovery engine writes
`workflow_metadata/slides.tsv` and `workflow_metadata/slides.json`. The TSV is
the human-reviewable roster; the JSON has a top-level `slides` array with the
same rows.

| Field | Meaning |
| --- | --- |
| `sample_id` | Collision-safe output/matrix identifier |
| `slide_path` | Resolved primary L0 path |
| `relative_path` | Primary path relative to input root |
| `size_bytes` | L0 file size |
| `mtime_ns`, `ctime_ns`, `device`, `inode` | Filesystem identity metadata |
| `fingerprint` | Stream-safe primary identity used in workflow caching |
| `l2_path`, `l2_exists`, `l2_size_bytes`, `l2_mtime_ns` | Companion location/state |
| `l2_content_sha256` | L2 content checksum when the companion is used |
| `l2_fingerprint` | Companion identity or explicit missing/not-used state |

The `inspect` command adds review-oriented format, pyramid, MPP, duplicate, and
storage information in its own manifest/report while retaining discovery
semantics.

## Sample sheet input

The user sample sheet is UTF-8 CSV or TSV containing at least:

```csv
sample_id,slide_path
sample_001,case_001/1_L0_rgb.tif
```

Paths may be relative to the input root or absolute within it. Empty or
duplicate IDs, duplicate primary paths, reserved IDs, files outside the input
root, and missing required L2 companions are rejected.

Sample IDs and paths can be sensitive. Use neutral aliases and do not commit
patient identifiers or study manifests.
