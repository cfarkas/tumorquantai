# Resume an interrupted run

| | |
| --- | --- |
| **For** | Users whose run stopped or has failed/incomplete samples |
| **Hands-on steps** | Read status, inspect first log, correct cause, repeat exact command |
| **Prerequisites** | Original output and work directories; same intended inputs/settings |
| **Download/storage** | Resume can continue container/model/download work; check free space first |
| **Writes to** | Existing result/work paths, with valid cached tasks reused |

## Ask TumorQuantAI what happened

```bash
./tumorquantai status /data/results-fast
./tumorquantai status /data/results-fast --json > status.json
```

Status parses workflow metadata, per-sample summaries, and
`aggregated_celltypes/sample_aggregation_audit.csv`. It reports completed,
failed, incomplete, excluded, and pending samples, then prints:

- the first relevant log to inspect; and
- the exact resume command when recorded.

Human status is a local operational view and may contain exact filesystem
paths. `status --json` and generated reports redact sensitive paths for sharing;
credential locations are never recorded. Review any human terminal output
before posting it.

A failed sample is not a biological zero. It remains out of the numeric
matrices and visible in the audit.

## Correct and resume

Resolve the reported environmental/input problem, then repeat the same command.
Resume is enabled by default:

```bash
./tumorquantai run /data/slides \
  --output /data/results-fast \
  --preset fast \
  --source-mpp "$SOURCE_MPP"
```

Changing the source fingerprint, L2 companion, source MPP, sampling, seed,
container/model identity, or relevant settings invalidates affected cached
tasks. That is a safeguard, not a resume failure.

Use `--no-resume` only for an intentional fresh execution. Keep the new run in
a separate output/work pair when scientific settings change.

## Stop and clean up

Press **Ctrl+C** to stop safely. Do not move an active work directory or run
`nextflow clean -f` while recovery is needed. After published outputs,
provenance, and audit are verified and backed up, remove only the exact work
directory associated with that run.

**Next:** if resume still fails, open [Troubleshooting](../troubleshooting/index.md).
