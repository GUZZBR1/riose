from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

from scripts import reproducibility


def _doctor_tools(root: Path) -> dict:
    site_packages = root / ".venv" / "lib" / "python3.12" / "site-packages"
    tools = {
        "python": {"path": sys.executable, "version": platform.python_version()},
        "uv": {"path": "/usr/bin/uv", "version": "uv 0.11.26"},
    }
    for name in (
        "node", "npm", "cmake", "cc", "cxx", "solc", "ganache", "west",
        "renode", "renode_test", "ngspice", "openems", "gz", "docker",
    ):
        tools[name] = {"path": None, "version": None}
    return tools


def _install_doctor_fakes(monkeypatch, root: Path, riose_origin: str | None) -> None:
    monkeypatch.setattr(reproducibility, "ROOT", root)
    monkeypatch.setattr(reproducibility, "tool_versions", lambda: _doctor_tools(root))
    monkeypatch.setattr(
        reproducibility,
        "run",
        lambda command, cwd=root: {
            "command": command,
            "exit_code": 0,
            "stdout": "Resolved 68 packages",
            "stderr": "",
        },
    )
    site_packages = root / ".venv" / "lib" / "python3.12" / "site-packages"
    monkeypatch.setattr(
        reproducibility,
        "import_origin",
        lambda name: riose_origin if name == "riose" else str(site_packages / f"{name}.py"),
    )


def test_absent_optional_tools_do_not_make_python_doctor_incompatible(monkeypatch) -> None:
    root = Path(reproducibility.__file__).resolve().parents[1]
    _install_doctor_fakes(monkeypatch, root, str(root / "src/riose/__init__.py"))

    report = reproducibility.doctor()
    checks = {check["name"]: check for check in report["checks"]}

    for name in ("node", "npm", "cmake", "cmake_version", "node_version", "npm_version"):
        assert checks[name]["status"] == "OPTIONAL_MISSING"
    assert report["overall_status"] == "OPTIONAL_MISSING"


def test_riose_import_from_another_checkout_is_incompatible(monkeypatch, tmp_path: Path) -> None:
    root = Path(reproducibility.__file__).resolve().parents[1]
    foreign_origin = str(tmp_path / "other-checkout/src/riose/__init__.py")
    _install_doctor_fakes(monkeypatch, root, foreign_origin)

    report = reproducibility.doctor()
    checks = {check["name"]: check for check in report["checks"]}

    assert checks["import_provenance"]["status"] == "INCOMPATIBLE"
    assert checks["import_provenance"]["evidence"]["unexpected_project_import"] is True
    assert report["overall_status"] == "INCOMPATIBLE"


def test_local_evm_versions_must_match_lock_and_compiler(tmp_path: Path) -> None:
    root = tmp_path
    packages = root / "contracts/node_modules"
    for name, version in (("ganache", "7.9.2"), ("solc", "0.8.37")):
        package_dir = packages / name
        package_dir.mkdir(parents=True)
        (package_dir / "package.json").write_text(json.dumps({"version": version}))
    lock = {"packages": {
        "node_modules/ganache": {"version": "7.9.2"},
        "node_modules/solc": {"version": "0.8.37"},
    }}

    status, evidence = reproducibility.local_evm_check(root, lock, "0.8.36+commit.abc")

    assert status == "INCOMPATIBLE"
    assert evidence["mismatched"] == ["solc compiler"]

    status, evidence = reproducibility.local_evm_check(root, lock, "0.8.37+commit.def")

    assert status == "READY"
    assert evidence["mismatched"] == []
