# Provenance fields

`<sample>/summary/summary.json` contains the completion and scientific identity:

- slide ID, source path identity/fingerprint, dimensions;
- source `slide_mpp` and target `mpp`/`target_mpp`;
- scientific processing signature and schema;
- paper-figure layout version, when the current rendering contract is recorded;
- HistoPLUS weight identity;
- device;
- detected-cell/class totals and explicit `zero_detections`;
- deterministic tile/patch sampling summary;
- pyramidal conversion identity; and
- relative output paths.

`<sample>/summary/run_metadata.json` records settings such as:

- source-MPP origin (override or embedded);
- tile size/overlap/background fraction;
- percentage and random seed;
- model repository, immutable revision, magnification, and weight filename;
- selected device/batches/workers;
- overlay palette/style;
- paper-figure layout version and portable relative figure/legend paths;
- conversion settings; and
- whether a token was supplied as a Boolean, never its contents.

The paper-figure layout version is deliberately excluded from the scientific
worker processing signature. This separation means that direct reuse of the
same persistent worker output preserves the earlier completion contract for a
legacy summary without a layout version. For outputs whose completion summary
records the current layout version, external
`paper_figures/celltypes_paper_figure_legend.txt` is part of the validated
contract; missing or empty text prevents completion/resume reuse.

Worker-signature reuse is not the same as top-level workflow-cache reuse.
`PROCESS_SLIDE` stages the worker code, and Nextflow also keys that code and its
configuration. A software upgrade may therefore invalidate the task and re-enter
HistoPLUS inference even though the scientific worker signature is unchanged.
Before a top-level resume, inspect the `--resume --dry-run` plan for Nextflow
`-resume` and the original work directory. Preserve the exact software revision
and work cache, or select `--cpu` when reuse is uncertain. To obtain redesigned
artwork for a legacy result, use a new output directory or choose a deliberate
rerun.

The legend records only public sample identity and portable scientific
provenance; it must not contain private cohort identifiers or absolute source
paths.

Workflow metadata adds:

- Git/software version or commit when available;
- immutable container digest;
- Nextflow report, trace, and timeline;
- discovery manifest/fingerprints; and
- authoritative aggregation roster/audit.

The public one-slide quickstart additionally records Zenodo record 21466410,
dataset DOI `10.5281/zenodo.21466410`, dataset-matched release `v0.4.0`,
MDS/TIFF checksums, source MPP `0.261780`, conversion levels L0/L2, command
provenance, and the sampling seed.

Secrets and model weights are external resources. Token contents and weight
files are never copied into result provenance.

### Weight-identity privacy migration

Current outputs retain the authorized weight filename, byte size, and SHA-256
needed for identity checks. They intentionally omit its absolute path,
device/inode numbers, and filesystem timestamps. Older outputs may contain
those location-specific fields; downstream readers must accept both forms and
must not require or republish the removed fields.
