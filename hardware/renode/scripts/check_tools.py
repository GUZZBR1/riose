#!/usr/bin/env python3
"""Report Renode availability without making it a hard dependency."""
from __future__ import annotations

import shutil
import subprocess
import sys


def main() -> int:
    print("MCU_MODEL=STM32L071_PROXY (not exact STM32L031K6)")
    print("MCU_MEMORY_MAP=192KiB_flash,20KiB_RAM; candidate_L031=32KiB_flash,8KiB_RAM")
    print("LOW_POWER=STOP_current_and_wake_latency_not_modeled")
    print("SIMULATION_SCOPE=firmware_and_protocol_only;not_electrical_or_RF")
    missing = []
    for tool in ("renode", "renode-test"):
        path = shutil.which(tool)
        if path is None:
            print(f"{tool.upper().replace('-', '_')}_AVAILABLE=false")
            missing.append(tool)
            continue
        print(f"{tool.upper().replace('-', '_')}_AVAILABLE=true")
        print(f"{tool.upper().replace('-', '_')}_PATH={path}")
        if tool == "renode-test":
            # Renode's wrapper chooses this runner by host OS (see tests/common.sh):
            # `python3` on POSIX and `py -3` on Windows. Check that interpreter,
            # since Robot may be installed there but not in this script's Python.
            runner = ["py", "-3"] if sys.platform == "win32" else ["python3"]
            runner_path = shutil.which(runner[0])
            if runner_path is None:
                print("ROBOT_FRAMEWORK_VERSION=unknown (Renode Python runner unavailable)")
                continue
            version_command = [*runner, "-m", "robot", "--version"]
            print(f"RENODE_TEST_PYTHON={runner_path}")
        else:
            version_command = [path, "--version"]
        result = subprocess.run(version_command, capture_output=True, text=True)
        version = (result.stdout or result.stderr).strip().splitlines()
        version_label = "ROBOT_FRAMEWORK_VERSION" if tool == "renode-test" else f"{tool.upper().replace('-', '_')}_VERSION"
        print(f"{version_label}={version[0] if version else 'unknown'}")
    if missing:
        print("RENODE_TESTS=SKIPPED (install Renode to run headless platform tests)")
        return 0
    print("RENODE_TESTS=AVAILABLE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
