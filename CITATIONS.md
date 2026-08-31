# Citation guide

Cite the software, dataset, model, and libraries as separate resources. A DOI
for one resource must not be assigned to another.

## TumorQuantAI software

Use the repository's `CITATION.cff` for citation-manager metadata and record the
exact release/tag or Git commit used:

> Farkas, Carlos. *TumorQuantAI*. Version 1.0.0. 2026.
> https://github.com/cfarkas/tumorquantai

TumorQuantAI does not currently have a software DOI. Do not use the tutorial
dataset DOI as a software DOI.

Repository code and documentation are licensed under MIT. Third-party
software, models, weights, containers, and datasets retain separate terms.

## Public lymphoma tutorial dataset

If the Zenodo MDS files or their manifest are used, cite:

> Farkas, Carlos. (2026). *TumorQuantAI lymphoma H&E whole-slide image
> tutorial dataset*. Zenodo. https://doi.org/10.5281/zenodo.21466410

Also record that the dataset identifies TumorQuantAI `v0.4.0` as its matched
software release. The record contains no diagnostic annotations or pathologist
ground truth and declares CC BY 4.0 for the dataset.

## Public breast-IHC raw-patch dataset

If the published raw TIFF patches or release manifest are used, cite:

> Farkas, Carlos. (2026). *TumorQuantAI breast cancer immunohistochemistry
> patch dataset for marker quantification and reproducible paper figures*
> (Version 1.0). Zenodo. https://doi.org/10.5281/zenodo.21797920

The record declares CC BY 4.0 for the dataset. It contains raw-only example
material; generated TumorQuantAI paper/QC figures are local outputs and are not
part of the deposit. The dataset DOI does not identify or license TumorQuantAI
software, HistoPLUS weights, dependencies, or containers.

## Public colon CD3/CD8/CK20 WSI dataset

If the published MDS files, catalog, checksums, frozen analysis tables, or
review figures are used, cite:

> Farkas, Carlos. (2026). *TumorQuantAI colon cancer CD3, CD8, and CK20
> whole-slide image dataset* (Version 1.0.0). Zenodo.
> https://doi.org/10.5281/zenodo.22177196

The public record contains 30 sanitized MDS WSIs plus frozen CK20-guided proxy
outputs and review artifacts. Its custom rights statement is Copyright (C)
2026 The Authors; do not describe it as CC BY unless the record is changed to
declare that license. The DOI identifies the colon-IHC dataset, not the
TumorQuantAI software and not a clinically validated consensus Immunoscore.


## LazySlide

TumorQuantAI uses [LazySlide](https://github.com/rendeirolab/LazySlide) as part
of its WSI analysis engine. Cite the exact installed version and follow the
upstream project's current citation guidance for the version used.

## HistoPLUS

TumorQuantAI uses the gated
[HistoPLUS model](https://huggingface.co/Owkin-Bioptimus/histoplus). Record the
model repository, magnification, filename/content identity, and immutable
revision
`cde2eee81af9e39b03802fc33d4f284733b5ee5e`, then follow the model provider's
current citation and use terms. Model access/terms are separate from this
repository and the public dataset.

## Workflow and optional methods

Analyses also use [Nextflow](https://www.nextflow.io/) for orchestration and
the exact container/dependencies recorded by run provenance. Cite Nextflow and
other methods according to their upstream guidance when material to the work.

The optional InstanSeg cell stage, QuPath export/review, spatial report, and
clinical analysis should be cited only when actually used; record versions and
follow each upstream method's citation instructions.

## Minimum reproducibility statement

Alongside citations, report:

- TumorQuantAI tag/commit and container digest;
- HistoPLUS immutable revision and authorized weight identity;
- source slide fingerprints;
- source MPP and target MPP;
- preset, processed percentage, and random seed;
- completed/failed/incomplete sample audit; and
- whether counts cover sampled or all detected tissue tiles.
