#!/usr/bin/env python3
"""Make TumorQuantAI installable and simplify all beginner commands."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.rstrip() + "\n", encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Unable to patch {label}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"Unable to patch {label}; matches={count}")
    return updated


# ---------------------------------------------------------------------------
# Installable CLI and a no-edit QuickStart default
# ---------------------------------------------------------------------------
cli = read("tumorquantai")

cli = replace_once(
    cli,
    "import shlex\nimport shutil\nimport subprocess\nimport sys\nfrom pathlib import Path\nfrom typing import Any, Mapping, Sequence\n\nimport yaml\n\n\nROOT = Path(__file__).resolve().parent\nsys.path.insert(0, str(ROOT / \"bin\"))\n",
    '''import shlex
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import yaml
except ModuleNotFoundError:  # The install subcommand bootstraps PyYAML itself.
    yaml = None


def _looks_like_repository(path: Path) -> bool:
    return all(
        (path / relative).is_file()
        for relative in (
            "main.nf", "nextflow_schema.json", "bin/tumorquantai_core.py",
            "requirements-tutorial.txt",
        )
    )


def _repository_pointer(path: Path) -> Path | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not value:
        return None
    candidate = Path(value).expanduser().resolve()
    return candidate if _looks_like_repository(candidate) else None


def _resolve_repository_root() -> Path:
    configured = os.environ.get("TUMORQUANTAI_REPO", "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend((Path(__file__).resolve().parent, Path.cwd()))
    for pointer in (
        Path.home() / ".config/tumorquantai/repository",
        Path("/etc/tumorquantai/repository"),
    ):
        candidate = _repository_pointer(pointer)
        if candidate is not None:
            candidates.append(candidate)
    for candidate in candidates:
        resolved = candidate.resolve()
        if _looks_like_repository(resolved):
            return resolved
    raise SystemExit(
        "ERROR: TumorQuantAI cannot locate its repository. Run the command from "
        "the cloned tumorquantai directory or set TUMORQUANTAI_REPO."
    )


ROOT = _resolve_repository_root()
sys.path.insert(0, str(ROOT / "bin"))
''',
    "CLI bootstrap",
)

cli = regex_once(
    cli,
    r'''class _UniqueKeyLoader\(yaml\.SafeLoader\):.*?_UniqueKeyLoader\.add_constructor\(\n    yaml\.resolver\.BaseResolver\.DEFAULT_MAPPING_TAG,\n    _construct_unique_mapping,\n\)\n''',
    '''if yaml is not None:
    class _UniqueKeyLoader(yaml.SafeLoader):
        """Safe YAML loader that refuses ambiguous duplicate mappings."""


    def _construct_unique_mapping(
        loader: Any, node: Any, deep: bool = False,
    ) -> dict[Any, Any]:
        result: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in result:
                raise ValueError(f"duplicate parameter key {key!r}")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result


    _UniqueKeyLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        _construct_unique_mapping,
    )
else:
    class _UniqueKeyLoader:  # pragma: no cover - used only by bootstrap install
        pass
''',
    "optional YAML loader",
)

cli = regex_once(
    cli,
    r'''def _load_parameter_file\(path: Path\) -> dict\[str, Any\]:.*?    return normalized\n''',
    '''def _load_parameter_file(path: Path) -> dict[str, Any]:
    parameter_file = path.expanduser().resolve()
    try:
        text = parameter_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise _parameter_error(f"Could not read parameter file: {exc}") from exc
    suffix = parameter_file.suffix.lower()
    if yaml is None and suffix != ".json":
        raise _parameter_error(
            "YAML support is not installed. Run 'tumorquantai install --docker' "
            "or use a JSON parameter file."
        )
    try:
        if suffix == ".json":
            data = json.loads(text, object_pairs_hook=_unique_json_object)
        elif suffix in {".yaml", ".yml"}:
            assert yaml is not None
            data = yaml.load(text, Loader=_UniqueKeyLoader)
        else:
            try:
                data = json.loads(text, object_pairs_hook=_unique_json_object)
            except (json.JSONDecodeError, ValueError):
                if yaml is None:
                    raise _parameter_error(
                        "The parameter file is not JSON and YAML support is unavailable."
                    )
                data = yaml.load(text, Loader=_UniqueKeyLoader)
    except (json.JSONDecodeError, ValueError) as exc:
        raise _parameter_error(f"Invalid parameter file: {exc}") from exc
    except Exception as exc:
        if yaml is not None and isinstance(exc, yaml.YAMLError):
            raise _parameter_error(f"Invalid parameter file: {exc}") from exc
        raise
    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise _parameter_error("Parameter file must contain a top-level mapping.")
    if set(data) == {"params"}:
        data = data["params"]
        if not isinstance(data, Mapping):
            raise _parameter_error("The parameter-file 'params' value must be a mapping.")

    normalized: dict[str, Any] = {}
    for raw_key, value in data.items():
        if not isinstance(raw_key, str):
            raise _parameter_error("Every parameter-file key must be a string.")
        key = raw_key.replace("-", "_")
        if key in normalized:
            raise _parameter_error(
                f"Parameter file defines {key!r} more than once after key normalization."
            )
        normalized[key] = value

    allowed = set(PUBLIC_PARAMETER_OPTIONS) | set(LAUNCHER_DEFAULTS)
    internal = sorted(set(normalized) & set(INTERNAL_SCHEMA_PARAMETERS))
    if internal:
        raise _parameter_error(
            "Internal parameters cannot be set through tumorquantai: "
            + ", ".join(internal)
        )
    unknown = sorted(set(normalized) - allowed)
    if unknown:
        raise _parameter_error(
            "Unknown parameter-file key(s): " + ", ".join(unknown)
        )
    return normalized
''',
    "parameter-file loader",
)

install_helpers = r'''
NEXTFLOW_VERSION = "25.10.2"
NEXTFLOW_URL = (
    "https://github.com/nextflow-io/nextflow/releases/download/"
    f"v{NEXTFLOW_VERSION}/nextflow"
)
NEXTFLOW_SHA256 = "60aff30ad532030657296ca1fa72e37befda236bfd4fc7358a3cabf5e7589dd7"


def _configured_backend() -> str:
    value = os.environ.get("TUMORQUANTAI_BACKEND", "").strip().casefold()
    if value in {"docker", "singularity", "conda", "local"}:
        return value
    for path in (
        Path.home() / ".config/tumorquantai/backend",
        Path("/etc/tumorquantai/backend"),
    ):
        try:
            value = path.read_text(encoding="utf-8").strip().casefold()
        except OSError:
            continue
        if value in {"docker", "singularity", "conda", "local"}:
            return value
    return "docker"


def _install_command(command: Sequence[str], *, env: Mapping[str, str] | None = None) -> None:
    print("$ " + shlex.join([str(item) for item in command]))
    completed = subprocess.run(list(command), env=dict(env) if env else None, check=False)
    if completed.returncode != 0:
        raise core.TumorQuantAIError(
            f"Installation command failed with exit code {completed.returncode}: "
            + shlex.join([str(item) for item in command]),
            core.EXIT_PREFLIGHT,
        )


def _venv_python(environment: Path) -> Path:
    return environment / "bin/python"


def _prepare_python_environment(environment: Path) -> Path:
    python = _venv_python(environment)
    if not python.is_file():
        environment.parent.mkdir(parents=True, exist_ok=True)
        _install_command([sys.executable, "-m", "venv", str(environment)])
    _install_command([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    _install_command([
        str(python), "-m", "pip", "install", "--requirement",
        str(ROOT / "requirements-tutorial.txt"),
    ])
    return python


def _prepare_poetry_environment(state_dir: Path) -> Path:
    tool_environment = state_dir / "poetry-tool"
    poetry_python = _venv_python(tool_environment)
    if not poetry_python.is_file():
        _install_command([sys.executable, "-m", "venv", str(tool_environment)])
    _install_command([
        str(poetry_python), "-m", "pip", "install", "--upgrade", "pip",
        "poetry>=2,<3",
    ])
    poetry = tool_environment / "bin/poetry"
    environment = os.environ.copy()
    environment["POETRY_VIRTUALENVS_IN_PROJECT"] = "true"
    _install_command([str(poetry), "install", "--no-interaction"], env=environment)
    python = ROOT / ".venv/bin/python"
    if not python.is_file():
        raise core.TumorQuantAIError(
            "Poetry did not create the expected in-project environment.",
            core.EXIT_PREFLIGHT,
        )
    return python


def _install_nextflow(bin_dir: Path, *, allow_download: bool) -> Path | None:
    existing = shutil.which("nextflow")
    if existing:
        return Path(existing).resolve()
    target = bin_dir / "nextflow"
    if target.is_file():
        return target
    if not allow_download:
        return None
    print(f"Downloading pinned Nextflow {NEXTFLOW_VERSION}...")
    try:
        with urllib.request.urlopen(NEXTFLOW_URL, timeout=60) as response:
            payload = response.read()
    except OSError as exc:
        raise core.TumorQuantAIError(
            f"Could not download Nextflow: {exc}", core.EXIT_PREFLIGHT
        ) from exc
    digest = hashlib.sha256(payload).hexdigest()
    if digest != NEXTFLOW_SHA256:
        raise core.TumorQuantAIError(
            "Downloaded Nextflow checksum did not match the pinned release.",
            core.EXIT_DATA,
        )
    bin_dir.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(payload)
    temporary.chmod(0o755)
    os.replace(temporary, target)
    return target


def _java_major() -> int | None:
    if shutil.which("java") is None:
        return None
    completed = subprocess.run(
        ["java", "-version"], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    match = re.search(r'version "([0-9]+)', completed.stdout)
    return int(match.group(1)) if match else None


def _backend_issues(method: str) -> list[str]:
    issues: list[str] = []
    if method in {"docker", "poetry"}:
        if shutil.which("docker") is None:
            issues.append("Docker is not installed: https://docs.docker.com/engine/install/")
        else:
            result = subprocess.run(
                ["docker", "info"], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, check=False,
            )
            if result.returncode != 0:
                issues.append("Docker is installed but its daemon is not accessible.")
    elif method == "singularity":
        if shutil.which("apptainer") is None and shutil.which("singularity") is None:
            issues.append(
                "Install Apptainer or Singularity: "
                "https://apptainer.org/docs/admin/main/installation.html"
            )
    elif method == "conda":
        if shutil.which("conda") is None:
            issues.append(
                "Conda is not installed; install Miniforge: "
                "https://github.com/conda-forge/miniforge"
            )
    java = _java_major()
    if java is None:
        issues.append("Java is not installed; install Java 17 or newer.")
    elif java < 17:
        issues.append(f"Java {java} is too old; install Java 17 or newer.")
    return issues


def cmd_install(args: argparse.Namespace) -> int:
    method = args.install_method
    if args.system and args.prefix is not None:
        raise core.TumorQuantAIError(
            "Use either --system or --prefix, not both.", core.EXIT_USAGE
        )
    prefix = (
        Path("/usr/local") if args.system
        else (args.prefix or Path.home() / ".local")
    ).expanduser().resolve()
    state_dir = (
        Path("/usr/local/share/tumorquantai") if args.system
        else Path.home() / ".local/share/tumorquantai"
    )
    bin_dir = prefix / "bin"
    config_dir = Path("/etc/tumorquantai") if args.system else Path.home() / ".config/tumorquantai"
    wrapper = bin_dir / "tumorquantai"
    backend = "docker" if method == "poetry" else method

    print("TumorQuantAI installation plan:")
    print(f"  repository: {ROOT}")
    print(f"  method:     {method}")
    print(f"  command:    {wrapper}")
    print(f"  state:      {state_dir}")
    if args.dry_run:
        print("Dry run complete; no files or environments were changed.")
        return core.EXIT_OK

    try:
        bin_dir.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)
        config_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        raise core.TumorQuantAIError(
            "The selected installation prefix is not writable. Use the default "
            "user installation or rerun with sudo and --system.",
            core.EXIT_PREFLIGHT,
        ) from exc

    python = (
        _prepare_poetry_environment(state_dir)
        if method == "poetry"
        else _prepare_python_environment(state_dir / "venv")
    )
    nextflow = _install_nextflow(
        bin_dir, allow_download=not args.no_nextflow_download
    )

    wrapper_text = "\n".join((
        "#!/usr/bin/env bash",
        "set -Eeuo pipefail",
        f"export TUMORQUANTAI_REPO={shlex.quote(str(ROOT))}",
        f"export TUMORQUANTAI_BACKEND={shlex.quote(backend)}",
        f"export PATH={shlex.quote(str(bin_dir))}:\"$PATH\"",
        f"exec {shlex.quote(str(python))} {shlex.quote(str(ROOT / 'tumorquantai'))} \"$@\"",
        "",
    ))
    core.atomic_text(wrapper, wrapper_text, mode=0o755)
    core.atomic_text(config_dir / "repository", str(ROOT) + "\n", mode=0o644)
    core.atomic_text(config_dir / "backend", backend + "\n", mode=0o644)

    issues = _backend_issues(method)
    if nextflow is None:
        issues.append(
            "Nextflow is not installed. Rerun without --no-nextflow-download "
            "or install Nextflow 24.10 or newer."
        )

    print(f"Installed command: {wrapper}")
    if str(bin_dir) not in os.environ.get("PATH", "").split(os.pathsep):
        print(f'For this terminal, run: export PATH="{bin_dir}:$PATH"')
    if issues:
        print("The TumorQuantAI command is installed, but this route is not ready:")
        for issue in issues:
            print(f"  - {issue}")
        return core.EXIT_PREFLIGHT
    print(f"Installation and {method} readiness checks passed.")
    print("Next: tumorquantai quickstart --no-inference")
    return core.EXIT_OK


def _default_quickstart_output() -> Path:
    configured = os.environ.get("TUMORQUANTAI_DATA_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve() / "quickstart-one-wsi"
    return ROOT.parent / "tumorquantai-quickstart-one-wsi"

'''

cli = replace_once(
    cli,
    "def add_execution_profile_options(command: argparse.ArgumentParser) -> None:\n",
    install_helpers + "def add_execution_profile_options(command: argparse.ArgumentParser) -> None:\n",
    "install helpers",
)

cli = replace_once(
    cli,
    '    command.set_defaults(backend="docker")\n',
    '    command.set_defaults(backend=_configured_backend())\n',
    "configured backend default",
)
cli = cli.replace('prog="./tumorquantai"', 'prog="tumorquantai"')
cli = cli.replace('"  ./tumorquantai demo\\n"', '"  tumorquantai demo\\n"')
cli = cli.replace('"  ./tumorquantai inspect /data/slides --output /data/tqa-inspection\\n"', '"  tumorquantai inspect /data/slides --output /data/tqa-inspection\\n"')
cli = cli.replace('"  ./tumorquantai quickstart --output /mounted-storage/tutorial-one-slide --cpu"', '"  tumorquantai quickstart --no-inference"')

install_parser = '''
    install = subparsers.add_parser(
        "install",
        help="install the global command and prepare one execution method",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    route = install.add_mutually_exclusive_group(required=True)
    route.add_argument(
        "--docker", dest="install_method", action="store_const", const="docker",
        help="install the launcher and validate Docker",
    )
    route.add_argument(
        "--singularity", "--apptainer", dest="install_method",
        action="store_const", const="singularity",
        help="install the launcher and validate Singularity/Apptainer",
    )
    route.add_argument(
        "--poetry", dest="install_method", action="store_const", const="poetry",
        help="install the Poetry-managed launcher; Docker is the default backend",
    )
    route.add_argument(
        "--conda", dest="install_method", action="store_const", const="conda",
        help="install the launcher and validate Miniforge/Conda",
    )
    install.add_argument(
        "--prefix", type=Path,
        help="user installation prefix (default: ~/.local)",
    )
    install.add_argument(
        "--system", action="store_true",
        help="install under /usr/local and /etc; normally run with sudo",
    )
    install.add_argument(
        "--no-nextflow-download", action="store_true",
        help="do not download the pinned Nextflow launcher when it is absent",
    )
    install.add_argument(
        "--dry-run", action="store_true",
        help="print the installation plan without changing files",
    )

'''
cli = replace_once(
    cli,
    '    subparsers = parser.add_subparsers(dest="command", required=True)\n\n    doctor =',
    '    subparsers = parser.add_subparsers(dest="command", required=True)\n' + install_parser + '    doctor =',
    "install parser",
)

cli = replace_once(
    cli,
    '    quickstart.add_argument("--output", type=Path, required=True, help="tutorial root on a storage mount")\n',
    '    quickstart.add_argument(\n        "--output", type=Path,\n        help="tutorial root (default: ../tumorquantai-quickstart-one-wsi)"\n    )\n',
    "QuickStart default output",
)

cli = replace_once(
    cli,
    '            "./tumorquantai", "quickstart", "--output", str(root),\n',
    '            "tumorquantai", "quickstart", "--output", str(root),\n',
    "QuickStart resume command",
)
cli = replace_once(
    cli,
    'def cmd_quickstart(args: argparse.Namespace) -> int:\n    backend = getattr(args, "backend", "docker")\n    root = args.output.expanduser().resolve()\n',
    'def cmd_quickstart(args: argparse.Namespace) -> int:\n    backend = getattr(args, "backend", _configured_backend())\n    explicit_output = args.output is not None\n    root = (args.output or _default_quickstart_output()).expanduser().resolve()\n    print(f"QuickStart directory: {root}")\n',
    "QuickStart root",
)
cli = replace_once(
    cli,
    '    if not args.dry_run:\n        core.validate_large_data_root(root)\n        _check_quickstart_dependencies(args)\n',
    '    if not args.dry_run:\n        if explicit_output:\n            core.validate_large_data_root(root)\n        elif root == ROOT or ROOT in root.parents:\n            raise core.TumorQuantAIError(\n                "The default QuickStart directory resolved inside the repository.",\n                core.EXIT_PREFLIGHT,\n            )\n        _check_quickstart_dependencies(args)\n',
    "QuickStart storage policy",
)
cli = cli.replace("./tumorquantai quickstart", "tumorquantai quickstart")
cli = cli.replace("./tumorquantai doctor", "tumorquantai doctor")
cli = cli.replace("./tumorquantai status", "tumorquantai status")
cli = cli.replace("./tumorquantai report", "tumorquantai report")
cli = replace_once(
    cli,
    '        if args.command == "doctor":\n',
    '        if args.command == "install":\n            return cmd_install(args)\n        if args.command == "doctor":\n',
    "install dispatch",
)
write("tumorquantai", cli)

# Poetry's entry point can also find a repository recorded by the installer.
poetry_cli = read("tumorquantai_cli/cli.py")
poetry_cli = regex_once(
    poetry_cli,
    r'''def repository_root\(\) -> Path:.*?    return Path\(__file__\)\.resolve\(\)\.parents\[1\]\n''',
    '''def repository_root() -> Path:
    configured = os.environ.get("TUMORQUANTAI_REPO")
    if configured:
        return Path(configured).expanduser().resolve()
    local = Path(__file__).resolve().parents[1]
    if (local / "main.nf").is_file():
        return local
    for pointer in (
        Path.home() / ".config/tumorquantai/repository",
        Path("/etc/tumorquantai/repository"),
    ):
        try:
            candidate = Path(pointer.read_text(encoding="utf-8").strip()).expanduser().resolve()
        except OSError:
            continue
        if (candidate / "main.nf").is_file():
            return candidate
    return local
''',
    "Poetry repository lookup",
)
write("tumorquantai_cli/cli.py", poetry_cli)

# The verifier follows the same default as `tumorquantai quickstart`.
verifier = read("examples/quickstart/verify_outputs.py")
verifier = replace_once(
    verifier,
    'EXPECTED_PERCENT = 1.0\n',
    'EXPECTED_PERCENT = 1.0\nDEFAULT_ROOT = Path(__file__).resolve().parents[2].parent / "tumorquantai-quickstart-one-wsi"\n',
    "verifier default root",
)
verifier = replace_once(
    verifier,
    '        "--tutorial-root",\n        required=True,\n        type=Path,\n        help="root passed to ./tumorquantai quickstart --output",\n',
    '        "--tutorial-root",\n        type=Path,\n        default=DEFAULT_ROOT,\n        help="QuickStart root (default: ../tumorquantai-quickstart-one-wsi)",\n',
    "verifier optional root",
)
write("examples/quickstart/verify_outputs.py", verifier)

# The tiny worker must accept every argument used by the route matrix.
stub = read("tests/fixtures/stub_worker.py")
stub = replace_once(
    stub,
    '    "--mpp", "--tile-px", "--overlap", "--background-fraction", "--percent-slide",\n',
    '    "--mpp", "--slide-mpp", "--tile-px", "--overlap", "--background-fraction", "--percent-slide",\n',
    "stub source MPP option",
)
stub = replace_once(
    stub,
    '    "--histoplus-magnification", "--histoplus-repo-id", "--histoplus-revision",\n    "--histoplus-cache-dir",',
    '    "--histoplus-magnification", "--histoplus-repo-id", "--histoplus-revision",\n    "--histoplus-weight-file", "--histoplus-weight-sha256", "--histoplus-cache-dir",',
    "stub weight options",
)
write("tests/fixtures/stub_worker.py", stub)

# ---------------------------------------------------------------------------
# Beginner-first public documentation
# ---------------------------------------------------------------------------
for path in [ROOT / "README.md", *(ROOT / "docs").rglob("*.md"), *(ROOT / "examples").rglob("README.md")]:
    text = path.read_text(encoding="utf-8")
    text = text.replace("./tumorquantai", "tumorquantai")
    path.write_text(text, encoding="utf-8")

README = r'''# TumorQuantAI

![TumorQuantAI: whole-slide images to reviewable cell-type measurements](docs/assets/tumorquantai-hero.svg)

[![CI](https://github.com/cfarkas/tumorquantai/actions/workflows/ci.yml/badge.svg)](https://github.com/cfarkas/tumorquantai/actions/workflows/ci.yml)
[![Documentation](https://github.com/cfarkas/tumorquantai/actions/workflows/docs.yml/badge.svg)](https://cfarkas.github.io/tumorquantai/)
[![Release](https://img.shields.io/github/v/release/cfarkas/tumorquantai?sort=semver)](https://github.com/cfarkas/tumorquantai/releases/latest)
[![Dataset DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21466410.svg)](https://doi.org/10.5281/zenodo.21466410)

TumorQuantAI is a Nextflow research workflow for H&E whole-slide images (WSIs). It validates physical scale, samples tissue reproducibly, runs HistoPLUS, and writes overlays, cell coordinates, per-slide summaries, and cohort tables.

```text
H&E WSI -> validated scale -> tissue tiles -> HistoPLUS -> overlays + coordinates + cohort tables
```

**Research use only.** TumorQuantAI is not a diagnostic device. Predictions are not diagnoses or pathologist ground truth.

## Install the `tumorquantai` command

Clone the repository, enter it, and choose one installation method. The installer creates an isolated Python environment, installs the global command under `~/.local/bin`, installs pinned Nextflow when needed, and checks the selected runtime.

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai

# Install the command and prepare the Docker route.
./tumorquantai install --docker

# Make the user-level command available in this terminal.
export PATH="$HOME/.local/bin:$PATH"

# Confirm that the command is available.
tumorquantai --version
```

Choose only one installation command:

```bash
# Installation and execution through Docker.
./tumorquantai install --docker

# Installation and execution through Singularity or Apptainer.
./tumorquantai install --singularity

# Installation through Poetry; Docker is the default scientific backend.
./tumorquantai install --poetry

# Installation and execution through Conda.
./tumorquantai install --conda
```

For a system-wide command, use `sudo ./tumorquantai install --docker --system` or replace `--docker` with the selected method. The installer does not silently modify the operating-system package manager; when Docker, Apptainer/Singularity, Conda, Java, or another system prerequisite is missing, it prints the exact component that must be installed.

## QuickStart Example 1: one public WSI

No output path needs to be edited. The default directory is created beside the repository as `tumorquantai-quickstart-one-wsi`.

```bash
# Preview the fixed one-slide plan without downloading anything.
tumorquantai quickstart --dry-run

# Download, verify, convert, and inspect sample 022 without HistoPLUS inference.
tumorquantai quickstart --no-inference

# Verify the public download, L0/L2 conversion, and model-free inspection.
python3 examples/quickstart/verify_outputs.py --preparation-only
```

The command downloads only `TumorQuantAI_LymphomaWSI_022` from Zenodo record `21466410`, verifies its published size and checksums, converts L0 and L2, and writes `START_HERE.html`. Use `--output /another/directory` only when a different storage location is needed.

After authorized HistoPLUS access is configured, run the same one-slide 1% analysis through one route:

```bash
# Run through Docker on CPU.
tumorquantai quickstart --docker --cpu

# Run through Singularity or Apptainer on CPU.
tumorquantai quickstart --singularity --cpu

# Run through the Poetry-installed command with Docker.
tumorquantai quickstart --docker --cpu

# Run through Conda on CPU.
tumorquantai quickstart --conda --cpu
```

Then verify the inference outputs:

```bash
# Verify the overlay, summary, coordinates, class counts, and aggregation audit.
python3 examples/quickstart/verify_outputs.py
```

See the [complete one-WSI QuickStart](https://cfarkas.github.io/tumorquantai/quick_start/) for sample identity, checksums, model access, output review, and resume behavior.

## Full tutorial: 21 public lymphoma WSIs at 10%

The [full tutorial](https://cfarkas.github.io/tumorquantai/full_tutorial/) downloads all 21 public lymphoma MDS files, validates every SHA-256 checksum, converts L0/L2, and processes a deterministic 10% of detected tissue tiles per slide. It uses the `fast` preset and seed `20260709`.

## Run your own WSIs

Use one L0 TIFF and, for sampled analyses, one L2 companion per sample:

```text
slides/
└── case_001/
    ├── 1_L0_rgb.tif
    └── 1_L2_rgb.tif
```

```bash
# Inspect your own slides without running HistoPLUS.
tumorquantai inspect /path/to/slides \
  --output /path/to/tumorquantai-inspection \
  --source-mpp 0.261780

# Run a reproducible 10% Docker analysis after reviewing the inspection.
tumorquantai run /path/to/slides \
  --output /path/to/tumorquantai-results \
  --work-dir /path/to/tumorquantai-work \
  --preset fast \
  --source-mpp 0.261780 \
  --docker \
  --cpu
```

Do not copy an MPP from another slide. Use scanner or export provenance.

## Inspect these outputs first

| Path | Purpose |
| --- | --- |
| `START_HERE.html` | Run status and links to outputs that exist |
| `<sample>/overlays/celltypes_overview_and_zoom.png` | Visual alignment and cell-type overlay QC |
| `<sample>/summary/summary.json` | Completion, scale, sampling, seed, model, and provenance |
| `<sample>/cell_types/class_counts.csv` | Detected-cell counts in processed tissue tiles |
| `aggregated_celltypes/sample_aggregation_audit.csv` | Included, failed, incomplete, and excluded samples |
| `aggregated_celltypes/celltype_fractions_by_sample.csv` | Within-sample cell-type fractions |

A zero is interpretable only for a completed sample. Failed or incomplete samples do not become all-zero columns.

## Documentation

- [Installation](https://cfarkas.github.io/tumorquantai/installation/)
- [QuickStart Example 1](https://cfarkas.github.io/tumorquantai/quick_start/)
- [Execution methods](https://cfarkas.github.io/tumorquantai/execution_environments/)
- [Full 21-slide tutorial](https://cfarkas.github.io/tumorquantai/full_tutorial/)
- [Apply to your own WSIs](https://cfarkas.github.io/tumorquantai/own_data/)
- [Outputs](https://cfarkas.github.io/tumorquantai/outputs/)
- [Troubleshooting](https://cfarkas.github.io/tumorquantai/troubleshooting/)
'''
write("README.md", README)

INSTALLATION = r'''# Install TumorQuantAI

TumorQuantAI includes a self-installing command. Start from a fresh clone and choose one route.

## 1. Clone the repository

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
```

## 2. Choose one installation method

### Installation and execution through Docker

Install Docker Engine first, then run:

```bash
# Install the global command and validate Docker.
./tumorquantai install --docker

# Make the user-level command available now.
export PATH="$HOME/.local/bin:$PATH"

# Confirm the installed command and selected default backend.
tumorquantai --version
tumorquantai doctor
```

### Installation and execution through Singularity or Apptainer

Install Apptainer or Singularity first, then run:

```bash
# Install the global command and validate Singularity or Apptainer.
./tumorquantai install --singularity

# Make the user-level command available now.
export PATH="$HOME/.local/bin:$PATH"

# Confirm the installed command.
tumorquantai --version
```

### Installation through Poetry

This route creates an in-repository Poetry environment and installs the same global `tumorquantai` command. Docker is the default scientific backend; another backend can still be selected at execution time.

```bash
# Install Poetry in an isolated tool environment and install TumorQuantAI.
./tumorquantai install --poetry

# Make the user-level command available now.
export PATH="$HOME/.local/bin:$PATH"

# Confirm the installed command.
tumorquantai --version
```

### Installation and execution through Conda

Install Miniforge or Conda first, then run:

```bash
# Install the global command and validate Conda.
./tumorquantai install --conda

# Make the user-level command available now.
export PATH="$HOME/.local/bin:$PATH"

# Confirm the installed command.
tumorquantai --version
```

## What the installer changes

The default user installation writes only to:

```text
~/.local/bin/tumorquantai
~/.local/bin/nextflow              # only when Nextflow was absent
~/.local/share/tumorquantai/
~/.config/tumorquantai/repository
~/.config/tumorquantai/backend
```

It creates an isolated host-side Python environment for download, MDS conversion, and inspection. It records the cloned repository location so the command continues to work from any directory. The selected backend becomes the default, while `--docker`, `--singularity`, or `--conda` can override it for an individual run.

The installer validates system prerequisites but does not silently add operating-system repositories or invoke `sudo`. Follow the displayed official link when Docker, Apptainer/Singularity, Conda, or Java is missing.

## System-wide installation

```bash
# Install under /usr/local and /etc for all users.
sudo ./tumorquantai install --docker --system

# Confirm the system command.
tumorquantai --version
```

Replace `--docker` with `--singularity`, `--poetry`, or `--conda` as needed.

A manual copy also works when it is made from the clone and followed by the installer, because the command records the repository location:

```bash
# Optional manual launcher copy.
sudo cp tumorquantai /usr/local/bin/tumorquantai

# Run from the cloned repository so it can record this location.
tumorquantai install --docker
```

The built-in `--system` method is preferred because it also creates the managed Python environment and records the backend.

## Nextflow and Java

When `nextflow` is absent, the installer downloads pinned Nextflow `25.10.2` and verifies its SHA-256 checksum. Java 17 or newer is still required. Disable the download only when Nextflow is supplied by a module or administrator:

```bash
# Keep the external Nextflow installation unchanged.
./tumorquantai install --docker --no-nextflow-download
```

## First command

```bash
# Prepare one public WSI without model inference or an edited output path.
tumorquantai quickstart --no-inference
```

Continue with [QuickStart Example 1](quick_start.md).
'''
write("docs/installation.md", INSTALLATION)

QUICKSTART = r'''<a id="quick-start"></a>

# QuickStart Example 1: one public WSI

This tutorial downloads one public lymphoma WSI, validates its identity, converts Motic MDS levels L0 and L2 to TIFF, inspects the slide, and optionally runs a deterministic 1% HistoPLUS analysis.

![One-slide QuickStart workflow](assets/tutorial/quickstart_wsi_flow.svg)

## Fixed public sample

| Item | Value |
| --- | --- |
| Zenodo record | `21466410` |
| Sample | `TumorQuantAI_LymphomaWSI_022` |
| Download size | `125350400` bytes |
| MD5 | `94bb5b08ccf1957f8c42a579e8b33cfb` |
| SHA-256 | `db2988b5c6bc791510cec4127106509e604e577feafdb15b94c149043ed7067a` |
| Source MPP | `0.261780` µm/pixel |
| Converted levels | L0 and L2 |
| Optional inference | Seeded 1% of detected tissue tiles |

Public download and preparation need no Zenodo credential. HistoPLUS access is required only for inference.

## 1. Clone and install

Choose one installation command. Docker is shown first.

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai

# Install the command and Docker route.
./tumorquantai install --docker

# Make the installed command available in this terminal.
export PATH="$HOME/.local/bin:$PATH"
```

Alternative installation commands are:

```bash
# Install for Singularity or Apptainer.
./tumorquantai install --singularity

# Install through Poetry; Docker is the default scientific backend.
./tumorquantai install --poetry

# Install for Conda.
./tumorquantai install --conda
```

Run only the command for the route you will use.

## 2. Preview the plan

```bash
# Print the bounded one-slide plan without downloading.
tumorquantai quickstart --dry-run
```

The default directory is `../tumorquantai-quickstart-one-wsi`, beside the cloned repository. The command prints its resolved location. Use `--output /another/directory` only when a different filesystem is needed.

## 3. Download, verify, convert, and inspect

```bash
# Prepare sample 022 without running HistoPLUS.
tumorquantai quickstart --no-inference
```

This single command downloads the authoritative manifest and sample 022, verifies size, MD5, and SHA-256, converts L0/L2 with resumable state, writes `samples.csv`, performs model-free inspection, and creates `START_HERE.html`.

## 4. Verify the preparation

```bash
# Verify the default QuickStart directory.
python3 examples/quickstart/verify_outputs.py --preparation-only
```

Open first:

```text
../tumorquantai-quickstart-one-wsi/START_HERE.html
```

## 5. Configure HistoPLUS access

Follow [Configure authorized HistoPLUS access](how-to/model-access.md). Never place a token value on the command line or commit a model weight.

```bash
# Recheck the computer and authorized model-access path.
tumorquantai doctor --online
```

## 6. Run the one-slide 1% analysis

Choose one execution command:

### Docker

```bash
# Run QuickStart #1 through Docker on CPU.
tumorquantai quickstart --docker --cpu
```

### Singularity or Apptainer

```bash
# Run QuickStart #1 through Singularity or Apptainer on CPU.
tumorquantai quickstart --singularity --cpu
```

### Poetry

```bash
# Run from the Poetry environment with Docker.
poetry run tumorquantai quickstart --docker --cpu
```

The global command installed by `tumorquantai install --poetry` is equivalent:

```bash
# Run the Poetry-installed global command with Docker.
tumorquantai quickstart --docker --cpu
```

### Conda

```bash
# Run QuickStart #1 through the versioned Conda environment.
tumorquantai quickstart --conda --cpu
```

Use a GPU only after the selected container runtime and NVIDIA device pass `tumorquantai doctor`.

## 7. Verify inference outputs

```bash
# Verify the overlay, summary, coordinates, counts, and audit.
python3 examples/quickstart/verify_outputs.py
```

Review in this order:

1. `../tumorquantai-quickstart-one-wsi/START_HERE.html`
2. the one-slide cell-type overlay;
3. `summary.json`;
4. `class_counts.csv` and cell coordinates;
5. `sample_aggregation_audit.csv`.

The counts describe the selected 1% of detected tissue tiles. Do not multiply them by 100.

## Stop and resume

Press **Ctrl+C** to stop. Repeat the same command. Verified downloads, converted TIFFs, and valid Nextflow tasks are reused.

```bash
# Download and verify only.
tumorquantai quickstart --download-only

# Convert an already verified download.
tumorquantai quickstart --convert-only

# Regenerate preparation and inspection without inference.
tumorquantai quickstart --no-inference
```

## Continue

- [Full tutorial: all 21 lymphoma WSIs at 10%](full_tutorial.md)
- [Apply TumorQuantAI to your own WSIs](own_data.md)
- [Output files](outputs.md)
'''
write("docs/quick_start.md", QUICKSTART)

EXECUTION = r'''# Execution methods

TumorQuantAI exposes one installed command and four supported ways to prepare or execute the workflow.

![Four execution routes](assets/tutorial/runtime_routes.svg)

## Docker

```bash
# Install and select Docker as the default backend.
./tumorquantai install --docker
export PATH="$HOME/.local/bin:$PATH"

# Run an analysis explicitly through Docker.
tumorquantai run /path/to/slides \
  --output /path/to/results \
  --preset fast \
  --source-mpp 0.261780 \
  --docker \
  --cpu
```

## Singularity or Apptainer

```bash
# Install and select Singularity or Apptainer as the default backend.
./tumorquantai install --singularity
export PATH="$HOME/.local/bin:$PATH"

# Run an analysis explicitly through Singularity or Apptainer.
tumorquantai run /path/to/slides \
  --output /path/to/results \
  --preset fast \
  --source-mpp 0.261780 \
  --singularity \
  --cpu
```

## Poetry

```bash
# Install the Poetry-managed launcher.
./tumorquantai install --poetry
export PATH="$HOME/.local/bin:$PATH"

# Run through Poetry with Docker as the scientific backend.
poetry run tumorquantai run /path/to/slides \
  --output /path/to/results \
  --preset fast \
  --source-mpp 0.261780 \
  --docker \
  --cpu
```

The global `tumorquantai` command installed by the same operation can be used instead of `poetry run tumorquantai`.

## Conda

```bash
# Install and select Conda as the default backend.
./tumorquantai install --conda
export PATH="$HOME/.local/bin:$PATH"

# Run through the versioned Conda environment.
tumorquantai run /path/to/slides \
  --output /path/to/results \
  --preset fast \
  --source-mpp 0.261780 \
  --conda \
  --cpu
```

The versioned Conda route is CPU-only. Use Docker or Singularity/Apptainer for GPU execution.

## Override the installed default

The installer stores the selected default backend. Any run can override it with exactly one of:

```text
--docker
--singularity
--conda
--backend docker|singularity|conda|local
```

Keep separate output and work directories when comparing routes. Do not reuse one Nextflow work directory across different backends.
'''
write("docs/execution_environments.md", EXECUTION)

INDEX = r'''# TumorQuantAI

TumorQuantAI converts H&E whole-slide images into reproducible HistoPLUS cell-type outputs with explicit scale, sampling, provenance, and failure auditing.

![TumorQuantAI workflow](assets/tumorquantai-hero.svg)

## Start here

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai

# Install the global command and Docker route.
./tumorquantai install --docker
export PATH="$HOME/.local/bin:$PATH"

# Prepare the fixed public WSI without model inference.
tumorquantai quickstart --no-inference
```

Choose `--singularity`, `--poetry`, or `--conda` instead of `--docker` during installation when that is your intended route.

## Guided workflows

- [Install TumorQuantAI](installation.md)
- [QuickStart Example 1: one public WSI](quick_start.md)
- [Full tutorial: 21 lymphoma WSIs at 10%](full_tutorial.md)
- [Apply TumorQuantAI to your own WSIs](own_data.md)
- [Execution methods](execution_environments.md)
- [Understand the outputs](outputs.md)

Public WSI download, checksum validation, conversion, and inspection require no HistoPLUS credential. Inference requires separate authorized model access.

**Research use only.** Review slide quality, physical scale, sampling, overlays, failures, and biological plausibility. Do not use TumorQuantAI alone for patient-care decisions.
'''
write("docs/index.md", INDEX)

EXAMPLE_README = r'''# QuickStart Example 1 files

The canonical instructions are in [`docs/quick_start.md`](../../docs/quick_start.md).

```bash
# Clone, install, and prepare the fixed public WSI.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai
./tumorquantai install --docker
export PATH="$HOME/.local/bin:$PATH"
tumorquantai quickstart --no-inference

# Verify the default preparation directory.
python3 examples/quickstart/verify_outputs.py --preparation-only
```

After authorized HistoPLUS access is configured, run `tumorquantai quickstart --docker --cpu` and then run the verifier without `--preparation-only`.
'''
write("examples/quickstart/README.md", EXAMPLE_README)

# Make every remaining public command use the installed name.
for path in [ROOT / "README.md", *(ROOT / "docs").rglob("*.md"), *(ROOT / "examples").rglob("README.md")]:
    text = path.read_text(encoding="utf-8")
    text = text.replace("./tumorquantai", "tumorquantai")
    # Restore the only command that runs before the global launcher exists.
    text = text.replace("tumorquantai install --", "./tumorquantai install --")
    path.write_text(text, encoding="utf-8")

# ---------------------------------------------------------------------------
# Quality gates and tests
# ---------------------------------------------------------------------------
hygiene = read("scripts/check_repository_hygiene.py")
hygiene = replace_once(
    hygiene,
    'EXPECTED_HELP = {\n',
    'EXPECTED_HELP = {\n    "install": ("--docker", "--singularity", "--poetry", "--conda", "--system"),\n',
    "install help expectations",
)
hygiene = regex_once(
    hygiene,
    r'''def check_readme_quickstart\(errors: list\[str\]\) -> None:.*?\n\ndef main''',
    '''def check_readme_quickstart(errors: list[str]) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required_snippets = {
        "repository clone": "git clone https://github.com/cfarkas/tumorquantai.git",
        "Docker installer": "./tumorquantai install --docker",
        "Singularity installer": "./tumorquantai install --singularity",
        "Poetry installer": "./tumorquantai install --poetry",
        "Conda installer": "./tumorquantai install --conda",
        "global QuickStart": "tumorquantai quickstart --no-inference",
        "fixed public sample": "TumorQuantAI_LymphomaWSI_022",
        "preparation verifier": "examples/quickstart/verify_outputs.py --preparation-only",
    }
    for label, snippet in required_snippets.items():
        if snippet not in readme:
            errors.append(f"README is missing {label}: {snippet}")
    if "TQA_ROOT=/path/to/mounted/storage/tumorquantai-quickstart" in readme:
        errors.append("README QuickStart must not require an edited TQA_ROOT path")
    line_count = len(readme.splitlines())
    if not 100 <= line_count <= 350:
        errors.append(f"README should stay concise (100-350 lines); observed {line_count}")
    if not os.access(ROOT / "tumorquantai", os.X_OK):
        errors.append("root tumorquantai command is not executable")
        return
    with tempfile.TemporaryDirectory(prefix="tqa-readme-demo-") as temporary:
        output = Path(temporary) / "demo"
        environment = os.environ.copy()
        environment["HOME"] = str(Path(temporary) / "home")
        completed = subprocess.run(
            [str(ROOT / "tumorquantai"), "demo", "--output", str(output)],
            cwd=ROOT, text=True, capture_output=True, env=environment, check=False,
        )
        if completed.returncode != 0 or not (output / "START_HERE.html").is_file():
            errors.append("synthetic demo failed to create START_HERE.html")
        if "TumorQuantAI structural demo complete." not in completed.stdout:
            errors.append("synthetic demo success text drifted from executable output")


def main''',
    "README hygiene gate",
)
write("scripts/check_repository_hygiene.py", hygiene)

language = read("scripts/check_docs_language.py")
language = language.replace(
    '    "HF_TOKEN=hf_",\n',
    '    "HF_TOKEN=hf_",\n    "TQA_ROOT=/path/to/mounted/storage/tumorquantai-quickstart",\n',
)
language = language.replace(
    '    "--singularity", "poetry run tumorquantai", "--conda",\n',
    '    "--singularity", "poetry run tumorquantai", "--conda",\n    "./tumorquantai install --docker", "tumorquantai quickstart --no-inference",\n',
)
write("scripts/check_docs_language.py", language)

style = read("scripts/check_oncotracer_style_docs.py")
style = style.replace(
    '    "screen -r",\n',
    '    "screen -r",\n    "TQA_ROOT=/path/to/mounted/storage/tumorquantai-quickstart",\n',
)
style = style.replace(
    '        "assets/tutorial/quickstart_wsi_flow.svg",\n',
    '        "assets/tutorial/quickstart_wsi_flow.svg",\n        "./tumorquantai install --docker",\n        "./tumorquantai install --singularity",\n        "./tumorquantai install --poetry",\n        "./tumorquantai install --conda",\n        "tumorquantai quickstart --no-inference",\n',
)
write("scripts/check_oncotracer_style_docs.py", style)

TEST = r'''from __future__ import annotations

import os
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tumorquantai"


@pytest.mark.parametrize(
    ("flag", "method"),
    [
        ("--docker", "docker"),
        ("--singularity", "singularity"),
        ("--poetry", "poetry"),
        ("--conda", "conda"),
    ],
)
def test_install_parser_and_dry_run(flag: str, method: str, tmp_path: Path) -> None:
    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_install_test")
    args = namespace["build_parser"]().parse_args([
        "install", flag, "--prefix", str(tmp_path / "prefix"), "--dry-run"
    ])
    assert args.install_method == method
    assert namespace["cmd_install"](args) == 0
    assert not (tmp_path / "prefix").exists()


def test_quickstart_has_a_no_edit_default() -> None:
    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_quickstart_default")
    args = namespace["build_parser"]().parse_args(["quickstart", "--dry-run"])
    assert args.output is None
    default = namespace["_default_quickstart_output"]()
    assert default.name == "tumorquantai-quickstart-one-wsi"
    assert ROOT not in default.parents


def test_installed_backend_can_be_selected_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_backend_config")
    monkeypatch.setenv("TUMORQUANTAI_BACKEND", "conda")
    assert namespace["_configured_backend"]() == "conda"
    args = namespace["build_parser"]().parse_args(["quickstart", "--dry-run"])
    assert args.backend == "conda"


def test_program_name_is_global_command() -> None:
    namespace = runpy.run_path(str(CLI), run_name="tumorquantai_prog_test")
    parser = namespace["build_parser"]()
    assert parser.prog == "tumorquantai"
'''
write("tests/test_install_command.py", TEST)

print("Installable CLI, simplified QuickStart, documentation, and tests prepared.")
