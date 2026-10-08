"""Run the same named gates locally and in GitHub Actions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.skip_governance import SkipGovernance
from scripts.ci.validate_evidence import validate_package


PACKAGE = ROOT / "ci-scientific-gates"
ARCHITECTURE = PACKAGE / "gate_architecture.json"


def _run(command: list[str], *, cwd: Path = ROOT) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_policy() -> None:
    architecture = _json(ARCHITECTURE)
    for gate_name, gate in architecture["gates"].items():
        for relpath in gate["tests"]:
            target = ROOT / relpath
            if not target.exists():
                raise SystemExit(f"{gate_name} references missing test path: {relpath}")
    invariants = _json(PACKAGE / "scientific_invariants.json")["invariants"]
    scientific_tests = set(architecture["gates"]["SCIENTIFIC"]["tests"])
    for invariant in invariants:
        if not invariant["tests"]:
            raise SystemExit(f"{invariant['id']} has no executable test mapping")
        missing = set(invariant["tests"]) - scientific_tests
        if missing:
            raise SystemExit(f"{invariant['id']} is not in SCIENTIFIC gate: {sorted(missing)}")
    claims = _json(PACKAGE / "claim_rules.json")
    if "RIOSE_SCIENTIFIC_CLAIM_REGISTRY.json" not in claims["historical_registry"]["path"]:
        raise SystemExit("historical claim registry treatment is missing")
    _validate_workflow()
    validate_package(PACKAGE)


def _validate_workflow() -> None:
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("PyYAML is required to validate GitHub Actions workflows") from exc

    for workflow_path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        workflow = yaml.load(workflow_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        if not isinstance(workflow, dict):
            raise SystemExit(f"invalid workflow document: {workflow_path}")
        if workflow.get("permissions") != {"contents": "read"}:
            raise SystemExit(f"workflow must declare only contents:read: {workflow_path}")
        if "pull_request_target" in workflow.get("on", {}):
            raise SystemExit(f"privileged pull_request_target is not allowed: {workflow_path}")
        text = workflow_path.read_text(encoding="utf-8")
        if "${{ secrets." in text or "${{ github.event.pull_request." in text:
            raise SystemExit(f"secret or untrusted PR data is interpolated into workflow: {workflow_path}")
        for job in workflow.get("jobs", {}).values():
            for step in job.get("steps", []):
                action = step.get("uses")
                if action and not re.search(r"@[0-9a-f]{40}$", action):
                    raise SystemExit(f"action is not pinned to a full commit SHA: {action}")
                if action and action.startswith("actions/checkout@"):
                    if step.get("with", {}).get("persist-credentials") != "false":
                        raise SystemExit("checkout must set persist-credentials:false")
                if "run" in step and "${{" in step["run"]:
                    raise SystemExit("GitHub expressions must not be interpolated into shell run blocks")


def _run_pytest(paths: list[str]) -> int:
    plugin = SkipGovernance(PACKAGE / "skip_classification.json")
    existing_pythonpath = os.environ.get("PYTHONPATH")
    source_path = str(ROOT / "src")
    os.environ["PYTHONPATH"] = source_path + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    return int(pytest.main(["-q", "-ra", *paths], plugins=[plugin]))


def _fast() -> None:
    _validate_policy()
    _run([sys.executable, "-m", "compileall", "-q", "src"])
    paths = _json(ARCHITECTURE)["gates"]["PR_FAST"]["tests"]
    if _run_pytest(paths) != pytest.ExitCode.OK:
        raise SystemExit(1)
    _run(["git", "diff", "--check"])


def _scientific() -> None:
    _validate_policy()
    paths = _json(ARCHITECTURE)["gates"]["SCIENTIFIC"]["tests"]
    if _run_pytest(paths) != pytest.ExitCode.OK:
        raise SystemExit(1)


def _full_python() -> None:
    _validate_policy()
    # Honor pyproject's complete testpaths, which include application tests
    # and the hardware model regression suite.
    if _run_pytest([]) != pytest.ExitCode.OK:
        raise SystemExit(1)


def _main() -> None:
    # Local EVM tests exercise Ganache and solc, so install the locked local
    # packages before collecting or running the Python suite.
    _run(["npm", "ci", "--prefix", "contracts"])
    _run(["node", "contracts/test/compile_registry.cjs", "contracts/src/RioseCommitmentRegistry.sol"])
    _full_python()
    build_dir = os.environ.get("RIOSE_CTEST_BUILD_DIR", "/tmp/riose-sc4-ci-ctest")
    _run(["cmake", "-S", "hardware/tests", "-B", build_dir])
    _run(["cmake", "--build", build_dir, "--parallel"])
    _run(["ctest", "--test-dir", build_dir, "--output-on-failure"])
    _run([
        "uv", "build", "--build-constraints", "build-constraints.txt",
        "--wheel", "--out-dir", "/tmp/riose-sc4-ci-dist",
    ])


def _heavy(args: argparse.Namespace) -> None:
    if args.duration <= 0:
        raise SystemExit("duration must be positive")
    if re.search(r"real|mainnet|testnet|sepolia|devnet|field|hardware|ganache|anvil|rpc|public|solana|arbitrum|base", args.backend, re.IGNORECASE):
        raise SystemExit("heavy request interface accepts simulation backends only")
    artifact_dir = Path(args.artifact_directory).expanduser().resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    source_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    source_tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    config_path = None
    config_sha256 = None
    if args.config_file:
        configured = Path(args.config_file)
        if configured.is_absolute():
            raise SystemExit("config file must be a repository-relative path")
        resolved_config = (ROOT / configured).resolve()
        if not resolved_config.is_relative_to(ROOT) or not resolved_config.is_file():
            raise SystemExit("config file must exist inside the repository")
        config_path = resolved_config.relative_to(ROOT).as_posix()
        config_sha256 = hashlib.sha256(resolved_config.read_bytes()).hexdigest()
    request = {
        "schema_version": "riose.simulation-campaign-request/v1",
        "request_status": "REQUEST_ONLY",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scenario": args.scenario,
        "seed": args.seed,
        "duration_seconds": args.duration,
        "backend": args.backend,
        "source_sha": source_sha,
        "source_tree": source_tree,
        "config_path": config_path,
        "config_sha256": config_sha256,
        "config_provenance_status": "VERIFIED" if config_sha256 else "UNAVAILABLE",
        "evidence_classification": "UNVERIFIED",
        "artifact_directory": str(artifact_dir),
        "limitations": ["No campaign was executed by this interface."],
    }
    encoded = json.dumps(request, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    destination = artifact_dir / "campaign-request.json"
    destination.write_bytes(encoded)
    print(f"REQUEST_ONLY {destination} sha256={hashlib.sha256(encoded).hexdigest()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gate", choices=["fast", "scientific", "python", "main", "heavy"])
    parser.add_argument("--scenario")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--backend")
    parser.add_argument("--artifact-directory")
    parser.add_argument("--config-file")
    args = parser.parse_args()
    if args.gate == "fast":
        _fast()
    elif args.gate == "scientific":
        _scientific()
    elif args.gate == "python":
        _full_python()
    elif args.gate == "main":
        _main()
    else:
        required = (args.scenario, args.seed, args.duration, args.backend, args.artifact_directory)
        if any(value is None for value in required):
            parser.error("heavy requires --scenario, --seed, --duration, --backend, and --artifact-directory")
        _heavy(args)


if __name__ == "__main__":
    main()
