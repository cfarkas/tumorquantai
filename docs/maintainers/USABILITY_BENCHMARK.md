# GitHub usability benchmark

**Snapshot:** 2026-07-30T13:02:13Z
**Purpose:** identify transferable onboarding patterns for TumorQuantAI; this is not a project ranking.

## Methodology

The benchmark uses the GitHub REST API through the authenticated `gh api` CLI. It covers the 14 requested repositories plus two active computational-pathology toolkits selected from six topic searches. For each default branch, the collector records repository metadata, a recursive path inventory, release metadata, and whether the first approximately 100 README source lines contain an install or quickstart command. It never stores README bodies.

Path-derived signals cover CI, tests, issue templates, citation metadata, and bundled sample-data candidates. The higher-level onboarding fields and conservative count of shell commands needed to reach a first result were reviewed from each landing page and directly linked documentation. `N/A` means a GUI-first project or library has no defensible comparable first-result CLI sequence.

The compact machine-readable evidence is [`2026-07-30.json`](benchmark_data/2026-07-30.json). The collector is [`scripts/benchmark_github_usability.py`](https://github.com/cfarkas/tumorquantai/blob/main/scripts/benchmark_github_usability.py).

### Sources and limitations

Primary sources are each project's GitHub repository, GitHub API metadata, release API, and documentation URL reported by the repository. The six discovery queries were `digital-pathology`, `whole-slide-imaging`, `computational-pathology`, `histopathology`, `nextflow`, and `scientific-workflow`, each constrained to non-archived repositories and sorted by stars.

Stars, forks, notification subscribers, releases, and recent pushes are visibility or activity proxies—not measures of real-world usage, quality, scientific validity, or clinical fitness. GitHub's `watchers_count` currently duplicates the star count, so the report shows the distinct `subscribers_count`. Path heuristics can miss external documentation or treat fixture assets as sample data. Manual feature review measures whether guidance was discoverable, not whether every documented path still executes. Values will change after the snapshot date.

## Comparison

| Repository | Stars | Forks | Subscribers | Last push | Latest release | License | Language | Docs |
|---|---:|---:|---:|---|---|---|---|---|
| [lh3/minimap2](https://github.com/lh3/minimap2) | 2224 | 470 | 81 | 2026-05-19 | 2026-05-19 | MIT | C | [docs](https://lh3.github.io/minimap2) |
| [nf-core/rnaseq](https://github.com/nf-core/rnaseq) | 1348 | 886 | 159 | 2026-07-24 | 2026-05-07 | MIT | Nextflow | [docs](https://nf-co.re/rnaseq) |
| [nf-core/tools](https://github.com/nf-core/tools) | 318 | 251 | 148 | 2026-07-30 | 2026-07-29 | MIT | Python | [docs](https://nf-co.re/docs/nf-core-tools/) |
| [nextflow-io/nextflow](https://github.com/nextflow-io/nextflow) | 3453 | 800 | 83 | 2026-07-30 | 2026-07-15 | Apache-2.0 | Groovy | [docs](https://docs.seqera.io/nextflow/) |
| [mahmoodlab/TRIDENT](https://github.com/mahmoodlab/TRIDENT) | 603 | 136 | 6 | 2026-07-24 | 2026-06-22 | CC-BY-NC-ND-4.0 | Python | [docs](https://trident-docs.readthedocs.io/en/latest/) |
| [mahmoodlab/CLAM](https://github.com/mahmoodlab/CLAM) | 1717 | 512 | 21 | 2025-04-14 | — | GPL-3.0 | Python | [docs](http://clam.mahmoodlab.org) |
| [TissueImageAnalytics/tiatoolbox](https://github.com/TissueImageAnalytics/tiatoolbox) | 542 | 108 | 8 | 2026-07-27 | 2026-07-21 | BSD-3-Clause | Python | [docs](https://tia-toolbox.readthedocs.io/en/stable/) |
| [SBU-BMI/wsinfer](https://github.com/SBU-BMI/wsinfer) | 86 | 14 | 3 | 2024-07-11 | 2024-02-22 | Apache-2.0 | Python | [docs](https://wsinfer.readthedocs.io/) |
| [qupath/qupath](https://github.com/qupath/qupath) | 1411 | 354 | 53 | 2026-07-27 | 2026-03-02 | GPL-3.0 | Java | [docs](https://qupath.readthedocs.io/) |
| [Project-MONAI/MONAI](https://github.com/Project-MONAI/MONAI) | 8546 | 1591 | 100 | 2026-07-30 | 2026-06-11 | Apache-2.0 | Python | [docs](https://monai.readthedocs.io/en/latest/) |
| [rendeirolab/LazySlide](https://github.com/rendeirolab/LazySlide) | 311 | 30 | 6 | 2026-07-28 | 2026-06-22 | MIT | Python | [docs](https://lazyslide.readthedocs.io/en/stable/) |
| [slideflow/slideflow](https://github.com/slideflow/slideflow) | 368 | 66 | 14 | 2026-05-07 | 2024-10-18 | Apache-2.0 | Python | [docs](https://slideflow.dev/) |
| [openslide/openslide](https://github.com/openslide/openslide) | 509 | 269 | 31 | 2026-06-28 | 2026-06-08 | LGPL-2.1 | C | [docs](https://openslide.org/#documentation) |
| [computationalpathologygroup/ASAP](https://github.com/computationalpathologygroup/ASAP) | 681 | 178 | 25 | 2023-09-12 | 2023-08-12 | GPL-2.0 | C++ | [docs](https://computationalpathologygroup.github.io/ASAP/) |
| [histolab/histolab](https://github.com/histolab/histolab) | 462 | 66 | 6 | 2026-07-28 | 2024-02-25 | Apache-2.0 | Python | [docs](https://histolab.readthedocs.io/en/latest/) |
| [Dana-Farber-AIOS/pathml](https://github.com/Dana-Farber-AIOS/pathml) | 460 | 87 | 11 | 2026-07-17 | 2026-07-09 | GPL-2.0 | Python | [docs](https://pathml.readthedocs.io/en/latest/) |

Archived state was also checked: every repository included in this dated comparison was active (not archived). License identifiers come from the GitHub API except for minimap2, TRIDENT, and TIAToolbox, whose repository license or terms notice was used because the API returned `NOASSERTION`. `None detected` is not legal advice and not evidence that reuse is permitted.

### Repository and onboarding signals

| Repository | CI | Tests | Issues | Citation | Sample data | Command near top | Commands to result | Demo | One sample | Doctor | Output example | Troubleshooting | Output reference | Research limits | Model/data license |
|---|:---:|:---:|:---:|:---:|:---:|:---:|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| lh3/minimap2 | Yes | Yes | No | No | Yes | Yes | 2 | Yes | Yes | No | No | Yes | Yes | — | — |
| nf-core/rnaseq | Yes | Yes | Yes | No | Yes | Yes | 2 | Yes | Yes | Yes | Yes | Yes | Yes | — | — |
| nf-core/tools | Yes | Yes | Yes | Yes | Yes | Yes | 2 | Yes | No | No | No | Yes | Yes | — | — |
| nextflow-io/nextflow | Yes | Yes | Yes | Yes | Yes | Yes | 3 | Yes | Yes | Yes | Yes | Yes | Yes | — | — |
| mahmoodlab/TRIDENT | Yes | Yes | Yes | No | No | Yes | 3 | No | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| mahmoodlab/CLAM | No | No | No | No | Yes | Yes | 4 | Yes | Yes | No | Yes | No | Yes | Yes | Yes |
| TissueImageAnalytics/tiatoolbox | Yes | Yes | No | Yes | Yes | Yes | 3 | Yes | Yes | No | Yes | No | Yes | No | Yes |
| SBU-BMI/wsinfer | Yes | Yes | No | No | No | Yes | 1 | No | Yes | No | Yes | No | Yes | Yes | Yes |
| qupath/qupath | Yes | Yes | Yes | No | Yes | No | N/A | Yes | Yes | No | Yes | Yes | Yes | Yes | — |
| Project-MONAI/MONAI | Yes | Yes | Yes | Yes | Yes | Yes | 3 | Yes | Yes | No | Yes | Yes | Yes | No | Yes |
| rendeirolab/LazySlide | Yes | Yes | Yes | No | Yes | No | 3 | Yes | Yes | No | Yes | Yes | Yes | No | Yes |
| slideflow/slideflow | Yes | Yes | Yes | No | Yes | Yes | 3 | Yes | Yes | No | Yes | Yes | Yes | No | Yes |
| openslide/openslide | Yes | Yes | Yes | No | No | No | N/A | No | No | No | No | No | Yes | — | — |
| computationalpathologygroup/ASAP | Yes | Yes | No | No | No | No | N/A | No | Yes | No | Yes | No | Yes | No | — |
| histolab/histolab | Yes | Yes | Yes | Yes | Yes | No | 3 | Yes | Yes | No | Yes | No | Yes | No | Yes |
| Dana-Farber-AIOS/pathml | Yes | Yes | Yes | Yes | Yes | Yes | 3 | Yes | Yes | No | Yes | No | Yes | No | No |

Feature labels are deliberately narrow: a demo must run without private credentials; a one-sample path must be visible to a newcomer; a doctor/preflight item must perform environment checks rather than merely list prerequisites; and an output reference must explain produced artifacts, not only show a screenshot. An em dash means the item is not applicable to that project type.

## Patterns adopted for TumorQuantAI

- **Command-first landing page:** minimap2 demonstrates that useful commands can precede long conceptual material. TumorQuantAI should show the structural demo immediately, followed by the real one-slide and inspect-only paths.
- **Test before expensive work:** nf-core's test profiles and Nextflow's reproducible execution model support a credential-free fixture workflow before model access, GPU use, or WSI downloads.
- **One cautious slide plus preflight:** TRIDENT's environment checks, single-slide progression, resume guidance, and explicit run state are a strong model for `doctor`, `status`, and a 1% smoke preset.
- **One high-level command:** WSInfer shows the value of a compact inference entry point. TumorQuantAI can expose a short wrapper while printing its expanded legacy/Nextflow command for auditability.
- **Teaching examples for several skill levels:** TIAToolbox, LazySlide, MONAI, histolab, and PathML use runnable examples or notebooks to bridge first use and API-level reference. TumorQuantAI should separate a synthetic structural demo, public one-slide tutorial, and expert reference.
- **Visible outputs and support routes:** nf-core, QuPath, CLAM, Slideflow, and TIAToolbox make output interpretation, limitations, and troubleshooting discoverable. TumorQuantAI should link the audit, matrices, overlays, and per-slide summary from one local start page.
- **Research and license boundaries:** pathology/ML projects commonly distinguish software terms from model or dataset conditions. TumorQuantAI should state research-only scope and keep software, HistoPLUS, and Zenodo dataset citations and permissions separate.

## Patterns deliberately rejected

- **Popularity as a quality score:** stars and forks are retained only as dated visibility proxies; they do not justify scientific or UX claims.
- **Badge-only evidence of readiness:** badges cannot replace a local, actionable doctor check and a fixture-based demo.
- **Network, GPU, or gated weights in the first success path:** those dependencies make normal CI and first-run diagnosis fragile, so the first result must be structural and offline-capable.
- **A magic wrapper that hides execution details:** a high-level façade is useful only if it preserves direct Nextflow/run-script access, prints the expanded command with secrets redacted, and records provenance.
- **GUI or notebook as the only reproducible interface:** both can be valuable teaching surfaces, but the canonical workflow must remain scriptable, resumable, and testable headlessly.
- **Implicit permission from public source code:** a visible repository without a declared license does not grant broad reuse permission. TumorQuantAI's license remains an explicit owner decision.
- **Copied project prose or visual branding:** this benchmark adopts interaction patterns only; labels are short categorical summaries and no README body is retained.

## Reproduce or refresh

```bash
python scripts/benchmark_github_usability.py --output docs/maintainers/benchmark_data/2026-07-30.json --markdown-output docs/maintainers/USABILITY_BENCHMARK.md
```

The command requires an authenticated GitHub CLI. Use `--offline` only after populating the specified cache; the default cache is under `/tmp` and is not part of the repository. Review the manual first-result counts and onboarding classifications whenever refreshing the snapshot.
