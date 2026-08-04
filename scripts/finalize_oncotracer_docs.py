#!/usr/bin/env python3
"""Finalize the OncoTracer-style documentation and copy/paste examples."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_all(path: str, replacements: dict[str, str]) -> None:
    text = read(path)
    for old, new in replacements.items():
        text = text.replace(old, new)
    write(path, text)


# ---------------------------------------------------------------------------
# Canonical wording and real converter paths
# ---------------------------------------------------------------------------
for relative in (
    "README.md",
    "docs/index.md",
    "docs/installation.md",
    "docs/quick_start.md",
    "docs/own_data.md",
    "docs/full_tutorial.md",
    "docs/execution_environments.md",
    "docs/model_access.md",
    "docs/outputs.md",
    "docs/validation.md",
):
    replace_all(
        relative,
        {
            "beginner-first": "step-by-step",
            "beginner workflows": "step-by-step workflows",
            "H&E whole-slide images (WSIs)": "hematoxylin and eosin (H&E) whole-slide images (WSIs)",
            "H&E whole-slide images": "hematoxylin and eosin (H&E) whole-slide images",
            "Motic MDS examples": "Motic Digital Slide (MDS) examples",
            "MDS WSIs": "Motic Digital Slide (MDS) whole-slide images (WSIs)",
            "L0/L2 TIFF pairs": "level 0 and level 2 (L0/L2) Tagged Image File Format (TIFF) pairs",
            "L0/L2 images": "level 0 and level 2 (L0/L2) images",
            "source MPP": "source micrometres per pixel (MPP)",
            "CPU inference": "central processing unit (CPU) inference",
            "GPU inference": "graphics processing unit (GPU) inference",
        },
    )

replace_all(
    "docs/quick_start.md",
    {
        '$TQA_RUN/converted/TumorQuantAI_LymphomaWSI_022_L0_rgb.tif': '$TQA_RUN/converted/TumorQuantAI_LymphomaWSI_022/1_L0_rgb.tif',
        '$TQA_RUN/converted/TumorQuantAI_LymphomaWSI_022_L2_rgb.tif': '$TQA_RUN/converted/TumorQuantAI_LymphomaWSI_022/1_L2_rgb.tif',
        "The data are public; HistoPLUS access is required only for inference.": "The data are public; HistoPLUS access is required only for inference. L0 is the highest-resolution image-pyramid level and L2 is its lower-resolution companion.",
    },
)
replace_all(
    "README.md",
    {
        "Full tutorial: 21 lymphoma WSIs at 10%": "Full tutorial: 21 public lymphoma WSIs at 10%",
        "21 lymphoma WSIs": "21 public lymphoma WSIs",
    },
)
replace_all(
    "docs/full_tutorial.md",
    {
        "# Full tutorial: 21 lymphoma WSIs at 10%": "# Full tutorial: 21 public lymphoma WSIs at 10%",
        "21 privacy-sanitized lymphoma WSIs": "21 public privacy-sanitized lymphoma whole-slide images (WSIs)",
        "size, MD5, and SHA-256": "size, Message-Digest Algorithm 5 (MD5), and Secure Hash Algorithm 256-bit (SHA-256)",
    },
)

# ---------------------------------------------------------------------------
# Security, glossary, legacy redirects, and reference pages
# ---------------------------------------------------------------------------
write(
    "docs/security.md",
    """# Security and privacy

TumorQuantAI is designed for research whole-slide images. Do not commit patient slides, extracted coordinates, model weights, authentication tokens, or generated result directories.

## Credentials

Store the Hugging Face token in `~/.config/tumorquantai/hf_token` with file mode `0600`, or use an approved local weight file. Never put a token in a command, issue, screenshot, log, or workflow artifact.

## Data placement

