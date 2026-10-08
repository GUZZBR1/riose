#!/usr/bin/env python3
"""Small, dependency-free SC-3 preflight and environment evidence collector."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BOOTSTRAP_VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN_PATH = ROOT / "hardware" / "toolchain.json"


def run(command: list[str], *, cwd: Path = ROOT) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command, cwd=cwd, text=True, capture_output=True, check=False, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": command, "exit_code": None, "stdout": "", "stderr": str(exc)}
    return {
        "command": command,
        "exit_code": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def first_line(command: list[str], *, cwd: Path = ROOT) -> str | None:
    result = run(command, cwd=cwd)
    if result["exit_code"] == 0 and result["stdout"]:
        return result["stdout"].splitlines()[0]
    return None


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_value(*args: str) -> str | None:
    result = run(["git", *args])
    return result["stdout"] if result["exit_code"] == 0 else None


def executable(name: str) -> dict[str, str | None]:
    path = shutil.which(name)
    return {"path": path, "version": None}


def tool_versions() -> dict[str, Any]:
    tools: dict[str, Any] = {
        "python": {"path": sys.executable, "version": platform.python_version()},
        "uv": executable("uv"),
        "node": executable("node"),
        "npm": executable("npm"),
        "cmake": executable("cmake"),
        "cc": executable("cc"),
        "cxx": executable("c++"),
        "solc": executable("solc"),
        "ganache": executable("ganache"),
        "west": executable("west"),
        "renode": executable("renode"),
        "renode_test": executable("renode-test"),
        "ngspice": executable("ngspice"),
        "openems": executable("openEMS"),
        "gz": executable("gz"),
        "docker": executable("docker"),
    }
    version_commands = {
        "uv": ["uv", "--version"],
        "node": ["node", "--version"],
        "npm": ["npm", "--version"],
        "cmake": ["cmake", "--version"],
        "cc": ["cc", "--version"],
        "cxx": ["c++", "--version"],
        "solc": ["solc", "--version"],
        "ganache": ["ganache", "--version"],
        "west": ["west", "--version"],
        "renode": ["renode", "--version"],
        "renode_test": ["renode-test", "--version"],
        "ngspice": ["ngspice", "--version"],
        "openems": ["openEMS", "--version"],
        "gz": ["gz", "sim", "--version"],
        "docker": ["docker", "--version"],
    }
    for name, command in version_commands.items():
        if tools[name]["path"]:
            tools[name]["version"] = first_line(command)

    local_bin = ROOT / "contracts" / "node_modules" / ".bin"
    if (local_bin / "ganache").exists():
        tools["ganache"] = {
            "path": str(local_bin / "ganache"),
            "version": first_line([str(local_bin / "ganache"), "--version"]),
        }
    solc_entry = ROOT / "contracts" / "node_modules" / "solc" / "solc.js"
    if solc_entry.is_file() and tools["node"]["path"]:
        result = run(["node", "-e", "console.log(require('./contracts/node_modules/solc').version())"])
        tools["solc"] = {
            "path": str(solc_entry),
            "version": result["stdout"] if result["exit_code"] == 0 else None,
        }
    return tools


def import_origin(name: str) -> str | None:
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError, ModuleNotFoundError):
        return None
    if spec is None:
        return None
    return spec.origin or (str(spec.submodule_search_locations[0]) if spec.submodule_search_locations else None)


def doctor(*, external_network_blocked: bool = False) -> dict[str, Any]:
    tools = tool_versions()
    checks: list[dict[str, Any]] = []

    def add(name: str, status: str, detail: str, evidence: Any = None) -> None:
        item: dict[str, Any] = {"name": name, "status": status, "detail": detail}
        if evidence is not None:
            item["evidence"] = evidence
        checks.append(item)

    py_ok = sys.version_info >= (3, 12)
    add("python", "READY" if py_ok else "INCOMPATIBLE", "Python >=3.12 is required.", tools["python"])
    expected_venv = (ROOT / ".venv").resolve()
    actual_venv = Path(sys.prefix).resolve()
    in_project_venv = actual_venv == expected_venv
    add("python_environment", "READY" if in_project_venv else "INCOMPATIBLE", "Run the doctor through uv so imports come from this checkout's repository-local .venv.", {"expected_prefix": str(expected_venv), "actual_prefix": str(actual_venv)})
    uv_version = tools["uv"]["version"]
    try:
        uv_parts = tuple(int(part) for part in uv_version.split()[1].split(".")[:3]) if uv_version else ()
        uv_ok = uv_parts >= (0, 11, 7)
    except (IndexError, ValueError):
        uv_ok = False
    add("uv", "READY" if uv_ok else "INCOMPATIBLE", "uv >=0.11.7 is expected; CI pins 0.11.7.", tools["uv"])

    required_files = ["pyproject.toml", "uv.lock", "contracts/package.json", "contracts/package-lock.json", "hardware/tests/CMakeLists.txt"]
    absent = [name for name in required_files if not (ROOT / name).is_file()]
    add("required_files", "READY" if not absent else "INCOMPATIBLE", "Required source and lock files.", {"missing": absent})

    lock_result = run(["uv", "lock", "--check", "--offline"]) if tools["uv"]["path"] else {"exit_code": None, "stdout": "", "stderr": "uv missing"}
    lock_ok = lock_result["exit_code"] == 0
    add("python_lock", "READY" if lock_ok else "INCOMPATIBLE", "uv.lock consistency check (offline).", lock_result)

    package_json = json.loads((ROOT / "contracts" / "package.json").read_text()) if (ROOT / "contracts" / "package.json").is_file() else {}
    package_lock = json.loads((ROOT / "contracts" / "package-lock.json").read_text()) if (ROOT / "contracts" / "package-lock.json").is_file() else {}
    expected_deps = package_json.get("dependencies", {})
    lock_root = package_lock.get("packages", {}).get("", {})
    locked_deps = lock_root.get("dependencies", {})
    npm_lock_ok = package_lock.get("lockfileVersion") == 3 and expected_deps == locked_deps and package_json.get("engines") == lock_root.get("engines")
    add("npm_lock", "READY" if npm_lock_ok else "INCOMPATIBLE", "package-lock root dependencies and engine constraints must match package.json.", {"expected": expected_deps, "locked": locked_deps, "expected_engines": package_json.get("engines"), "locked_engines": lock_root.get("engines"), "lockfile_version": package_lock.get("lockfileVersion")})

    for name in ("node", "npm"):
        available = bool(tools[name]["path"] and tools[name]["version"])
        add(name, "READY" if available else "OPTIONAL_MISSING", "Required for the local EVM test gate; not needed for Python-only use.", tools[name])
    for name in ("cmake", "cc"):
        available = bool(tools[name]["path"] and tools[name]["version"])
        add(name, "READY" if available else "OPTIONAL_MISSING", "Required for the host CMake/CTest gate.", tools[name])
    cmake_text = tools["cmake"]["version"] or ""
    try:
        cmake_ok = tuple(int(part) for part in cmake_text.split()[-1].split(".")[:2]) >= (3, 16)
    except ValueError:
        cmake_ok = False
    add("cmake_version", "READY" if cmake_ok else "INCOMPATIBLE", "Hardware CMake project requires CMake >=3.16.", cmake_text or None)

    node_file = (ROOT / ".nvmrc").read_text().strip() if (ROOT / ".nvmrc").is_file() else None
    node_version = (tools["node"]["version"] or "").lstrip("v")
    node_ok = bool(node_file and node_version == node_file)
    add("node_version", "READY" if node_ok else "INCOMPATIBLE", "Local EVM validation uses the exact Node version in .nvmrc.", {"expected": node_file, "actual": tools["node"]["version"]})
    package_manager = package_json.get("packageManager", "")
    npm_expected = package_manager.split("@", 1)[1] if "@" in package_manager else None
    npm_ok = bool(npm_expected and tools["npm"]["version"] == npm_expected)
    add("npm_version", "READY" if npm_ok else "INCOMPATIBLE", "Local EVM validation uses the npm version recorded in package.json.", {"expected": npm_expected, "actual": tools["npm"]["version"]})

    evm_modules = [ROOT / "contracts" / "node_modules" / name / "package.json" for name in ("ganache", "solc")]
    evm_missing = [path.parent.name for path in evm_modules if not path.is_file()]
    add("local_evm_dependencies", "READY" if not evm_missing else "OPTIONAL_MISSING", "Ganache and solc are required only for the local EVM gate; install with npm ci --prefix contracts.", {"missing": evm_missing})

    expected_env = {
        "PYTHONPATH": os.environ.get("PYTHONPATH"),
        "NODE_PATH": os.environ.get("NODE_PATH"),
        "VIRTUAL_ENV": os.environ.get("VIRTUAL_ENV"),
    }
    unexpected_env = {key: value for key, value in expected_env.items() if value and not Path(value).resolve().is_relative_to(ROOT)}
    add("environment_overrides", "READY" if not unexpected_env else "OPTIONAL_MISSING", "External Python/Node path overrides can change imports; values are reported only as paths, never secret variables.", {"configured_names": [key for key, value in expected_env.items() if value], "outside_checkout": list(unexpected_env)})

    imports = {
        "fastapi": ("required", expected_venv),
        "numpy": ("required", expected_venv),
        "scipy": ("required", expected_venv),
        "sklearn": ("required", expected_venv),
        "matplotlib": ("required", expected_venv),
        "pyarrow": ("required", expected_venv),
        "yaml": ("required", expected_venv),
        "construct": ("required", expected_venv),
        "pytest": ("required", expected_venv),
        "httpx": ("required", expected_venv),
        "solders": ("optional", expected_venv),
        "eth_account": ("optional", expected_venv),
        "eth_utils": ("optional", expected_venv),
        "hexbytes": ("optional", expected_venv),
    }
    origins = {"riose": import_origin("riose"), **{name: import_origin(name) for name in imports}}
    riose_origin = origins["riose"]
    unexpected_imports = []
    missing_required_imports = []
    missing_optional_imports = []
    for name, (requiredness, expected_root) in imports.items():
        origin = origins[name]
        if origin is None:
            (missing_required_imports if requiredness == "required" else missing_optional_imports).append(name)
        elif not Path(origin).resolve().is_relative_to(expected_root):
            unexpected_imports.append(name)
    source_ok = bool(riose_origin and Path(riose_origin).resolve().is_relative_to(ROOT / "src"))
    source_present = (ROOT / "src" / "riose" / "__init__.py").is_file()
    imports_ok = not unexpected_imports and not missing_required_imports and source_ok
    if imports_ok:
        import_status = "READY"
    elif unexpected_imports:
        import_status = "INCOMPATIBLE"
    elif external_network_blocked and (missing_required_imports or not source_ok):
        import_status = "EXTERNAL_BLOCKED"
    elif missing_required_imports or not source_present:
        import_status = "INCOMPATIBLE"
    else:
        import_status = "OPTIONAL_MISSING"
    add("import_provenance", import_status, "RIOSE must import from this checkout and Python dependencies from the repository-local .venv.", {"sys_prefix": sys.prefix, "expected_riose_source": str(ROOT / "src" / "riose"), "source_present": source_present, "origins": origins, "unexpected_imports": unexpected_imports, "missing_required_imports": missing_required_imports, "missing_optional_imports": missing_optional_imports})

    add("first_install_network", "EXTERNAL_BLOCKED" if external_network_blocked else "NOT_CONFIGURED", "Network is needed only for dependencies absent from local package caches; the doctor does not contact registries.", {"network_probe_performed": False})

    optional_tools = ("west", "renode", "renode_test", "ngspice", "openems", "gz", "docker")
    missing_optional = [name for name in optional_tools if not tools[name]["path"] or not tools[name]["version"]]
    add("optional_toolchains", "OPTIONAL_MISSING" if missing_optional else "READY", "Optional engineering/simulation tools are not required for the Python or host CTest route.", {"missing": missing_optional, "tools": {name: tools[name] for name in optional_tools}})

    core_failures = [c for c in checks if c["status"] == "INCOMPATIBLE"]
    external_blockers = [c for c in checks if c["status"] == "EXTERNAL_BLOCKED"]
    overall = "INCOMPATIBLE" if core_failures else ("EXTERNAL_BLOCKED" if external_blockers else "OPTIONAL_MISSING" if any(c["status"] == "OPTIONAL_MISSING" for c in checks) else "READY")
    return {
        "schema_version": 1,
        "kind": "doctor_report",
        "overall_status": overall,
        "scope": "local software preflight; does not contact public networks or validate physical hardware",
        "repository": str(ROOT),
        "source_sha": git_value("rev-parse", "HEAD"),
        "checks": checks,
        "tools": tools,
    }


def manifest() -> dict[str, Any]:
    tracked_tree = git_value("rev-parse", "HEAD^{tree}")
    git_status = git_value("status", "--porcelain=v1") or ""
    lockfiles = ["uv.lock", "contracts/package-lock.json"]
    config_files = ["pyproject.toml", "contracts/package.json", "hardware/toolchain.json", "Makefile"]
    tools = tool_versions()
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha": git_value("rev-parse", "HEAD"),
        "source_tree": {"git_tree_sha": tracked_tree, "working_tree_clean": not git_status, "status_lines": git_status.splitlines()},
        "os": {"system": platform.system(), "release": platform.release(), "version": platform.version(), "machine": platform.machine(), "architecture": platform.architecture()[0]},
        "python": tools["python"],
        "tools": tools,
        "lockfile_hashes_sha256": {name: sha256(ROOT / name) for name in lockfiles},
        "config_hash_sha256": {name: sha256(ROOT / name) for name in config_files},
        "bootstrap_version": BOOTSTRAP_VERSION,
        "environment_variable_names_set": sorted(name for name in ("PYTHONPATH", "NODE_PATH", "VIRTUAL_ENV", "UV_CACHE_DIR", "HTTP_PROXY", "HTTPS_PROXY") if os.environ.get(name)),
        "secrets_included": False,
    }


def write_report(report: dict[str, Any], output: str | None) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output:
        target = Path(output)
        if not target.is_absolute():
            target = ROOT / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered)
    else:
        print(rendered, end="")


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("doctor", "manifest"):
        sub = commands.add_parser(command)
        sub.add_argument("--output")
        if command == "doctor":
            sub.add_argument("--external-network-blocked", action="store_true", help="record a confirmed registry/network blocker without probing the network")
    args = parser.parse_args()
    report = doctor(external_network_blocked=args.external_network_blocked) if args.command == "doctor" else manifest()
    write_report(report, args.output)
    return 1 if args.command == "doctor" and report["overall_status"] == "INCOMPATIBLE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
