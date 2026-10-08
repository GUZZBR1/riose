from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.ci.run_gate import PACKAGE, ROOT, _heavy, _validate_policy
from scripts.ci.skip_governance import SkipGovernance
from scripts.ci.validate_evidence import EvidenceError, validate_claims, validate_evidence_record, validate_package


def test_ci_policy_has_present_test_paths_for_every_gate_and_invariant():
    _validate_policy()


def test_historical_claim_registry_is_not_current_sc4_evidence():
    rules = json.loads((PACKAGE / "claim_rules.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "RIOSE_SCIENTIFIC_CLAIM_REGISTRY.json").read_text(encoding="utf-8"))
    assert rules["historical_registry"]["treatment"] == "historical_only"
    assert rules["historical_registry"]["rewrite"] is False
    assert registry["candidate_code_head"] != "HEAD"
    assert all(isinstance(claim["evidence"], list) for claim in registry["claims"])


def _valid_evidence(tmp_path: Path) -> dict:
    artifact = PACKAGE / "claim_rules.json"
    source_sha = "b2ddf11098ecd87b954bf97af26f8ecb8862b58a"
    import subprocess

    tree = subprocess.check_output(
        ["git", "rev-parse", f"{source_sha}^{{tree}}"], cwd=ROOT, text=True
    ).strip()
    empty_patch = hashlib.sha256(b"").hexdigest()
    config = ROOT / "uv.lock"
    return {
        "evidence_id": "evidence-1",
        "source_sha": source_sha,
        "source_tree": tree,
        "tested_sha": source_sha,
        "tested_tree": tree,
        "patch_sha256": empty_patch,
        "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "config_path": "uv.lock",
        "seed": 17,
        "environment": {"python": "3.12"},
        "artifact_path": artifact.relative_to(ROOT).as_posix(),
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "scenario": "fixture",
        "backend": "simulated-local",
        "evidence_classification": "SIMULATED",
    }


def test_evidence_validator_binds_sha_tree_artifact_and_claim_links(tmp_path):
    evidence = _valid_evidence(tmp_path)
    validate_evidence_record(evidence, ROOT)
    validate_claims(
        {"claims": [{"claim_id": "local-smoke", "evidence_classification": "SIMULATED", "evidence_ids": ["evidence-1"]}]},
        [evidence],
        ROOT,
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_sha", "f" * 40, "does not resolve"),
        ("source_tree", "0" * 64, "does not match"),
        ("artifact_sha256", "0" * 64, "does not match"),
        ("seed", None, "seed must be explicit"),
    ],
)
def test_evidence_validator_rejects_stale_or_incomplete_provenance(tmp_path, field, value, message):
    evidence = _valid_evidence(tmp_path)
    evidence[field] = value
    with pytest.raises(EvidenceError, match=message):
        validate_evidence_record(evidence, ROOT)


@pytest.mark.parametrize(
    ("backend", "classification", "extra", "message"),
    [
        ("mock-solana", "REAL_ON_CHAIN", {"network": "devnet", "receipt_id": "receipt-1"}, "mock and local EVM"),
        ("ganache-local", "REAL_ON_CHAIN", {"network": "localhost", "receipt_id": "receipt-1"}, "mock and local EVM"),
        ("base-sepolia", "REAL_ON_CHAIN", {"network": "base-sepolia", "receipt_id": "receipt-1"}, "verified receipt, network, and chain_id"),
        ("simulation", "FIELD_VALIDATED", {}, "field run, protocol, and reviewer"),
        ("simulation", "MEASURED_LAB", {}, "physical capture and reviewer"),
    ],
)
def test_evidence_validator_rejects_claim_promotions(tmp_path, backend, classification, extra, message):
    evidence = _valid_evidence(tmp_path)
    evidence.update({"backend": backend, "evidence_classification": classification, **extra})
    with pytest.raises(EvidenceError, match=message):
        validate_evidence_record(evidence, ROOT)


def test_claims_require_linked_evidence_of_the_same_classification(tmp_path):
    evidence = _valid_evidence(tmp_path)
    with pytest.raises(EvidenceError, match="promotes or mixes"):
        validate_claims(
            {"claims": [{"claim_id": "promoted", "evidence_classification": "FIELD_VALIDATED", "evidence_ids": ["evidence-1"]}]},
            [evidence],
            ROOT,
        )


def test_evidence_package_manifest_hash_mismatch_is_rejected(tmp_path):
    required_names = {
        "discovery.json", "ci_capability_matrix.json", "gate_architecture.json",
        "scientific_invariants.json", "claim_rules.json", "evidence_rules.json",
        "skip_classification.json", "test_costs.json", "local_ci_results.json",
        "workflow_security.json", "red_team_report.md", "limitations.json",
        "environment.json", "claims.json", "final_report.md",
        "evidence_records.json",
    }
    artifacts = {}
    for name in required_names:
        path = tmp_path / name
        content = '{"records":[]}\n' if name == "evidence_records.json" else '{"claims":[]}\n' if name == "claims.json" else "{}\n"
        path.write_text(content, encoding="utf-8")
        artifacts[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps({
        "schema_version": "riose.sc4-evidence-manifest/v1", "artifacts": artifacts
    }), encoding="utf-8")
    validate_package(tmp_path)
    (tmp_path / "claims.json").write_text("changed\n", encoding="utf-8")
    with pytest.raises(EvidenceError, match="manifest hash mismatch"):
        validate_package(tmp_path)


def test_heavy_interface_hashes_the_exact_repository_config_and_records_request_only(tmp_path):
    import argparse

    _heavy(argparse.Namespace(
        scenario="test-interface", seed=1042, duration=1.0, backend="simulated-local",
        artifact_directory=str(tmp_path), config_file="uv.lock",
    ))
    request = json.loads((tmp_path / "campaign-request.json").read_text(encoding="utf-8"))
    assert request["request_status"] == "REQUEST_ONLY"
    assert request["evidence_classification"] == "UNVERIFIED"
    assert request["config_provenance_status"] == "VERIFIED"
    assert request["config_path"] == "uv.lock"
    assert request["config_sha256"] == hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest()


def test_heavy_interface_rejects_configuration_paths_outside_the_repository(tmp_path):
    import argparse

    with pytest.raises(SystemExit, match="inside the repository"):
        _heavy(argparse.Namespace(
            scenario="test-interface", seed=1042, duration=1.0, backend="simulated-local",
            artifact_directory=str(tmp_path), config_file="../../outside.json",
        ))


def test_heavy_interface_refuses_public_chain_and_physical_backends(tmp_path):
    import argparse

    for backend in ("base-sepolia", "arbitrum-mainnet", "real-on-chain", "hardware-lab"):
        with pytest.raises(SystemExit, match="simulation backends only"):
            _heavy(argparse.Namespace(
                scenario="test-interface", seed=1042, duration=1.0, backend=backend,
                artifact_directory=str(tmp_path), config_file=None,
            ))


def test_skip_governance_reports_expected_optional_and_blocks_unexplained_skips():
    from types import SimpleNamespace

    governance = SkipGovernance(PACKAGE / "skip_classification.json")
    governance.pytest_runtest_logreport(SimpleNamespace(
        skipped=True,
        nodeid="hardware/mechanical/test_model.py::optional-cad",
        longrepr="CadQuery unavailable; dedicated CI CAD job installs requirements-cad.txt",
    ))
    governance.pytest_runtest_logreport(SimpleNamespace(
        skipped=True,
        nodeid="tests/test_critical_contract.py::hidden-skip",
        longrepr="external process unavailable",
    ))
    assert [row[1] for row in governance.skips] == ["EXPECTED_OPTIONAL", "UNEXPLAINED"]
    assert [row[1] for row in governance.blocking] == ["UNEXPLAINED"]


def test_skip_governance_blocks_module_level_collection_skips():
    from types import SimpleNamespace

    governance = SkipGovernance(PACKAGE / "skip_classification.json")
    governance.pytest_collectreport(SimpleNamespace(
        skipped=True,
        nodeid="tests/test_hidden_module.py",
        longrepr="No module named 'optional_dependency'",
    ))
    assert [row[1] for row in governance.skips] == ["UNEXPLAINED"]
    assert [row[1] for row in governance.blocking] == ["UNEXPLAINED"]
