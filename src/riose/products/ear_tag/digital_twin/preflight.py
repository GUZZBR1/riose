"""Toolchain and optional capability discovery."""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

from .paths import ROOT

def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False

def _version_matches(expected: str | None, observed: str | None) -> bool | None:
    if not expected or not observed:
        return None
    expected_token = re.search(r"\d+(?:\.\d+)+(?:[-.]?(?:rc|a|b|dev)\d+)?", expected, re.I)
    observed_token = re.search(r"\d+(?:\.\d+)+(?:[-.]?(?:rc|a|b|dev)\d+)?", observed, re.I)
    if not expected_token or not observed_token:
        return expected in observed
    expected_value = expected_token.group(0).lower().replace("-", "")
    observed_value = observed_token.group(0).lower().replace("-", "")
    if expected.endswith(".x"):
        return observed_value.startswith(expected_value)
    return observed_value == expected_value

def preflight() -> dict[str, Any]:
    toolchain_path = ROOT / "hardware" / "toolchain.json"
    toolchain = json.loads(toolchain_path.read_text(encoding="utf-8"))
    commands = {name: shutil.which(name) for name in (
        "python3", "uv", "micromamba", "ninja", "west", "renode", "renode-test",
        "ngspice", "openEMS", "openscad",
    )}
    modules = {name: _module_available(name) for name in ("yaml", "cadquery", "openEMS", "CSXCAD", "torch", "sionna")}
    distributions = {"yaml": "PyYAML", "cadquery": "cadquery", "openEMS": "openEMS",
                     "CSXCAD": "CSXCAD", "torch": "torch", "sionna": "sionna"}
    module_versions: dict[str, str | None] = {}
    for module, distribution in distributions.items():
        try:
            module_versions[module] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            module_versions[module] = None
    try:
        from hardware.antenna.capabilities import detect_capabilities
        gpu = detect_capabilities()
    except (ImportError, OSError):
        gpu = {"GPU_AVAILABLE": False, "GPU_TYPE": "UNKNOWN", "CUDA_AVAILABLE": False,
               "SIONNA_AVAILABLE": False, "status": "UNAVAILABLE", "experiment": "OPTIONAL_GPU_EXPERIMENT"}
    versions: dict[str, dict[str, Any]] = {}
    version_args = {
        "python3": ["--version"], "uv": ["--version"], "micromamba": ["--version"],
        "ninja": ["--version"], "west": ["--version"], "renode": ["--version"],
        # Renode's Robot wrapper has no --version flag; --help is its clean probe.
        "renode-test": ["--help"], "ngspice": ["--version"], "openEMS": ["--help"],
    }
    expected_commands = {
        "python3": toolchain.get("host", {}).get("python"),
        "uv": toolchain.get("host", {}).get("uv"),
        "micromamba": toolchain.get("host", {}).get("micromamba"),
        "ninja": toolchain.get("host", {}).get("ninja"),
        "west": toolchain.get("host", {}).get("west"),
        **toolchain.get("optional_external", {}),
    }
    for name, executable in commands.items():
        expected = expected_commands.get(name)
        if not executable:
            versions[name] = {"status": "NOT_AVAILABLE", "expected": expected,
                              "matches_expected": None}
            continue
        args = version_args.get(name)
        if not args:
            versions[name] = {"status": "PATH_ONLY", "path": executable,
                              "expected": expected, "matches_expected": None}
            continue
        try:
            result = subprocess.run([executable, *args], capture_output=True, text=True,
                                    timeout=5, check=False)
            output = (result.stdout or result.stderr).strip().splitlines()
            observed = next((line for line in output if _version_matches(expected, line) is True),
                            output[0] if output else None)
            matches = (None if result.returncode != 0 else _version_matches(expected, observed))
            versions[name] = {"status": "AVAILABLE" if result.returncode == 0 else "VERSION_PROBE_FAILED",
                              "path": executable, "version": observed, "expected": expected,
                              "matches_expected": matches, "return_code": result.returncode}
        except (OSError, subprocess.TimeoutExpired) as exc:
            versions[name] = {"status": "VERSION_PROBE_FAILED", "path": executable,
                              "expected": expected, "matches_expected": None, "detail": str(exc)}
    expected_modules = toolchain.get("optional_external", {})
    for module in modules:
        expected = expected_modules.get(module)
        observed = module_versions.get(module)
        versions[f"module:{module}"] = {
            "status": "AVAILABLE" if modules[module] else "NOT_AVAILABLE",
            "version": observed, "expected": expected,
            "matches_expected": _version_matches(expected, observed),
        }
    zephyr_base = os.environ.get("ZEPHYR_BASE")
    expected_zephyr = toolchain.get("host", {}).get("zephyr")
    zephyr_version: str | None = None
    if zephyr_base:
        version_file = Path(zephyr_base) / "VERSION"
        if version_file.is_file():
            fields = {}
            for line in version_file.read_text(encoding="utf-8").splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    fields[key.strip()] = value.strip()
            if all(key in fields for key in ("VERSION_MAJOR", "VERSION_MINOR", "PATCHLEVEL")):
                zephyr_version = ".".join(fields[key] for key in ("VERSION_MAJOR", "VERSION_MINOR", "PATCHLEVEL"))
    versions["zephyr"] = {"status": "AVAILABLE" if zephyr_version else "NOT_CONFIGURED",
                           "path": zephyr_base, "version": zephyr_version, "expected": expected_zephyr,
                           "matches_expected": (str(expected_zephyr) in zephyr_version if zephyr_version else None)}
    sdk_expected = toolchain.get("host", {}).get("zephyr_sdk")
    sdk_root = os.environ.get("ZEPHYR_SDK_INSTALL_DIR")
    if not sdk_root and sdk_expected:
        candidate = Path.home() / ".local" / "opt" / f"zephyr-sdk-{sdk_expected}"
        if candidate.is_dir():
            sdk_root = str(candidate)
    sdk_version_file = Path(sdk_root) / "sdk_version" if sdk_root else None
    sdk_version = sdk_version_file.read_text(encoding="utf-8").strip() if sdk_version_file and sdk_version_file.is_file() else None
    versions["zephyr_sdk"] = {"status": "AVAILABLE" if sdk_version else "NOT_AVAILABLE",
                               "path": sdk_root, "version": sdk_version, "expected": sdk_expected,
                               "matches_expected": (sdk_version == str(sdk_expected) if sdk_version else None)}
    return {"status": "ENVIRONMENT_PROBE_ONLY", "platform": platform.platform(),
            "python": sys.version.split()[0], "commands": commands, "modules": modules,
            "module_versions": module_versions, "versions": versions, "toolchain_manifest": str(toolchain_path),
            "gpu": gpu,
            "physical_hardware_used": False}
