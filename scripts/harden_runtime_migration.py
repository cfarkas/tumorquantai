#!/usr/bin/env python3
"""Harden the temporary runtime migration before it is applied."""

from pathlib import Path

path = Path(__file__).with_name("apply_oncotracer_runtime.py")
text = path.read_text(encoding="utf-8")

old = "  - pip>=24\n  - pytorch=2.6.0\n"
new = "  - pip>=24\n  - git\n  - pytorch=2.6.0\n"
if old not in text:
    raise SystemExit("Unable to add Git to the versioned Conda environment")
text = text.replace(old, new, 1)

old = "prefix = config.split(marker, 1)[0]\nruntime_config = r'''process {\n"
new = """prefix = config.split(marker, 1)[0]
if "    conda_environment = " not in prefix:
    prefix = prefix.replace(
        "    docker_shm_size = '2g'\\n",
        "    docker_shm_size = '2g'\\n"
        "    conda_environment = \\\"${projectDir}/environment.yml\\\"\\n",
        1,
    )
runtime_config = r'''process {
"""
if old not in text:
    raise SystemExit("Unable to add the configurable Conda environment path")
text = text.replace(old, new, 1)

# A quoted pipe-separated name is ambiguous across Nextflow releases. Use an
# explicit regular-expression selector so every scientific process receives
# the selected container or Conda environment.
old = "            withName: 'DISCOVER_SLIDES|PROCESS_SLIDE|AGGREGATE_COUNTS' {\n"
new = "            withName: /DISCOVER_SLIDES|PROCESS_SLIDE|AGGREGATE_COUNTS/ {\n"
if old not in text:
    raise SystemExit("Unable to convert runtime process selectors to regexes")
text = text.replace(old, new)

old = '                conda = "${projectDir}/environment.yml"\n'
new = '                conda = params.conda_environment\n'
if old not in text:
    raise SystemExit("Unable to make the Conda environment path configurable")
text = text.replace(old, new, 1)

marker = "# ---------------------------------------------------------------------------\n# Poetry launcher\n# ---------------------------------------------------------------------------\n"
addition = '''write(
    "environment-ci.yml",
    """name: tumorquantai-runtime-ci
channels:
  - conda-forge
dependencies:
  - python=3.11
  - pandas>=2.2,<3
  - pyyaml>=6,<7
""",
)

'''
if marker not in text:
    raise SystemExit("Unable to add the lightweight Conda route-test environment")
text = text.replace(marker, addition + marker, 1)

# The run parser stores profile options in an argparse argument group named
# `execution`, while QuickStart stores them directly on its parser.
if "add_execution_profile_options(run)" not in text:
    raise SystemExit("Unable to repair the run parser backend insertion")
text = text.replace("add_execution_profile_options(run)", "add_execution_profile_options(execution)")
text = text.replace("add_execution_backend_options(run)", "add_execution_backend_options(execution)")

# The migration adds backend explicitly to the QuickStart run namespace and
# then updates the remaining function calls. Avoid adding it twice.
old = r"r'profile=args\.profile(?=\s*[,\)])',"
new = r"r'profile=args\.profile(?!\s*,\s*backend=)(?=\s*[,\)])',"
if old not in text:
    raise SystemExit("Unable to harden the QuickStart backend call replacement")
text = text.replace(old, new, 1)

# The generic replacement above already adds backend to the QuickStart
# argparse namespace. Remove the later exact rewrite, which would otherwise
# look for the pre-replacement text and fail.
old = '''replace_once(
    "tumorquantai",
    '        input=converted, output=smoke_results, preset="smoke", source_mpp=core.TUTORIAL_SOURCE_MPP,\\n        sample=core.TUTORIAL_SAMPLE, profile=args.profile, seed=args.seed,\\n',
    '        input=converted, output=smoke_results, preset="smoke",\\n'
    '        source_mpp=core.TUTORIAL_SOURCE_MPP, sample=core.TUTORIAL_SAMPLE,\\n'
    '        profile=args.profile, backend=args.backend, seed=args.seed,\\n',
)
'''
if old not in text:
    raise SystemExit("Unable to remove the redundant QuickStart namespace rewrite")
