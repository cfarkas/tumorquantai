# Configure HistoPLUS access

HistoPLUS is hosted as a gated model on Hugging Face. TumorQuantAI can prepare and inspect public slides without it, but inference requires approved access.

## 1. Request access

Open the [HistoPLUS model page](https://huggingface.co/Owkin-Bioptimus/histoplus), sign in, and request access. Creating a token does not approve the model request; both steps are required.

## 2. Create a read token

After the model request is approved, create a Hugging Face access token with **Read** permission.

## 3. Save the token privately

```bash
# Create the private TumorQuantAI configuration directory.
install -d -m 700 "$HOME/.config/tumorquantai"

# Paste the Hugging Face read token without displaying it.
read -rsp "Hugging Face read token: " HF_READ_TOKEN
printf '\n'
printf '%s' "$HF_READ_TOKEN" > "$HOME/.config/tumorquantai/hf_token"
unset HF_READ_TOKEN
chmod 600 "$HOME/.config/tumorquantai/hf_token"
```

TumorQuantAI automatically reads `$HOME/.config/tumorquantai/hf_token`. Do not put the token value after `--token-file`, in an environment file, in a Git command, or in an issue.

## 4. Check readiness

```bash
# Check the installed runtime, public metadata, and local credential file.
tumorquantai doctor --online
```

Doctor confirms that the token file exists and is private; the first inference confirms that the approved account can download the pinned HistoPLUS artifact.

## Authorized local weight

An organization-provided authorized weight can be selected instead of a token:

```bash
# Run with an authorized local HistoPLUS weight.
tumorquantai run /path/to/slides \
  --output /path/to/results \
  --local-weight /approved/model-store/histoplus_cellvit_segmentor_20x.pt \
  --preset smoke \
  --source-mpp 0.261780 \
  --cpu
```

The weight is hashed for provenance and read from its original location. Do not copy it into the repository or result directory.

## Replace a compromised token

Revoke it in Hugging Face, repeat the private-file commands with a new read token, and rerun `tumorquantai doctor --online`.

**Next:** run the [public one-slide QuickStart](../quick_start.md).
