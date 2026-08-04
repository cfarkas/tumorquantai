"""Execute the repository CLI from a Poetry-managed environment."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def repository_root() -> Path:
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


def main() -> int:
    script = repository_root() / "tumorquantai"
    if not script.is_file():
        print(
            "ERROR: TumorQuantAI repository launcher was not found. "
            "Run Poetry from the cloned tumorquantai directory or set TUMORQUANTAI_REPO.",
            file=sys.stderr,
        )
        return 2
    return subprocess.call([sys.executable, str(script), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
