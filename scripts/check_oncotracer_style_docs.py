#!/usr/bin/env python3
"""Validate the public TumorQuantAI tutorials and copy/paste command blocks."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLONE = "git clone https://github.com/cfarkas/tumorquantai.git"
ENTER = "cd tumorquantai"

PRIMARY_DOCS = (
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

START_FROM_CLONE = (
    "README.md",
    "docs/index.md",
    "docs/installation.md",
    "docs/quick_start.md",
    "docs/full_tutorial.md",
    "docs/own_data.md",
    "docs/tutorials/four-public-slides.md",
    "examples/quickstart/README.md",
    "examples/lymphoma/README.md",
)

BASH_BLOCK = re.compile(r"```bash[ \t]*\n(.*?)```", re.DOTALL)
MARKDOWN_HEADING = re.compile(r"^\s*#{2,6}\s")

FORBIDDEN = (
    "REPO_DIR=",
    "$REPO_DIR",
    "/home/student/",
    "screen -S",
    "screen -r",
    "TQA_ROOT",
    "REPO_ROOT",
    "python3 -m venv",
    "python -m venv",
    "requirements-tutorial.txt",
)

FIGURES = (
    "docs/assets/tumorquantai-hero.svg",
    "docs/assets/tutorial/quickstart_wsi_flow.svg",
    "docs/assets/tutorial/full_lymphoma_flow.svg",
    "docs/assets/tutorial/input_layout.svg",
    "docs/assets/tutorial/sampling_presets.svg",
    "docs/assets/tutorial/output_map.svg",
)


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def read(relative_path: str) -> str:
    path = ROOT / relative_path
    if not path.is_file():
        fail(f"missing public documentation file: {relative_path}")
    return path.read_text(encoding="utf-8")


def check_bash_blocks(relative_path: str, text: str) -> None:
    blocks = BASH_BLOCK.findall(text)
    if not blocks:
        return
    for number, block in enumerate(blocks, start=1):
        first = next((line.strip() for line in block.splitlines() if line.strip()), "")
        if not first.startswith("#"):
            fail(f"Bash block {number} in {relative_path} must begin with #")
        for line in block.splitlines():
            if MARKDOWN_HEADING.match(line):
                fail(f"Markdown heading leaked into Bash block {number} in {relative_path}")
        completed = subprocess.run(
            ["bash", "-n"],
            input=block,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "unknown Bash syntax error"
            fail(f"invalid Bash block {number} in {relative_path}: {detail}")


def check_clone_order(relative_path: str, text: str) -> None:
    if CLONE not in text:
        fail(f"missing clone command in {relative_path}")
    if ENTER not in text:
        fail(f"missing cd tumorquantai in {relative_path}")
    if text.index(CLONE) > text.index(ENTER):
        fail(f"cd tumorquantai appears before cloning in {relative_path}")


def check_primary_docs() -> None:
    for relative_path in PRIMARY_DOCS:
        text = read(relative_path)
        if text.count("```") % 2:
            fail(f"unbalanced Markdown code fences in {relative_path}")
        for phrase in FORBIDDEN:
            if phrase in text:
                fail(f"forbidden verbose or server-specific text in {relative_path}: {phrase}")
        check_bash_blocks(relative_path, text)
        if relative_path in START_FROM_CLONE:
            check_clone_order(relative_path, text)


def check_quickstart() -> None:
    text = read("docs/quick_start.md")
    required = (
        "QuickStart Example 1: one public WSI",
        "TumorQuantAI_LymphomaWSI_022",
        "125350400",
        "0.261780",
        "--no-inference",
        "1%",
        "examples/quickstart/verify_outputs.py",
        "assets/tutorial/quickstart_wsi_flow.svg",
        "./tumorquantai install --docker",
        "./tumorquantai install --singularity",
        "./tumorquantai install --poetry",
        "./tumorquantai install --conda",
        "tumorquantai quickstart --no-inference",
    )
    for item in required:
        if item not in text:
            fail(f"QuickStart is missing required text: {item}")
    if "--preset full" in text:
        fail("QuickStart must not use the full preset")


def check_full_tutorial() -> None:
    text = read("docs/full_tutorial.md")
    required = (
        "21 public lymphoma WSIs at 10%",
        "zenodo_all_21.urls.txt",
        "checksums_all_21.sha256",
        "--expected-count 21",
        "--preset fast",
        "results-10-percent",
        "verify_fast21_outputs.py",
        "tumorquantai convert",
        "assets/tutorial/full_lymphoma_flow.svg",
    )
    for item in required:
        if item not in text:
            fail(f"Full tutorial is missing required text: {item}")
    if "--preset full" in text:
        fail("The maintained 21-slide tutorial must use 10%, not the full preset")
    if "100%" in text and "not" not in text:
        fail("The maintained 21-slide tutorial contains an unexplained 100% reference")


def check_readme_model_access() -> None:
    text = read("README.md")
    required = (
        "https://huggingface.co/Owkin-Bioptimus/histoplus",
        "$HOME/.config/tumorquantai/hf_token",
        "chmod 600",
        "tumorquantai doctor --online",
    )
    for item in required:
        if item not in text:
            fail(f"README model-access instructions are missing: {item}")


def check_figures() -> None:
    for relative_path in FIGURES:
        path = ROOT / relative_path
        if not path.is_file() or path.stat().st_size <= 0:
            fail(f"missing explanatory figure: {relative_path}")
        text = path.read_text(encoding="utf-8")
        if "<title" not in text or "<desc" not in text:
            fail(f"SVG lacks accessible title/description: {relative_path}")


def check_example_files() -> None:
    required = (
        "examples/quickstart/verify_outputs.py",
        "examples/lymphoma/verify_fast21_outputs.py",
        "examples/lymphoma/zenodo_one.urls.txt",
        "examples/lymphoma/zenodo_first_four.urls.txt",
        "examples/lymphoma/zenodo_all_21.urls.txt",
        "examples/lymphoma/checksums_one.sha256",
        "examples/lymphoma/checksums_first_four.sha256",
        "examples/lymphoma/checksums_all_21.sha256",
    )
    for relative_path in required:
        path = ROOT / relative_path
        if not path.is_file() or path.stat().st_size <= 0:
            fail(f"missing tutorial support file: {relative_path}")


def main() -> int:
    check_primary_docs()
    check_quickstart()
    check_full_tutorial()
    check_readme_model_access()
    check_figures()
    check_example_files()
    print("PASS: TumorQuantAI documentation follows the reproducible OncoTracer-style tutorial structure")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
