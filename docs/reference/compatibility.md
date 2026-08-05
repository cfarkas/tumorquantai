# Version 1 compatibility policy

TumorQuantAI follows semantic versioning for its supported public workflow
interfaces. Version 1.0.0 establishes the first stable contract; this policy is
about interface compatibility, not biological performance or clinical validity.

## Supported v1 interfaces

The v1 compatibility contract covers:

- documented `tumorquantai` commands, options, exit behavior, and preset names;
- documented Nextflow parameters in `nextflow_schema.json`;
- required output paths and table columns documented in the output reference;
- recorded completion, failure, physical-scale, sampling, model, and runtime
  provenance; and
- the explicit distinction between failed/incomplete samples and completed
  biological-zero samples.

Within 1.x, new optional commands, parameters, files, columns, or metadata fields
may be added. Existing required fields may receive better validation or corrected
values when the earlier behavior was erroneous. A supported interface is not
removed or incompatibly renamed without a documented deprecation path; an
unavoidable incompatible contract change requires a new major version.

## Not public interfaces

Internal Python functions, implementation scripts under `bin/` or `scripts/`,
Nextflow process internals, cache/work-directory layout, log wording, and test
fixtures are not stable public APIs unless another reference page explicitly
says otherwise. Optional upstream tools, gated models, and separately published
runtime images retain their own versions and terms.

Security, privacy, integrity, and scientific-correctness fixes can supersede
compatibility when preserving old behavior would be unsafe or misleading. Such
changes must be called out in the changelog and release notes with a migration
or validation instruction when one is needed.
