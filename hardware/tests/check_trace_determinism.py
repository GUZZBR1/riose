"""Run the same virtual firmware scenario twice and compare exported traces."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    executable = sys.argv[1]
    with tempfile.TemporaryDirectory(prefix="riose-trace-") as directory:
        first = Path(directory) / "first.jsonl"
        second = Path(directory) / "second.jsonl"
        for destination in (first, second):
            subprocess.run(
                [executable, "--trace-output", str(destination), "--trace-scenario", "NORMAL"],
                check=True,
                capture_output=True,
                text=True,
            )
        if first.read_bytes() != second.read_bytes():
            raise SystemExit("same scenario produced different trace output")
    print("same scenario produced byte-identical traces")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
