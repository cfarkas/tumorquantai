#!/usr/bin/env python3
"""Check public prose, terminology, and shell examples without network access."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

LANGUAGE_CONTRACT_FILES = frozenset({
    Path("README.md"),
    Path("docs/index.md"),
    Path("docs/how-to/download-mds.md"),
    Path("docs/start-here/public-slide.md"),
    Path("docs/tutorials/one-public-slide.md"),
    Path("docs/tutorials/four-public-slides.md"),
    Path("docs/tutorials/full-collection.md"),
    Path("docs/reference/parameters.md"),
    Path("examples/lymphoma/README.md"),
})
BANNED_PATTERNS = {
    "beginner framing": re.compile(r"\bbeginner(?:s|-first)?\b", re.IGNORECASE),
    "choice-grid heading": re.compile(r"\bchoose your path\b", re.IGNORECASE),
    "generated result-contract heading": re.compile(r"\bthe result contract\b", re.IGNORECASE),
    "generated demo label": re.compile(r"\bcredential-free structural demo\b", re.IGNORECASE),
    "bounded-plan label": re.compile(r"\bbounded public plan\b", re.IGNORECASE),
    "advanced-progression label": re.compile(r"\badvanced progression\b", re.IGNORECASE),
    "safe-beginner label": re.compile(r"\bsafe beginner\b", re.IGNORECASE),
    "readiness-state label": re.compile(r"\breadiness state\b", re.IGNORECASE),
}

LOCAL_PATH_PATTERNS = {
    "server-specific storage path": re.compile(r"/media/server/"),
    "server-specific home path": re.compile(r"/home/server/"),
}

CODE_FENCE = re.compile(
    r"^(?P<fence>`{3,}|~{3,})[^\n]*\n.*?^(?P=fence)\s*$",
    re.MULTILINE | re.DOTALL,
)

SHELL_FENCE = re.compile(
    r"^(?P<fence>`{3,}|~{3,})(?:bash|sh|shell)\s*\n"
    r"(?P<body>.*?)^(?P=fence)\s*$",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
SHELL_USE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)[^}]*\}|([A-Za-z_][A-Za-z0-9_]*))")
SHELL_ASSIGN = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=")
SHELL_FOR = re.compile(r"^for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b")
SHELL_READ_LOOP = re.compile(
    r"^while\s+IFS=\s+read\s+-r\s+([A-Za-z_][A-Za-z0-9_]*)\s*;\s*do$"
)
SHELL_ALLOWED = {
    "HOME", "PATH", "PWD", "OLDPWD", "SHELL", "TMPDIR", "USER", "UID", "GID",
    "HOSTNAME", "LANG", "LC_ALL", "TERM", "COLUMNS", "LINES",
}


@dataclass(frozen=True)
class Term:
    label: str
    abbreviation: re.Pattern[str]
    definition: re.Pattern[str]


TERMS = (
    Term("H&E", re.compile(r"\bH&E\b"), re.compile(r"hematoxylin\s+and\s+eosin", re.IGNORECASE)),
    Term("WSI", re.compile(r"\bWSIs?\b"), re.compile(r"whole-slide\s+images?", re.IGNORECASE)),
    Term("MPP", re.compile(r"\bMPP\b"), re.compile(r"micrometres\s+per\s+pixel", re.IGNORECASE)),
    Term("TIFF", re.compile(r"\bTIFFs?\b"), re.compile(r"Tagged\s+Image\s+File\s+Format", re.IGNORECASE)),
    Term("QC", re.compile(r"\bQC\b"), re.compile(r"quality(?:\s+|-)+control", re.IGNORECASE)),
    Term("CLI", re.compile(r"\bCLI\b"), re.compile(r"command-line\s+interface", re.IGNORECASE)),
    Term("GPU", re.compile(r"\bGPUs?\b"), re.compile(r"graphics\s+processing\s+units?", re.IGNORECASE)),
    Term("CPU", re.compile(r"\bCPUs?\b"), re.compile(r"central\s+processing\s+units?", re.IGNORECASE)),
    Term("DOI", re.compile(r"\bDOI\b"), re.compile(r"digital\s+object\s+identifier", re.IGNORECASE)),
    Term("MD5", re.compile(r"\bMD5\b"), re.compile(r"Message[- ]Digest(?:\s+Algorithm)?\s+5", re.IGNORECASE)),
    Term("SHA-256", re.compile(r"\bSHA-256\b"), re.compile(r"Secure\s+Hash\s+Algorithm\s+256(?:-bit)?", re.IGNORECASE)),
    Term("CSV", re.compile(r"\bCSV\b"), re.compile(r"comma-separated\s+values?", re.IGNORECASE)),
    Term("JSON", re.compile(r"\bJSON\b"), re.compile(r"JavaScript\s+Object\s+Notation", re.IGNORECASE)),
    Term("PHI", re.compile(r"\bPHI\b"), re.compile(r"protected\s+health\s+information", re.IGNORECASE)),
)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    return [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def public_markdown(files: list[Path]) -> list[Path]:
    """Return the entry surfaces governed by the first-use prose contract."""
    tracked = {path.relative_to(ROOT) for path in files}
    return [
        ROOT / relative for relative in sorted(LANGUAGE_CONTRACT_FILES)
        if relative in tracked and (ROOT / relative).is_file()
    ]


def text_for_terms(markdown: str) -> str:
    without_fences = CODE_FENCE.sub("", markdown)
    without_inline_code = re.sub(r"`[^`]*`", "", without_fences)
    without_urls = re.sub(r"https?://\S+", "", without_inline_code)
    return re.sub(r"<[^>]+>", "", without_urls)


def check_banned_language(files: list[Path], errors: list[str]) -> None:
    for path in files:
        relative = path.relative_to(ROOT)
        in_public_tree = bool(relative.parts) and relative.parts[0] in {
            "docs", "examples", ".github",
        }
        selected_root_file = relative.as_posix() in {
            "README.md", "AGENTS.md", "mkdocs.yml", "tumorquantai",
            "bin/tumorquantai_core.py", "scripts/benchmark_github_usability.py",
        }
        if not in_public_tree and not selected_root_file:
            continue
        if relative.as_posix().startswith("docs/maintainers/benchmark_data/"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in {**BANNED_PATTERNS, **LOCAL_PATH_PATTERNS}.items():
            match = pattern.search(text)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                errors.append(f"{relative}:{line}: {label}: {match.group(0)!r}")


def check_acronyms(files: list[Path], errors: list[str]) -> None:
    for path in public_markdown(files):
        text = text_for_terms(path.read_text(encoding="utf-8"))
        for term in TERMS:
            abbreviation = term.abbreviation.search(text)
            if not abbreviation:
                continue
            defined_before = term.definition.search(text[:abbreviation.start()])
            first_use = text[
                max(0, abbreviation.start() - 120):abbreviation.end() + 240
            ]
            defined_at_first_use = term.definition.search(first_use)
            if not defined_before and not defined_at_first_use:
                line = text.count("\n", 0, abbreviation.start()) + 1
                errors.append(
                    f"{path.relative_to(ROOT)}:{line}: define {term.label} before first use"
                )
        pyramid = re.search(r"\bL[02]\b", text)
        if pyramid:
            first_use = text[
                max(0, pyramid.start() - 160):pyramid.end() + 280
            ].casefold()
            pyramid_defined = re.search(r"image-pyramid\s+levels?", first_use)
            if not pyramid_defined or "highest-resolution" not in first_use:
                line = text.count("\n", 0, pyramid.start()) + 1
                errors.append(
                    f"{path.relative_to(ROOT)}:{line}: define L0/L2 as image-pyramid levels "
                    "and identify L0 as highest-resolution before first use"
                )


def undefined_shell_variables(body: str) -> set[str]:
    defined = set(SHELL_ALLOWED)
    undefined: set[str] = set()
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        assignment = SHELL_ASSIGN.match(line)
        loop = SHELL_FOR.match(line)
        read_loop = SHELL_READ_LOOP.match(line)
        newly_defined = {
            match.group(1)
            for match in (assignment, loop, read_loop) if match
        }
        for match in SHELL_USE.finditer(line):
            name = match.group(1) or match.group(2)
            if name not in defined and name not in newly_defined:
                undefined.add(name)
        defined.update(newly_defined)
    return undefined


def check_shell_blocks(files: list[Path], errors: list[str]) -> None:
    for path in public_markdown(files):
        text = path.read_text(encoding="utf-8")
        for number, match in enumerate(SHELL_FENCE.finditer(text), start=1):
            undefined = undefined_shell_variables(match.group("body"))
            if undefined:
                errors.append(
                    f"{path.relative_to(ROOT)}: shell block {number} uses undefined variables: "
                    + ", ".join(sorted(undefined))
                )
        placeholder = re.search(r"<(?:PATH|TOKEN|RELEASE)>", text, re.IGNORECASE)
        if placeholder:
            line = text.count("\n", 0, placeholder.start()) + 1
            errors.append(
                f"{path.relative_to(ROOT)}:{line}: undefined command placeholder {placeholder.group(0)!r}"
            )


def run_checks(files: list[Path] | None = None) -> list[str]:
    selected = tracked_files() if files is None else files
    errors: list[str] = []
    check_banned_language(selected, errors)
    check_acronyms(selected, errors)
    check_shell_blocks(selected, errors)
    return errors


def main() -> int:
    errors = run_checks()
    if errors:
        print("Documentation language checks failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Documentation language checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
