# Status and report JSON

Print machine-readable summaries to standard output:

```bash
tumorquantai status OUTPUT --json > status.json
tumorquantai report OUTPUT --json > report-output.json
```

`report` also writes `OUTPUT/tumorquantai_report.json` and
`OUTPUT/START_HERE.html`.

Human `status` output is a local operational view: it may print exact
filesystem paths for a directly runnable resume command and the first log.
Review and redact that terminal output before sharing it. By contrast, the
`--json` and HTML/report forms use share-oriented path redaction and relative
links. Credential/token/weight locations are never recorded in either form.

## Stable top-level fields

Both status and report use:

| Field | Meaning |
| --- | --- |
| `schema_version` | Versioned machine-readable contract |
| `generated_at_utc` | Generation timestamp |
| `output_name` | Redacted/basename result identity |
| `overall_status` | `PASS`, `WARN`, or `FAIL` |
| `counts` | Completed, failed, incomplete, excluded, pending, and biological-zero totals |
| `samples` | Sample IDs grouped by those states |
| `reasons` | Available non-secret failure/exclusion reasons |
| `resume_command` | Recorded command with sensitive paths/values redacted |
| `first_log` | First relative log to inspect, or null |
| `run` | Available software/container/model/MPP/sampling/dataset provenance |
| `interpretation` | Explicit failed-versus-biological-zero guardrail |

The report payload additionally includes `links`: relative path/label objects
only for files that exist.

User-derived text is HTML-escaped in `START_HERE.html`. Token values, weight
contents, credential locations, and absolute sensitive paths are excluded.
Missing optional files produce a warning or absent link, never an invented
target.

Consumers should ignore unknown fields for forward compatibility and check
`schema_version` before relying on a field. A failed sample must never be
coerced to numeric zero.
