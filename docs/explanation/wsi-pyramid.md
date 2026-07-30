# WSI, pyramid levels, L0 and L2

A **whole-slide image (WSI)** is a high-resolution digital image of a glass
slide. A single full-resolution plane can be extremely large, so slide formats
often store an image pyramid: the same field of view at progressively lower
resolutions.

- **L0** is TumorQuantAI's highest-resolution primary exported image. It is the
  image analyzed.
- **L2** is a lower-resolution companion used by sampled-patch and overview
  artifacts. It is not a second biological sample.
- A **tile** is a rectangular region read from the WSI for tissue detection or
  model processing.

The portable layout names these files `1_L0_rgb.tif` and `1_L2_rgb.tif` under
one sample directory. Sampled modes require the matching L2 companion. Full
mode processes all detected tissue tiles from L0, not every background pixel.

The number in “L2” is an export-level label, not MPP. Physical scale must still
come from the scanner/export record, a trusted sidecar, or reliable embedded
metadata.

**Next:** understand [source and target MPP](mpp.md).
