# Export to QuPath

| | |
| --- | --- |
| **For** | Experienced users who want generated cell annotations in QuPath |
| **Hands-on steps** | Enable export for a separate smoke run, verify integrity, import and review |
| **Prerequisites** | Completed inspection, authorized inference, QuPath installed separately |
| **Download/storage** | JSON annotations can be large; budget result/work space before running |
| **Writes to** | `<sample>/cell_types/cell_types_qupath.json` plus integrity metadata |

QuPath export is optional because annotation JSON can be large. Test it on one
smoke sample in a separate result root:

```bash
./run.sh \
  --input-dir /data/slides \
  --output-dir /data/results-qupath-smoke \
  --work-dir /data/results-qupath-smoke/.tumorquantai-work \
  --fast \
  --percent-slide 1 \
  --slide-mpp "$SOURCE_MPP" \
  --fail-fast \
  --export-qupath \
  --profile auto
```

QuPath export is an advanced `run.sh` option; the main interface
and direct Nextflow path remain compatible. Expected completion includes
`<sample>/cell_types/cell_types_qupath.json`; requested large exports are
validated before `summary.json` is published as the completion marker.

Open the matching source image in QuPath and import the JSON according to the
QuPath version in use. Verify coordinate alignment, physical scale, class
mapping, and a range of tissue regions. Do not treat an import without visual
review as successful.

## Stop, resume, and clean up

Press **Ctrl+C** and repeat the same command with the same output/work paths.
Remove only the dedicated QuPath smoke pair if discarded; do not delete the
source slide or reuse the root for a non-QuPath run.

**Next:** consult the [output reference](../reference/outputs.md).
