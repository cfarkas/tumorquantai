# Troubleshooting

| | |
| --- | --- |
| **For** | Users diagnosing setup, input, storage, conversion, model, or sample failures |
| **Hands-on steps** | Run redacted checks, choose the matching symptom, correct one cause, resume |
| **Prerequisites** | The original command and output/work paths |
| **Download/storage** | Offline checks do not download; verify free space before resuming |
| **Writes to** | Optional redacted `doctor.json`/`status.json` in the current directory |

Start with:

```bash
tumorquantai doctor --output /path/to/results --json > doctor.json
tumorquantai status /path/to/results --json > status.json
```

Review both files before sharing. Never attach tokens, weight files, raw WSI,
PHI, patient-level tables, private manifests, or unredacted logs/paths.

## Docker permission denied

**Typical message:** permission denied while connecting to the Docker socket.

```bash
docker version
docker info
```

Use the Docker access method approved by your system administrator. Do not
change socket permissions broadly or run unrelated server maintenance. Log out
and back in if an administrator has just changed group membership. Rerun
`doctor`; expected Docker CLI and daemon checks are `PASS`.

## Docker daemon unavailable

**Typical message:** cannot connect to the Docker daemon.

Check `docker info`. The daemon may be stopped, the context may be wrong, or the
host may not provide Docker. Ask the host administrator to restore the approved
service or use the `local` profile only in a deliberately prepared environment.
Do not alter Docker's data root, volumes, mounts, or system configuration.

## NVIDIA GPU not visible

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

The second command may download a public test image. Use it only when approved.
If the host sees the GPU but Docker does not, the NVIDIA Container Toolkit or
runtime configuration needs administrator attention. `--cpu` (equivalent to
`--profile cpu`) is a supported fallback but can be much slower; doctor must
state that path explicitly.

## HistoPLUS access denied

Access to the Hugging Face repository and possession of a read token are
separate. Confirm the account has been approved, then check the token-file
location and private permissions:

```bash
stat -c '%a %n' "$HOME/.config/tumorquantai/hf_token"
tumorquantai doctor --online
```

Expected mode is `600` and directory mode `700`. Do not print the file. The
legacy `~/.config/lazyslide-histoplus/hf_token` remains supported with a
warning. An authorized local weight can be supplied with `--local-weight`.
Missing gated access after valid quickstart preparation is readiness, not
public-data corruption.

## MPP missing or inconsistent

MPP is micrometres per pixel. Source MPP describes the input L0 image; target
MPP describes model tiles. If inspection cannot establish source scale:

1. consult scanner/export provenance;
2. check a trusted export sidecar;
3. ask the imaging facility; then
4. rerun with `--source-mpp VERIFIED_VALUE`.

Do not copy the public tutorial value or another slide's MPP. TumorQuantAI
fails closed because guessing changes physical scale.

## No slides discovered

```bash
tumorquantai inspect /data/slides \
  --output /data/inspection \
  --pattern '*_L0_rgb.tif'
```

Check that `/data/slides` exists, primary files match the intended pattern, and
a sample sheet path is correct. Default discovery selects
`*_L0_rgb.tif`/`*.tiff` only. Do not broaden to `*.tif` until you have ruled out
companions, thumbnails, and generated outputs.

Expected inspection contains `inspection_manifest.csv`,
`inspection_manifest.tsv`, `inspection.json`, and `INSPECTION.html` with one
row per intended primary.

## MDS conversion interrupted

Repeat the same command with `--resume`:

```bash
python bin/mds_to_tiff.py \
  --input /mounted/data/raw \
  --manifest examples/lymphoma/tumorquantai_lymphoma_mds_manifest.csv \
  --output-dir /mounted/data/slides \
  --levels 0 2 \
  --sample-id TumorQuantAI_LymphomaWSI_022 \
  --expected-count 1 \
  --resume
```

The converter reuses only state matching the source hash, settings, geometry,
and output SHA-256. Keep `mds_conversion_manifest.json`. A checksum mismatch is
an integrity failure; do not bypass or label it a model failure.

## Out of disk space

Stop the run, then check the exact paths:

```bash
findmnt -T /path/to/results
df -hT /path/to/results
findmnt -T /path/to/work
df -hT /path/to/work
```

Do not move active work, prune Docker globally, or delete caches unrelated to
this run. Free or allocate space through approved storage operations, preserving
work for resume. Budget source download, conversion, Nextflow work, results,
and model cache separately.

## Nextflow resume did not reuse a task

Resume is enabled by default. Cache reuse should be invalidated when relevant
input fingerprints, L2, MPP, sampling, seed, model/container identity, or
processing settings change. Compare the expanded command and provenance.

```bash
tumorquantai status /path/to/results
```

If settings are unchanged, inspect the first log and Nextflow trace reported by
status. Do not use `--no-resume` as a routine fix; it intentionally disables
reuse.

## Sample failed or is missing from matrices

Open:

```text
aggregated_celltypes/sample_aggregation_audit.csv
<sample>/slide.log
workflow_metadata/nextflow_trace_<run>.tsv
```

A numeric matrix column exists only for a validly completed sample. Failed,
incomplete, excluded, and pending samples remain in the audit/status and must
not become zero. Correct the first cause and resume. Requiring every expected
sample may be appropriate for a tutorial checkpoint; do not silently analyze a
partial cohort.

## If you still need help

Open a GitHub bug report with:

- repository tag/commit;
- redacted command;
- expected and observed behavior;
- reviewed `doctor.json` and `status.json`; and
- only the smallest redacted log excerpt needed.

Use GitHub private security reporting for a security issue. Never open a public
issue containing a credential, PHI, private WSI, patient-level table, or model
weight.

## Stop, resume, and clean up

Press **Ctrl+C** to stop. Keep the original work directory, correct the cause,
and repeat the exact command. Remove only temporary redacted JSON you created
for troubleshooting and only after confirming it is not needed for an issue.

**Next:** return to [resume an interrupted run](../how-to/resume.md).
