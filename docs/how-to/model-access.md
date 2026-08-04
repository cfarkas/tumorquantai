# Configure authorized HistoPLUS access

| | |
| --- | --- |
| **For** | Users already authorized to use the gated HistoPLUS model |
| **Hands-on steps** | Request access, store a read token file or point to an authorized local weight, check readiness |
| **Prerequisites** | An approved Hugging Face account or organization-approved local weight |
| **Download/storage** | Model download/cache size depends on the authorized artifact; keep the cache on an approved filesystem |
| **Writes to** | A mode-0600 token file outside the repository or a read-only weight reference |

Request access on the
[HistoPLUS model page](https://huggingface.co/Owkin-Bioptimus/histoplus).
Creating a Hugging Face token does not grant model access. Never send a token
to TumorQuantAI maintainers.

## Preferred token-file location

Store a read-only token without placing its value on the command line:

```bash
install -d -m 700 "$HOME/.config/tumorquantai"
umask 077
read -rsp "Hugging Face read token: " TQA_TOKEN
printf '%s' "$TQA_TOKEN" > "$HOME/.config/tumorquantai/hf_token"
unset TQA_TOKEN
printf '\n'
chmod 600 "$HOME/.config/tumorquantai/hf_token"

export TUMORQUANTAI_HF_TOKEN_FILE="$HOME/.config/tumorquantai/hf_token"
```

Resolution order is:

1. `TUMORQUANTAI_HF_TOKEN_FILE` when set;
2. an explicit `run --token-file FILE` path;
3. `~/.config/tumorquantai/hf_token`;
4. legacy `HF_TOKEN_FILE` automation when set, with a deprecation warning;
5. legacy `~/.config/lazyslide-histoplus/hf_token` with a deprecation warning.

The legacy path remains supported. Move it only when doing so will not disrupt
existing automation. Token contents are never copied to outputs or printed.
An existing `HF_TOKEN` environment value remains an automation compatibility
fallback, but a private token file is preferred and documented for new users.

## Authorized local weight

If your organization provides the matching authorized HistoPLUS weight:

```bash
export HISTOPLUS_WEIGHT_FILE=/approved/model-store/histoplus_cellvit_segmentor_20x.pt
test -r "$HISTOPLUS_WEIGHT_FILE"
```

The launcher hashes the file for provenance and mounts it read-only. Do not
copy it into the repository or result directory.
When a local weight is selected, TumorQuantAI removes unrelated token
variables before launching Nextflow or a worker.

## Check readiness

```bash
tumorquantai doctor --online
```

The online check validates pinned public model metadata only. The local
credential item confirms that a private token file or authorized local weight
is configured and readable; it does not prove account authorization. Actual
gated access is established only when inference resolves the pinned artifact.
Doctor never prints the token. Missing gated access is a readiness warning for
download/inspection-only quickstart stages, but blocks inference.

## Stop and revoke

Press **Ctrl+C** to stop a check. Revoke a compromised token through Hugging
Face, then replace only the mode-0600 file. Never attach it to an issue. Cache
cleanup is optional and must target only the authorized model cache, not an
entire home directory.

**Next:** run the [public one-slide quickstart](../start-here/public-slide.md).
