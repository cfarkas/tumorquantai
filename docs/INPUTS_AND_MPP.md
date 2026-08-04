# Inputs, L0/L2, and MPP

This material is now split into:

- [Prepare TIFF inputs](how-to/prepare-tiff.md)
- [Create a sample sheet](how-to/sample-sheet.md)
- [WSI, pyramid levels, L0 and L2](explanation/wsi-pyramid.md)
- [Source MPP versus target MPP](explanation/mpp.md)
- [Input manifest schema](reference/input-manifest.md)

Inspect without inference:

```bash
tumorquantai inspect /data/slides \
  --output /data/tumorquantai-inspection
```

TumorQuantAI fails closed when a workflow requires physical scale and source
MPP cannot be established reliably. Do not guess or substitute target MPP.
