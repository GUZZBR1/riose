#!/usr/bin/env python3
"""Report Renode availability without making it a hard dependency."""
from __future__ import annotations

import shutil
import subprocess
import sys


def main() -> int:
    missing = []
    for tool in ("renode", "renode-test"):
        path = shutil.which(tool)
        if path is None:
            print(f"{tool.upper().replace('-', '_')}_AVAILABLE=false")
            missing.append(tool)
            continue
        print(f"{tool.upper().replace('-', '_')}_AVAILABLE=true")
        print(f"{tool.upper().replace('-', '_')}_PATH={path}")
        result = subprocess.run([path, "--version"], capture_output=True, text=True)
        version = (result.stdout or result.stderr).strip().splitlines()
        print(f"{tool.upper().replace('-', '_')}_VERSION={version[0] if version else 'unknown'}")
    if missing:
        print("RENODE_TESTS=SKIPPED (install Renode to run headless platform tests)")
        return 0
    print("RENODE_TESTS=AVAILABLE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
