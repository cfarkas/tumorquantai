# Provenance fields

`<sample>/summary/summary.json` contains the completion and scientific identity:

- slide ID, source path identity/fingerprint, dimensions;
- source `slide_mpp` and target `mpp`/`target_mpp`;
- processing signature and schema;
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
- conversion settings; and
- whether a token was supplied as a Boolean, never its contents.

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
