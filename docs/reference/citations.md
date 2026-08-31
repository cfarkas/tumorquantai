# Citation guide

Cite each resource actually used; do not assign one resource's DOI to another.

## TumorQuantAI software

Use the repository `CITATION.cff` and record the exact release/tag or commit:

> Farkas, Carlos. *TumorQuantAI*. Version 1.0.0. 2026.
> https://github.com/cfarkas/tumorquantai

TumorQuantAI has no software DOI. DOIs `10.5281/zenodo.21466410`,
`10.5281/zenodo.21797920`, and `10.5281/zenodo.22177196` belong to separate
datasets, not the software.
Repository code and documentation are licensed under MIT; third-party
software, models, weights, containers, and datasets retain separate terms.

## Public lymphoma tutorial dataset

When the public MDS files or manifest are used:

> Farkas, Carlos. (2026). *TumorQuantAI lymphoma H&E whole-slide image tutorial
> dataset*. Zenodo. https://doi.org/10.5281/zenodo.21466410

The record declares CC BY 4.0, identifies TumorQuantAI `v0.4.0` as its matched
software, and contains no diagnostic annotations or pathologist ground truth.

## Public breast-IHC raw-patch dataset

When the published raw TIFF patches or release manifest are used:

> Farkas, Carlos. (2026). *TumorQuantAI breast cancer immunohistochemistry
> patch dataset for marker quantification and reproducible paper figures*
> (Version 1.0). Zenodo. https://doi.org/10.5281/zenodo.21797920

The record declares CC BY 4.0 for the dataset. Generated paper/QC figures are
local workflow outputs, not deposit contents. This DOI does not identify or
license TumorQuantAI software, model weights, dependencies, or containers.

## Public colon CD3/CD8/CK20 WSI dataset

When the published MDS files or deposited analysis/review artifacts are used:

> Farkas, Carlos. (2026). *TumorQuantAI colon cancer CD3, CD8, and CK20
> whole-slide image dataset* (Version 1.0.0). Zenodo.
> https://doi.org/10.5281/zenodo.22177196

The record exposes 57 public files: 30 sanitized MDS WSIs and 27 catalog,
checksum, result, QC, report, figure, and review artifacts. The record uses a
custom copyright statement rather than CC BY. This DOI does not identify the
software or establish clinical validation of the CK20-guided provisional
proxy.


## LazySlide and HistoPLUS

Record and cite the exact [LazySlide](https://github.com/rendeirolab/LazySlide)
version using its upstream guidance. Separately record the gated
[HistoPLUS](https://huggingface.co/Owkin-Bioptimus/histoplus) repository,
magnification, authorized weight identity, and immutable revision
`cde2eee81af9e39b03802fc33d4f284733b5ee5e`, then follow the provider's current
citation/use terms.

## Workflow and optional tools

Cite [Nextflow](https://www.nextflow.io/) and other methods when material to
the analysis. Cite InstanSeg, QuPath, spatial reports, or clinical-analysis
methods only if actually used, with their recorded versions.

Alongside citations, report container/model/software identity, input
fingerprints, source/target MPP, sampling/seed, and the completed/failed sample
audit.
