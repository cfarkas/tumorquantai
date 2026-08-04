#!/usr/bin/env python3
"""Check public documentation terminology, paths, and shell examples."""

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
    "docs/full_tutorial.md",
    "docs/own_data.md",
    "docs/inputs.md",
    "docs/running.md",
    "docs/outputs.md",
    "docs/gallery.md",
    "docs/tutorials/four-public-slides.md",
    "examples/quickstart/README.md",
    "examples/lymphoma/README.md",
)

FORBIDDEN_TEXT = (
    "/media/server/",
    "/home/server/",
    "/home/student/",
    "REPO_DIR=",
    "$REPO_DIR",
    "screen -S",
    "screen -r",
    "HF_TOKEN=hf_",
    "TQA_ROOT=/path/to/mounted/storage/tumorquantai-quickstart",
)

SHELL_FENCE = re.compile(
    r"^```(?:bash|sh|shell)\s*\n(?P<body>.*?)^```\s*$",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
SHELL_USE = re.compile(
    r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)[^}]*\}|([A-Za-z_][A-Za-z0-9_]*))"
)
SHELL_ASSIGN = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=")
SHELL_FOR = re.compile(r"^for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b")
SHELL_READ_LOOP = re.compile(
    r"^while\s+IFS=\s+read\s+-r\s+([A-Za-z_][A-Za-z0-9_]*)\s*;\s*do$"
)
SHELL_ALLOWED = {
    "HOME",
    "PATH",
    "PWD",
    "OLDPWD",
    "SHELL",
    "TMPDIR",
    "USER",
    "UID",
    "GID",
    "HOSTNAME",
    "LANG",
    "LC_ALL",
    "TERM",
    "COLUMNS",
    "LINES",
    # Variables are deliberately introduced in an earlier numbered tutorial step.
    "TQA_ROOT",
    "REPO_ROOT",
    "TQA_INPUT",
    "TQA_INSPECTION",
    "TQA_DATA",
    "PROJECT_DIR",
    "CONFIG",
}


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def read(relative_path: str) -> str:
    path = ROOT / relative_path
    if not path.is_file():
        fail(f"missing public file: {relative_path}")
    return path.read_text(encoding="utf-8")


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
            for match in (assignment, loop, read_loop)
            if match
        }
        for match in SHELL_USE.finditer(line):
            name = match.group(1) or match.group(2)
            if name not in defined and name not in newly_defined:
                undefined.add(name)
        defined.update(newly_defined)
    return undefined


def check_file(relative_path: str) -> None:
    text = read(relative_path)
    if text.count("```") % 2:
        fail(f"unbalanced Markdown fences in {relative_path}")
    if "~~~bash" in text or "~~~sh" in text:
        fail(f"legacy tilde shell fence remains in {relative_path}")
    for phrase in FORBIDDEN_TEXT:
        if phrase in text:
            fail(f"forbidden public text in {relative_path}: {phrase}")
    for number, match in enumerate(SHELL_FENCE.finditer(text), start=1):
        body = match.group("body")
        undefined = undefined_shell_variables(body)
        if undefined:
            fail(
                f"shell block {number} in {relative_path} uses undefined variables: "
                + ", ".join(sorted(undefined))
            )


def main() -> int:
    for relative_path in PUBLIC_FILES:
        check_file(relative_path)

    full = read("docs/full_tutorial.md")
    if "--preset fast" not in full or "21 public lymphoma WSIs at 10%" not in full:
        fail("full tutorial must use the 21-slide 10% fast workflow")
    if "--preset full" in full:
        fail("full tutorial must not use the 100% full preset")

    quickstart = read("docs/quick_start.md")
    if "TumorQuantAI_LymphomaWSI_022" not in quickstart or "--no-inference" not in quickstart:
        fail("QuickStart must expose fixed sample 022 and model-free preparation")

    print("Documentation language and shell-variable checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
