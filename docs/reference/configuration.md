# Configuration and environment variables

Beginner CLI arguments take precedence over ordinary defaults. Credential
resolution deliberately prefers `TUMORQUANTAI_HF_TOKEN_FILE` when it is set.
Use files and paths for credentials; never place token values in command
arguments.

## Credential resolution

| Setting | Meaning |
| --- | --- |
| `TUMORQUANTAI_HF_TOKEN_FILE` | Preferred explicit Hugging Face token-file path |
| `--token-file FILE` | Explicit run token-file path, after the environment preference |
| `~/.config/tumorquantai/hf_token` | Preferred default token file |
| `HF_TOKEN_FILE` | Legacy automation fallback after the preferred default file; migrate to `TUMORQUANTAI_HF_TOKEN_FILE` |
| `~/.config/lazyslide-histoplus/hf_token` | Legacy fallback; supported with deprecation warning |
| `HISTOPLUS_WEIGHT_FILE` | Authorized local HistoPLUS weight path |
| `--local-weight FILE` | Per-run authorized local-weight override |

Token files must be private regular files. Contents and credential locations
are not printed, placed in result provenance, or recorded in reports. Local
weights are hashed for identity but their filesystem locations and contents are
not copied into result outputs.
Selecting a local weight also removes unrelated token variables from the
launched Nextflow/worker environment.
An already configured `HF_TOKEN` remains supported for legacy automation but is
not the recommended beginner setup.

## Cache, work, and expert compatibility variables

| Setting | Scope and safe use |
| --- | --- |
| `TUMORQUANTAI_CACHE` | Writable cache checked by `doctor`; place it on an approved filesystem |
| `HF_HOME` | Direct-`run.sh` Hugging Face download/cache default |
| `HISTOPLUS_CACHE` | Direct-`run.sh` resolved HistoPLUS cache default |
| `NXF_WORK` | Legacy/direct-`run.sh` work default |
| `CONTAINER_IMAGE` | Direct-`run.sh` expert override for the profile container |
| `HISTOPLUS_REVISION` | Direct-`run.sh` expert override for the model revision |

Put caches that may grow on a verified mounted filesystem, outside the
repository and result directory. The canonical CLI explicitly passes
`OUTPUT/.tumorquantai-work` (or `--work-dir`), a sibling output-associated
model cache, and the pinned container/model identities. Those safe beginner
choices take precedence over the direct-`run.sh` environment defaults above.
A deliberate expert path or identity change requires review, a separate output
root, and complete provenance; direct `run.sh` remains the explicit expert
route.

## Execution

| CLI | Legacy mapping |
| --- | --- |
| `--source-mpp FLOAT` | `run.sh --slide-mpp FLOAT` |
| `--preset smoke` | `--fast --percent-slide 1 --fail-fast` plus one sample |
| `--preset fast` | `--fast` (10% default) |
| `--preset full` | `--full` |
| `--seed INT` | `--seed INT` |
| `--profile auto|gpu|cpu|local` | same `run.sh` profile |
| `--work-dir DIR` | Nextflow work directory |

The target model-tile MPP remains 0.5 unless an expert changes the existing
engine setting. The pinned defaults are:

- HistoPLUS repository `Owkin-Bioptimus/histoplus`;
- immutable revision
  `cde2eee81af9e39b03802fc33d4f284733b5ee5e`; and
- immutable CPU/GPU container digests from `nextflow.config`.

Changing pinned identities is an expert, reviewed reproducibility decision.

## Direct workflow

`nextflow_schema.json` and `nextflow.config` define the direct workflow
parameters. `run.sh --help` documents launcher flags. Protected model revision,
weight identity, source MPP, and shared-memory parameters must be passed through
the launcher rather than unreviewed Nextflow passthrough.