text = text.replace(
    old,
    "# QuickStart backend is injected by the generic manifest-call replacement.\n",
    1,
)

# The runtime test is itself written from a Python triple-quoted string. Keep
# its newline separator escaped in the generated source file.
old = r'    rendered = "\n".join(map(str, dependencies))'
new = r'    rendered = "\\n".join(map(str, dependencies))'
if old not in text:
    raise SystemExit("Unable to escape the generated runtime test newline")
text = text.replace(old, new, 1)

old = "    assert 'conda = \"${projectDir}/environment.yml\"' in config\n"
new = (
    '    assert "conda = params.conda_environment" in config\n'
    '    assert "conda_environment" in config\n'
    '    assert "withName: /DISCOVER_SLIDES|PROCESS_SLIDE|AGGREGATE_COUNTS/" in config\n'
)
if old not in text:
    raise SystemExit("Unable to update the runtime-profile Conda assertion")
text = text.replace(old, new, 1)

old = '''if [[ -z "${CONTAINER_IMAGE}" && ( "${BACKEND}" == "docker" || "${BACKEND}" == "singularity" ) ]]; then
  if [[ "${PROFILE}" == "gpu" ]]; then
    CONTAINER_IMAGE="carlosfarkas/lazyslide-histoplus@sha256:c4b02485d4549a56348cd09995ce0788a6acc8a3e1e600e986b644231a95bd25"
  else
    CONTAINER_IMAGE="carlosfarkas/lazyslide-histoplus@sha256:413bed6b55bc86923321c61453c18ece678da3c125ae44dcbd5f6c3bce7115d4"
  fi
fi
'''
new = old + '''
if [[ "${BACKEND}" == "singularity" \
  && "${CONTAINER_IMAGE}" != *://* \
  && "${CONTAINER_IMAGE}" != /* \
  && "${CONTAINER_IMAGE}" != *.sif ]]; then
  CONTAINER_IMAGE="docker://${CONTAINER_IMAGE}"
fi
'''
if old not in text:
    raise SystemExit("Unable to add the docker:// scheme for Singularity/Apptainer")
text = text.replace(old, new, 1)

# Preserve compatibility with existing programmatic callers and tests. Older
# QuickStart Namespace objects have no `backend`, and older callers monkeypatch
# `resolve_profile` with a one-argument function.
marker = "# ---------------------------------------------------------------------------\n# Runtime regression tests and CI parsing\n# ---------------------------------------------------------------------------\n"
compatibility = '''# Preserve backward-compatible programmatic entry points.
replace_once(
    "tumorquantai",
    "import argparse\\n",
    "import argparse\\nimport inspect\\n",
)
replace_once(
    "tumorquantai",
    '    requested_profile = resolve_profile(args.profile, args.backend)\\n',
    '    resolver = resolve_profile\\n'
    '    resolver_parameter_count = len(inspect.signature(resolver).parameters)\\n'
    '    requested_profile = (\\n'
    '        resolver(args.profile)\\n'
    '        if resolver_parameter_count == 1\\n'
    '        else resolver(args.profile, args.backend)\\n'
    '    )\\n',
)

quickstart_source = read("tumorquantai")
quickstart_start = quickstart_source.index("def cmd_quickstart(args: argparse.Namespace) -> int:\\n")
quickstart_end = quickstart_source.index("\\ndef main(", quickstart_start)
quickstart_section = quickstart_source[quickstart_start:quickstart_end]
quickstart_section = quickstart_section.replace(
    "def cmd_quickstart(args: argparse.Namespace) -> int:\\n    root =",
    "def cmd_quickstart(args: argparse.Namespace) -> int:\\n"
    "    backend = getattr(args, \\\"backend\\\", \\\"docker\\\")\\n"
    "    root =",
    1,
)
quickstart_section = quickstart_section.replace("args.backend", "backend")
quickstart_source = (
    quickstart_source[:quickstart_start]
    + quickstart_section
    + quickstart_source[quickstart_end:]
)
write("tumorquantai", quickstart_source)

'''
if marker not in text:
    raise SystemExit("Unable to add runtime compatibility patches")
text = text.replace(marker, compatibility + marker, 1)

path.write_text(text, encoding="utf-8")
