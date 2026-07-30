# Prepare TIFF inputs

| | |
| --- | --- |
| **For** | Users exporting scanner images to TumorQuantAI's portable layout |
| **Hands-on steps** | Export L0/L2, preserve provenance, inspect the folder |
| **Prerequisites** | Access to the scanner/export system and authoritative physical-scale metadata |
| **Download/storage** | None; exported L0 can be much larger than its source container |
| **Writes to** | A user-selected slide input directory; inspection writes a separate manifest |

## Portable layout

```text
/data/slides/
├── case_001/
│   ├── 1_L0_rgb.tif
│   └── 1_L2_rgb.tif
└── case_002/
    ├── 1_L0_rgb.tif
    └── 1_L2_rgb.tif
```

L0 is the highest-resolution primary image analyzed. L2 is a lower-resolution
companion needed by sampled modes and reports. Preserve the scanner/export
record that establishes the source L0 MPP.

TumorQuantAI discovers `*_L0_rgb.tif` and `*_L0_rgb.tiff` by default. Avoid a
broad `*.tif` pattern that can select thumbnails, companions, or outputs.

## Inspect without the model

```bash
./tumorquantai inspect /data/slides \
  --output /data/tumorquantai-inspection
```

Expected success is a reviewable manifest with one selected primary per sample,
its companion, format/pyramid information when readable, embedded or supplied
MPP, duplicate warnings, and storage estimates.

If MPP is absent or unreliable, obtain it from the imaging facility and supply
`--source-mpp` for the beginner run. Do not infer MPP from an unrelated slide or treat
target MPP as source MPP.

## Stop and clean up

Press **Ctrl+C** during inspection and rerun. Inspection does not change the
slide directory. Remove only its separate inspection output if unwanted; keep
the source exports read-only.

**Next:** [create a sample sheet](sample-sheet.md) or
[choose a preset](choose-preset.md).
