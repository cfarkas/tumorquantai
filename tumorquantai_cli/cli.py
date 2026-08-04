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
    return Path(__file__).resolve().parents[1]


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
