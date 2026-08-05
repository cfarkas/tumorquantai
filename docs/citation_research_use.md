# Citation and research use

TumorQuantAI combines several distinct resources. Cite each resource that was actually used rather than treating the public dataset DOI as a software citation.

## TumorQuantAI software

Use the repository citation metadata in [`CITATION.cff`](https://github.com/cfarkas/tumorquantai/blob/main/CITATION.cff). Record the exact TumorQuantAI release or commit used for the analysis.

## Public lymphoma WSI dataset

The public tutorial dataset is:

- Zenodo record: `21466410`
- DOI: [`10.5281/zenodo.21466410`](https://doi.org/10.5281/zenodo.21466410)

Cite the dataset when its MDS slides, manifest, checksums, or derived tutorial TIFFs are used.

## Public breast-IHC raw patch dataset

The public raw-only breast-IHC example dataset is:

- Zenodo record: `21797920`
- DOI: [`10.5281/zenodo.21797920`](https://doi.org/10.5281/zenodo.21797920)
- License: CC BY 4.0
- Contents: 55 files comprising 51 case archives with 1,901 TIFF patches plus
  four auxiliary files: one manifest bundle, one packaging report, and two
  checksum rosters (74,958,557,152 bytes total)

Cite this dataset when its TIFF patches, manifest, or checksums are used.
Generated paper and QC figures are local TumorQuantAI outputs and are not part
of the Zenodo deposit. This DOI identifies the breast-IHC dataset; it is not a
software DOI and does not replace the separate citation for TumorQuantAI.

## HistoPLUS and LazySlide

Cite the HistoPLUS model and LazySlide software according to their official documentation and terms. Record the pinned HistoPLUS revision and weight identity from each TumorQuantAI summary.

See [`CITATIONS.md`](https://github.com/cfarkas/tumorquantai/blob/main/CITATIONS.md) for the maintained non-conflated citation guide.

## Research-use limitation

TumorQuantAI is not a standalone diagnostic system or medical device. The workflow does not establish:

- diagnosis;
- treatment eligibility;
- prognosis;
- clinical sensitivity or specificity;
- pathologist ground truth;
- generalization across scanners, stains, tissues, or institutions.

HistoPLUS predictions require expert visual review, slide-quality review, physical-scale validation, and independent biological or pathological validation.

## Sampled analyses

The `smoke` and `fast` presets process sampled tissue tiles. Their counts are not validated whole-slide counts and must not be rescaled by `100 / percent_slide`.

Report:

- sampling percentage;
- random seed;
- source and target MPP;
- selected sample set;
- software commit;
- model revision and weight identity;
- container identity;
- failed and excluded samples;
- overlay-review procedure.

## Failed samples

A failed, incomplete, or excluded slide is not a biological zero. Report it separately and retain `sample_aggregation_audit.csv` with any cohort matrix.

## Privacy

Do not commit or publish:

- raw private WSIs;
- protected health information;
- patient-identifying sample names;
- model tokens or weights;
- private clinical linkage tables;
- unredacted logs containing sensitive paths.

Use controlled research sample IDs and redact diagnostic reports before opening a public issue.

## License status

TumorQuantAI repository code and documentation are licensed under MIT. The
Zenodo datasets, dependencies, container contents, and gated HistoPLUS model or
weights have separate licenses or terms.
