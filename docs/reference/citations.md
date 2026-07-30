# Citation guide

Cite each resource actually used; do not assign one resource's DOI to another.

## TumorQuantAI software

Use the repository `CITATION.cff` and record the exact release/tag or commit:

> Farkas, Carlos. *TumorQuantAI*. Version 0.4.0. 2026.
> https://github.com/cfarkas/tumorquantai

TumorQuantAI has no software DOI. DOI `10.5281/zenodo.21466410` belongs to the
dataset, not the software.

## Public tutorial dataset

When the public MDS files or manifest are used:

> Farkas, Carlos. (2026). *TumorQuantAI lymphoma H&E whole-slide image tutorial
> dataset*. Zenodo. https://doi.org/10.5281/zenodo.21466410

The record declares CC BY 4.0, identifies TumorQuantAI `v0.4.0` as its matched
software, and contains no diagnostic annotations or pathologist ground truth.

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
