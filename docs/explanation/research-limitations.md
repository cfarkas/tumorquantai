# Research limitations

TumorQuantAI is research software, not a diagnostic device. Its outputs must
not be used for patient-care decisions.

Key limitations:

- HistoPLUS classes are model predictions, not diagnoses or pathologist ground
  truth.
- Results depend on slide quality, staining, export fidelity, tissue
  detection, physical scale, sampling, model domain, and QC choices.
- Sampled-tile counts are not whole-slide counts or validated extrapolations.
- Fractions change the denominator but do not remove selection or model bias.
- Visual overlays help identify technical problems but do not measure accuracy.
- The public lymphoma tutorial collection has no diagnostic annotations,
  outcome labels, or pathologist ground truth and is not a clinical benchmark.
- Technical workflow validation does not establish clinical validity,
  generalizability, prognostic performance, or treatment utility.

TumorQuantAI preserves provenance and makes failures explicit so that research
teams can audit what ran. Those controls are necessary for reproducibility but
are not substitutes for an appropriate study design, independent validation,
domain-expert review, data governance, or regulatory assessment.

Model and dataset access/licensing are separate from repository source
visibility. TumorQuantAI repository code and documentation use the MIT License;
third-party software, models, weights, containers, and datasets retain separate
licenses or terms.

**Next:** review the [provenance reference](../reference/provenance.md).
