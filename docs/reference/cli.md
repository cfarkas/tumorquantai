# CLI reference

`tumorquantai` is the main command-line interface. It wraps the existing
`run.sh` and Nextflow workflow rather than reimplementing inference. The
installed command's `--help` output is authoritative.

## Synopsis

```text
tumorquantai install (--docker | --singularity | --poetry | --conda)
                      [--prefix DIR | --system]
                      [--no-nextflow-download] [--dry-run]

tumorquantai doctor [--input PATH] [--output PATH] [--work-dir PATH]
                     [--online] [--json]

tumorquantai demo [--output DIR]

tumorquantai convert INPUT --output DIR
                       [--manifest CSV] [--levels INT ...]
                       [--sample-id ID]... [--expected-count INT]
                       [--source-mpp FLOAT]
                       [--resume | --overwrite] [--dry-run]

tumorquantai inspect INPUT --output DIR
                        [--source-mpp FLOAT] [--sample-sheet CSV]
                        [--pattern GLOB]... [--include GLOB] [--exclude GLOB]

tumorquantai run INPUT --output DIR
                    [--preset smoke|fast|full] [--source-mpp FLOAT]
                    [--sample ID]
                    [--docker | --singularity | --conda]
                    [--profile auto|gpu|cpu|local | --cpu | --gpu]
                    [--seed INT] [--sample-sheet CSV]
                    [--pattern GLOB]... [--include GLOB] [--exclude GLOB]
                    [--work-dir DIR]
                    [--dry-run] [--no-resume]
                    [--local-weight FILE] [--token-file FILE]
                    [-- EXPERT_NEXTFLOW_ARGS]

tumorquantai status OUTPUT [--json]
tumorquantai report OUTPUT [--json]

tumorquantai quickstart [--output PATH]
                         [--dry-run | --download-only | --convert-only |
                          --no-inference]
                         [--docker | --singularity | --conda]
                         [--profile auto|gpu|cpu|local | --cpu | --gpu]
                         [--seed INT] [--local-weight FILE]
```

## Commands

### `install`

Installs the global `tumorquantai` command, creates an isolated launcher
environment, records the cloned repository location, and prepares one execution
method. Choose exactly one route:

- `--docker`: install the command and validate Docker.
- `--singularity` or `--apptainer`: install the command and validate Singularity/Apptainer.
- `--poetry`: create the Poetry-managed launcher; Docker is its default scientific backend.
- `--conda`: install the command and validate Miniforge/Conda.

Additional options:

- `--prefix DIR`: install under a user-selected prefix; the default is `~/.local`.
- `--system`: install under `/usr/local` and `/etc`, normally with `sudo`.
- `--no-nextflow-download`: keep an administrator-provided Nextflow installation.
- `--dry-run`: print the installation plan without changing files.

### `doctor`

Offline by default. Always checks the operating system, architecture,
Java/Nextflow, Docker CLI/daemon, NVIDIA visibility, CPU fallback, writable
caches, and configured model readiness. Without paths, its storage/cache probe
uses the current path. `--input` checks the chosen input; `--output` plus
optional `--work-dir` checks the intended output/work mount and free space.
`--online` checks pinned public release, dataset, and model metadata; it does
not prove that an account/token is authorized. `--json` omits secrets and
minimizes sensitive paths.

### `demo`

Runs bundled fixtures and a stub worker. It needs no model, GPU, Docker,
credentials, or public-data download. Every result is labelled structural and
non-biological.

### `convert`

Runs the maintained Motic MDS converter through the Python environment created by `tumorquantai install`. It verifies manifest-bound inputs, writes resumable L0/L2 TIFF files and `samples.csv`, and removes the need for a separate tutorial virtual environment.

### `inspect`

Discovers candidate primary slides/companions, duplicate risks, format/pyramid
metadata when available, source MPP or its absence, and storage estimates.
Writes a reviewable manifest without HistoPLUS inference.

### `run`

Maps `smoke` to one selected seeded 1% slide and fail-fast behavior, `fast` to
seeded 10% by default, and `full` to 100% of detected tissue tiles. Resume is
on unless `--no-resume` is used. The expanded command is printed with secrets
redacted. Default work is `OUTPUT/.tumorquantai-work`.

`--cpu` forces CPU execution and `--gpu` selects the NVIDIA execution profile;
the two flags cannot be combined. They are concise aliases for `--profile cpu`
and `--profile gpu`. The existing `--profile auto|gpu|cpu|local` option remains
backward compatible. Run `doctor` before GPU work: the CLI checks host and
container visibility, while the worker retains its established device
resolution if CUDA later becomes unavailable.

Use `--token-file` only with a token file, never a token value. `--local-weight`
references an authorized local file read-only. Arguments after `--` are an
expert Nextflow-parameter escape hatch. Existing launcher options remain
available by invoking `run.sh` directly; `run.sh --help` and direct Nextflow
remain supported.

### `status`

Reads existing metadata, per-sample summaries, and the aggregation audit.
Reports completed, failed, incomplete, excluded, and pending samples, and
prints exact local filesystem paths for the first log and resume command when
available. This human output is for the machine running the workflow; redact it
before sharing.

### `report`

Writes a self-contained `START_HERE.html` plus JSON summary. Links are relative
and included only when the target exists. User-derived text is HTML-escaped;
secret contents, credential locations, and absolute sensitive paths are
excluded. `status --json` uses the same share-oriented path redaction.

### `quickstart`

Prepares only public alias 022 from Zenodo record 21466410, converts L0/L2,
inspects MPP `0.261780`, and optionally runs seeded 1% inference when authorized
model access is already configured. It never expands to four or 21 slides.
When `--output` is omitted, the output is created beside the cloned repository
as `tumorquantai-quickstart-one-wsi`.

## Advanced compatibility

`./run.sh`, direct `nextflow run main.nf`, existing worker-script overrides,
and existing automation remain supported. See [advanced tools](../TOOLS.md).
