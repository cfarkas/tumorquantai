# Keep work and output on mounted storage

| | |
| --- | --- |
| **For** | Users choosing safe locations before download, conversion, or inference |
| **Hands-on steps** | Resolve mount, check filesystem/capacity, test write, run doctor, select distinct paths |
| **Prerequisites** | A user-authorized mounted storage location |
| **Download/storage** | Estimates depend on the slide; budget download, conversion, work, results, and model cache separately |
| **Writes to** | A tiny writable probe and the explicit paths you approve |

## Verify the target

Create only the intended task root, then inspect it:

```bash
export TQA_STORAGE=/mounted/storage/tumorquantai-project
mkdir -p "$TQA_STORAGE"

findmnt -T "$TQA_STORAGE"
df -hT "$TQA_STORAGE"
test -w "$TQA_STORAGE"

./tumorquantai doctor \
  --output "$TQA_STORAGE/results-smoke" \
  --work-dir "$TQA_STORAGE/work-smoke"
```

Confirm the resolved filesystem is the intended mounted volume. Do not use the
repository, `/`, an unverified home filesystem, or a hidden default work
directory for large WSI data.

## Budget categories separately

| Category | Includes |
| --- | --- |
| Download | Original MDS/WSI and checksum state |
| Conversion | L0/L2 or pyramidal TIFFs and conversion manifest |
| Work | Nextflow task staging, caches, retry/resume material |
| Results | Coordinates, images, summaries, matrices, workflow metadata |
| Model cache | Authorized HistoPLUS artifact outside outputs |

Use distinct paths:

```text
/mounted/storage/tumorquantai-project/
├── input/             # preferably read-only during inference
├── results-smoke/
├── work-smoke/
├── results-fast/
└── work-fast/
```

When `--work-dir` is omitted, the main CLI chooses an output-associated
location on the same selected filesystem. Fast and full must have distinct
result/work pairs.

## Stop, move, and clean safely

Press **Ctrl+C** before any move. Do not move an active Nextflow work directory.
After stopping, prefer copying and verifying results before changing their
location; `START_HERE.html` uses relative links. Keep work while resume matters.
To clean, print and verify the exact task subdirectory and its mount, then
remove only that subdirectory—never a workspace root or mount root.

**Next:** [choose a preset](choose-preset.md).