Keep slides, model caches, Nextflow work, and results outside the Git clone on an access-controlled mounted filesystem. Review the repository-level [security policy](https://github.com/cfarkas/tumorquantai/security/policy) before reporting a vulnerability.

## Research limitation

TumorQuantAI and HistoPLUS outputs are research results. They are not a diagnosis, a treatment recommendation, or a substitute for expert pathology review.
""",
)
write(
    "docs/glossary.md",
    """# Glossary

| Term | Meaning |
| --- | --- |
| H&E | Hematoxylin and eosin stain |
| WSI | Whole-slide image |
| MDS | Motic Digital Slide container |
| L0 | Highest-resolution image-pyramid level used as the primary analysis image |
| L2 | Lower-resolution image-pyramid companion used during tissue sampling |
| TIFF | Tagged Image File Format |
| MPP | Micrometres per pixel; the physical pixel size |
| CPU | Central processing unit |
| GPU | Graphics processing unit |
| MD5 | Message-Digest Algorithm 5 checksum |
| SHA-256 | Secure Hash Algorithm 256-bit checksum |
| HistoPLUS | Gated upstream model used for cell detection and cell-type prediction |
| Nextflow work directory | Reusable task cache required for `-resume` |
""",
)

redirects = {
    "docs/QUICKSTART.md": ("QuickStart moved", "quick_start.md"),
    "docs/TUTORIAL_LYMPHOMA_ZENODO.md": ("Lymphoma tutorial moved", "full_tutorial.md"),
    "docs/start-here/public-slide.md": ("Public-slide QuickStart moved", "../quick_start.md"),
    "docs/start-here/own-slides.md": ("Own-slide guide moved", "../own_data.md"),
    "docs/tutorials/one-public-slide.md": ("One-slide tutorial moved", "../quick_start.md"),
    "docs/tutorials/four-public-slides.md": ("Public cohort tutorial moved", "../full_tutorial.md"),
    "docs/tutorials/full-collection.md": ("Full collection tutorial moved", "../full_tutorial.md"),
    "docs/how-to/install.md": ("Installation guide moved", "../installation.md"),
    "docs/how-to/model-access.md": ("Model-access guide moved", "../model_access.md"),
    "docs/runtime/index.md": ("Execution-environment guide moved", "../execution_environments.md"),
}
for path, (title, target) in redirects.items():
    write(path, f"# {title}\n\nContinue with [{title.lower()}]({target}).")

write(
    "docs/reference/outputs.md",
    """# Output reference

Start with [`START_HERE.html`](../outputs.md). It summarizes the run and links to the files below.

## Per-slide outputs

- `overview_with_zoom_box.png`: whole-slide overview and zoom location
- `zoom_overlay_celltypes.png`: detailed cell-type overlay
- `celltypes_overview_and_zoom.png`: combined visual quality-control figure
- `celltypes_overview_and_zoom.pdf`: PDF version of the combined figure
- `summary.json`: per-slide settings, tile sampling, and cell totals
- `class_counts.csv`: predicted class counts
- `cell_type_coordinates.csv`: predicted cell coordinates and classes

## Cohort outputs

- `celltype_counts_by_sample.csv`: wide count matrix
- `celltype_fractions_by_sample.csv`: wide fraction matrix
- `celltype_counts_long.csv`: long-format counts
- `sample_aggregation_audit.csv`: completed, failed, incomplete, and excluded samples
- `aggregation_summary.json`: cohort aggregation summary
- `workflow_aggregation_manifest.csv`: input/result linkage used by aggregation

## Workflow and report files

- `START_HERE.html`: first report to open
- `tumorquantai_report.json`: machine-readable report summary
- `nextflow.log`: workflow engine log
- `workflow_metadata/`: slides manifest, trace, timeline, report, and provenance

A failed or incomplete sample is recorded in the audit and is not represented as a biological zero.
""",
)
write(
    "docs/reference/cli.md",
    """# Command-line reference

Run `./tumorquantai COMMAND --help` for the authoritative options.

## `doctor`

Checks host readiness and accepts `--online`, `--json`, `--output`, and `--work-dir`.

## `demo`

Creates synthetic outputs with `--output`. Demo results are not scientific inference.

## `inspect`

Inspects inputs without HistoPLUS. Important options are `--output`, `--source-mpp`, `--sample-sheet`, `--pattern`, `--include`, and `--exclude`.

## `run`

Required: input path and `--output`.

Common options:

- `--preset smoke|fast|full`
- `--source-mpp FLOAT`
- `--sample ID`
- `--profile auto|cpu|gpu|local`
- `--docker`, `--singularity`, `--conda`, or `--backend METHOD`
- `--seed INTEGER`
- `--sample-sheet FILE`
- `--pattern GLOB`, `--include GLOB`, `--exclude GLOB`
- `--work-dir DIR`
- `--dry-run`, `--no-resume`
- `--token-file FILE`, `--local-weight FILE`
- `--params-file FILE`

## `status` and `report`

Both accept an output directory and optional `--json`.

## `quickstart`

Runs the public one-slide example. Important options are `--output`, `--dry-run`, `--download-only`, `--convert-only`, `--no-inference`, `--profile`, `--docker`, `--singularity`, `--conda`, `--seed`, and `--local-weight`.
""",
)

# ---------------------------------------------------------------------------
# Example READMEs and reusable verifiers
# ---------------------------------------------------------------------------
write(
    "examples/quickstart/README.md",
    """# QuickStart #1 files

The canonical instructions are in [`docs/quick_start.md`](../../docs/quick_start.md). The example downloads public sample `TumorQuantAI_LymphomaWSI_022`, verifies it, converts L0/L2, and creates a model-free inspection before any gated inference.

```bash
# Clone TumorQuantAI and run the one-slide preparation checkpoint.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-tutorial.txt
TQA_RUN="$(dirname "$PWD")/tumorquantai-quickstart-one-wsi"
./tumorquantai quickstart --output "$TQA_RUN" --no-inference
python examples/quickstart/verify_outputs.py "$TQA_RUN"
```

After approved HistoPLUS access is configured, choose Docker, Singularity/Apptainer, Poetry, or Conda as described in the QuickStart page.
""",
)
write(
    "examples/quickstart/verify_outputs.py",
    '''#!/usr/bin/env python3
"""Verify the public one-slide TumorQuantAI QuickStart."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

SAMPLE = "TumorQuantAI_LymphomaWSI_022"


def require(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"FAIL: missing or empty file: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--require-inference", action="store_true")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()

    required = (
        root / "download/tumorquantai_lymphoma_mds_manifest.csv",
        root / f"download/raw/{SAMPLE}/1.mds",
        root / f"converted/{SAMPLE}/1_L0_rgb.tif",
        root / f"converted/{SAMPLE}/1_L2_rgb.tif",
        root / "converted/samples.csv",
        root / "inspection/INSPECTION.html",
        root / "inspection/inspection_manifest.csv",
        root / "START_HERE.html",
    )
    for path in required:
        require(path)

    with (root / "inspection/inspection_manifest.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1 or rows[0].get("sample_id") != SAMPLE:
        raise SystemExit("FAIL: inspection manifest does not contain exactly sample 022")

    run_manifest = root / "tumorquantai_run.json"
    if run_manifest.is_file():
        payload = json.loads(run_manifest.read_text(encoding="utf-8"))
        if payload.get("tutorial_sample") != SAMPLE:
            raise SystemExit("FAIL: run manifest tutorial sample is incorrect")

    if args.require_inference:
        inference = root / "smoke-results"
        for path in (
            inference / "START_HERE.html",
            inference / f"{SAMPLE}/summary/summary.json",
            inference / f"{SAMPLE}/cell_types/class_counts.csv",
            inference / "aggregated_celltypes/sample_aggregation_audit.csv",
        ):
            require(path)

    print("SUCCESS: public one-slide QuickStart outputs are verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
)

write(
    "examples/lymphoma/README.md",
    """# Public lymphoma whole-slide image examples

TumorQuantAI uses the 21 privacy-sanitized public Motic Digital Slide (MDS) files in [Zenodo record 21466410](https://zenodo.org/records/21466410).

## QuickStart #1

Use one public whole-slide image (WSI), `TumorQuantAI_LymphomaWSI_022`, for download, checksum, conversion, inspection, and a deterministic 1% inference test after model access is configured. Follow [`docs/quick_start.md`](../../docs/quick_start.md).

## Full tutorial

The full tutorial downloads all 21 MDS files, verifies Secure Hash Algorithm 256-bit (SHA-256) checksums, converts image-pyramid levels L0 and L2, and analyzes 10% of detected tissue per slide with seed `20260709`. Follow [`docs/full_tutorial.md`](../../docs/full_tutorial.md).

## Four execution methods

The scientific workflow supports Docker, Singularity/Apptainer, Poetry with a selected backend, and a versioned central processing unit (CPU) Conda environment. Use one method per run and retain its Nextflow work directory for resume.

Files in this directory provide the 21 public URLs, SHA-256 checksums, manifest notes, and the cohort verifier. No slide, credential, or gated model weight is stored in Git.
""",
)
write(
    "examples/lymphoma/verify_outputs.py",
    '''#!/usr/bin/env python3
"""Verify the 21-slide public lymphoma preparation and optional result set."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def require(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"FAIL: missing or empty file: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, help="tumorquantai-lymphoma-21 directory")
    parser.add_argument("--results", type=Path)
    parser.add_argument("--require-all-complete", action="store_true")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    slides = root / "slides"
    require(slides / "samples.csv")
    l0 = sorted(slides.rglob("1_L0_rgb.tif"))
    l2 = sorted(slides.rglob("1_L2_rgb.tif"))
    if len(l0) != 21 or len(l2) != 21:
        raise SystemExit(
            f"FAIL: expected 21 L0 and 21 L2 files; found {len(l0)} and {len(l2)}"
        )
    with (slides / "samples.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 21 or len({row.get("sample_id") for row in rows}) != 21:
        raise SystemExit("FAIL: samples.csv does not contain 21 unique samples")

    if args.results:
        results = args.results.expanduser().resolve()
        for path in (
            results / "START_HERE.html",
            results / "aggregated_celltypes/sample_aggregation_audit.csv",
            results / "aggregated_celltypes/celltype_counts_by_sample.csv",
            results / "aggregated_celltypes/celltype_fractions_by_sample.csv",
        ):
            require(path)
        if args.require_all_complete:
            with (results / "aggregated_celltypes/sample_aggregation_audit.csv").open(
                newline="", encoding="utf-8"
            ) as handle:
                audit = list(csv.DictReader(handle))
            if len(audit) != 21:
                raise SystemExit("FAIL: aggregation audit does not contain 21 samples")
            rendered = "\n".join(",".join(row.values()) for row in audit).lower()
            if any(word in rendered for word in ("failed", "incomplete", "excluded")):
                raise SystemExit("FAIL: aggregation audit contains a non-complete sample")

    print("SUCCESS: 21-slide lymphoma preparation and requested results are verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
)

# ---------------------------------------------------------------------------
# Documentation checks, MkDocs paths, and workflow-independent requirements
# ---------------------------------------------------------------------------
write(
    "docs/requirements.txt",
    """mkdocs==1.6.1
mkdocs-material==9.6.21
""",
)
write(
    "requirements-docs.txt",
    """mkdocs==1.6.1
mkdocs-material==9.6.21
""",
)

mkdocs = read("mkdocs.yml")
mkdocs = mkdocs.replace("Security and Privacy: SECURITY.md", "Security and Privacy: security.md")
mkdocs = mkdocs.replace("Glossary: GLOSSARY.md", "Glossary: glossary.md")
write("mkdocs.yml", mkdocs)

write(
    "scripts/check_docs_language.py",
    '''#!/usr/bin/env python3
"""Check public documentation paths, shell variables, and tutorial scope."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = (
    "README.md",
    "docs/index.md",
    "docs/installation.md",
    "docs/quick_start.md",
    "docs/own_data.md",
    "docs/full_tutorial.md",
    "docs/execution_environments.md",
    "docs/model_access.md",
    "docs/outputs.md",
    "docs/validation.md",
    "examples/quickstart/README.md",
    "examples/lymphoma/README.md",
)
FORBIDDEN = (
    "/media/server/", "/home/server/", "/home/student/", "REPO_DIR=",
    "$REPO_DIR", "screen -S", "screen -r", "HF_TOKEN=hf_",
)
SHELL = re.compile(r"```(?:bash|sh|shell)\\s*\\n(.*?)```", re.DOTALL | re.IGNORECASE)
USE = re.compile(r"\\$(?:\\{([A-Za-z_][A-Za-z0-9_]*)[^}]*\\}|([A-Za-z_][A-Za-z0-9_]*))")
ASSIGN = re.compile(r"^(?:export\\s+)?([A-Za-z_][A-Za-z0-9_]*)=")
LOOP = re.compile(r"^for\\s+([A-Za-z_][A-Za-z0-9_]*)\\s+in\\b")
READ_LOOP = re.compile(r"^while\\s+IFS=\\s+read\\s+-r\\s+([A-Za-z_][A-Za-z0-9_]*)\\s*;\\s*do$")
ALLOWED = {
    "HOME", "PATH", "PWD", "OLDPWD", "SHELL", "TMPDIR", "USER", "UID",
    "GID", "HOSTNAME", "LANG", "LC_ALL", "TERM", "TQA_RUN", "TQA_DATA",
    "TQA_TOKEN", "SLIDES", "RESULTS", "INSPECTION", "ROOT", "READS_DIR",
    "PROJECT_DIR", "CONFIG", "NXF_CONDA_CACHEDIR", "filename", "url",
}


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def undefined(body: str) -> set[str]:
    defined = set(ALLOWED)
    missing: set[str] = set()
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        newly = {
            match.group(1)
            for match in (ASSIGN.match(line), LOOP.match(line), READ_LOOP.match(line))
            if match
        }
        for match in USE.finditer(line):
            name = match.group(1) or match.group(2)
            if name not in defined and name not in newly:
                missing.add(name)
        defined.update(newly)
    return missing


for relative in PUBLIC_FILES:
    path = ROOT / relative
    if not path.is_file():
        fail(f"missing public file: {relative}")
    text = path.read_text(encoding="utf-8")
    if text.count("```") % 2:
        fail(f"unbalanced Markdown fences in {relative}")
    if "~~~bash" in text or "~~~sh" in text:
        fail(f"legacy shell fence in {relative}")
    for phrase in FORBIDDEN:
        if phrase in text:
            fail(f"forbidden public text in {relative}: {phrase}")
    for number, block in enumerate(SHELL.findall(text), start=1):
        first = next((line.strip() for line in block.splitlines() if line.strip()), "")
        if not first.startswith("#"):
            fail(f"shell block {number} in {relative} must begin with #")
        missing = undefined(block)
        if missing:
            fail(f"shell block {number} in {relative} uses undefined variables: {sorted(missing)}")
        checked = subprocess.run(
            ["bash", "-n"], input=block, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if checked.returncode:
            fail(f"invalid shell block {number} in {relative}: {checked.stderr.strip()}")

full = (ROOT / "docs/full_tutorial.md").read_text(encoding="utf-8")
if "21 public lymphoma WSIs at 10%" not in full or "--percent-slide 10" not in full:
    fail("full tutorial must expose the 21-slide 10% workflow")
if "--preset full" in full:
    fail("full tutorial must not use the 100% full preset")

quick = (ROOT / "docs/quick_start.md").read_text(encoding="utf-8")
for required in (
    "TumorQuantAI_LymphomaWSI_022", "--no-inference", "--docker",
    "--singularity", "poetry run tumorquantai", "--conda",
):
    if required not in quick:
        fail(f"QuickStart is missing {required}")

print("Documentation language and command checks passed.")
''',
)

write(
    "tests/test_oncotracer_style_docs.py",
    '''#!/usr/bin/env python3
"""Validate step-by-step pages, explanatory figures, and all command boxes."""

from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = (
    "README.md", "docs/index.md", "docs/installation.md", "docs/quick_start.md",
    "docs/own_data.md", "docs/full_tutorial.md", "docs/execution_environments.md",
    "docs/model_access.md", "docs/outputs.md", "docs/validation.md",
    "examples/quickstart/README.md", "examples/lymphoma/README.md",
)
BASH = re.compile(r"```bash\\s*\\n(.*?)```", re.DOTALL)


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


for relative in PAGES:
    path = ROOT / relative
    if not path.is_file():
        fail(f"missing page: {relative}")
    text = path.read_text(encoding="utf-8")
    if "REPO_DIR=" in text or "$REPO_DIR" in text:
        fail(f"verbose repository variable in {relative}")
    for number, block in enumerate(BASH.findall(text), start=1):
        first = next((line.strip() for line in block.splitlines() if line.strip()), "")
        if not first.startswith("#"):
            fail(f"Bash block {number} in {relative} must begin with #")
        result = subprocess.run(
            ["bash", "-n"], input=block, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if result.returncode:
            fail(f"invalid Bash block {number} in {relative}: {result.stderr.strip()}")

for relative in (
    "docs/assets/tumorquantai-hero.svg",
    "docs/assets/tutorial/quickstart_flow.svg",
    "docs/assets/tutorial/runtime_routes.svg",
    "docs/assets/tutorial/full_tutorial_flow.svg",
    "docs/assets/tutorial/output_guide.svg",
):
    try:
        ET.parse(ROOT / relative)
    except (ET.ParseError, OSError) as exc:
        fail(f"invalid explanatory figure {relative}: {exc}")

quick = (ROOT / "docs/quick_start.md").read_text(encoding="utf-8")
for value in ("--docker", "--singularity", "poetry run tumorquantai", "--conda"):
    if value not in quick:
        fail(f"QuickStart is missing execution method {value}")
full = (ROOT / "docs/full_tutorial.md").read_text(encoding="utf-8")
for value in ("21 public lymphoma WSIs at 10%", "--preset fast", "--percent-slide 10"):
    if value not in full:
        fail(f"full tutorial is missing {value}")

print("PASS: step-by-step pages, four execution methods, figures, and Bash boxes are valid")
''',
)

# Extend help/reference checks for the newly public backend choices.
hygiene = read("scripts/check_repository_hygiene.py")
hygiene = hygiene.replace(
    '"--output", "--preset", "--source-mpp", "--sample", "--profile", "--seed",',
    '"--output", "--preset", "--source-mpp", "--sample", "--profile", "--backend", "--docker", "--singularity", "--conda", "--seed",',
)
hygiene = hygiene.replace(
    '"--output", "--dry-run", "--download-only", "--convert-only", "--no-inference", "--profile", "--seed", "--local-weight"),',
    '"--output", "--dry-run", "--download-only", "--convert-only", "--no-inference", "--profile", "--backend", "--docker", "--singularity", "--conda", "--seed", "--local-weight"),',
)
write("scripts/check_repository_hygiene.py", hygiene)

print("Final documentation, examples, and regression checks prepared.")
