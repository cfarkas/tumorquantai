# Software license decision

## Owner decision

On 2026-08-05, the owner selected the MIT License for TumorQuantAI release
`v1.0.0`. The canonical license text is tracked in the repository root as
`LICENSE`, with copyright notice:

> Copyright (c) 2026 Carlos Farkas

Repository and citation/package metadata identify the license with SPDX
identifier `MIT`.

## Scope and boundaries

The repository MIT License covers TumorQuantAI code and associated
documentation distributed in this release to the extent held and licensable by
the copyright holder. It does not relicense or override terms for:

1. third-party dependencies or files incorporated from other projects;
2. CPU/GPU runtime image contents supplied under their component licenses;
3. LazySlide, HistoPLUS code, gated model artifacts, or model weights;
4. the lymphoma and breast-IHC Zenodo datasets, which separately declare
   CC BY 4.0;
5. private WSI, clinical data, institutional materials, or user-provided data;
6. names, logos, trademarks, patents, or rights not granted by the MIT text.

Model access, data governance, consent, privacy, and institutional data-use
requirements remain independent of the repository software license. Neither
dataset DOI is a TumorQuantAI software DOI.

## Maintainer requirements

- Preserve the exact `LICENSE` text and copyright notice in distributions.
- Keep `MIT` aligned in `CITATION.cff`, package metadata, README, release notes,
  and repository hosting metadata.
- Do not describe third-party software, containers, models, weights, or
  datasets as MIT-licensed by TumorQuantAI unless their owners separately do so.
- Inventory dependency and container licenses before redistributing a new
  bundled artifact.
- Record any future license or copyright-scope change as a new explicit owner
  decision with an effective release.
