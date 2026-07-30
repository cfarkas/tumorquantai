# Exit codes

The canonical CLI uses this stable contract:

| Code | Meaning | Typical action |
| ---: | --- | --- |
| 0 | Success, including prepared quickstart when gated access is absent | Read warnings and open the report |
| 2 | CLI usage error | Correct arguments using `--help` |
| 3 | Host, storage, mount, or physical-scale preflight failure | Follow the exact next action; do not bypass |
| 4 | Missing or invalid input/output | Correct the path, manifest, or existing result |
| 5 | Public-data, checksum, or conversion integrity failure | Stop; verify/retry the bounded data stage |
| 6 | Gated-model readiness failure for direct `run` | Configure authorized token file/local weight |
| 10 | Nextflow/workflow/inference failure | Run `status`, inspect the first log, resume |

Pressing **Ctrl+C** normally produces the shell interruption status. Repeat the
same resumable command; no separate TumorQuantAI biological state is inferred
from an interruption.

For `quickstart`, absent authorized HistoPLUS access after valid
download/conversion/inspection returns 0 with a readiness report. It is not
data corruption. Direct `run` requires model readiness and returns 6 when it is
absent.

Direct `run.sh`, Nextflow, and worker scripts may expose their own detailed exit
codes. The canonical CLI maps workflow failure to 10 without converting a
failed sample into a biological zero.
