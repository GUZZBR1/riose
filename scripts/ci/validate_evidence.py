"""Fail-closed validation for machine-readable scientific evidence records."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


SHA256 = re.compile(r"^[0-9a-f]{64}$")
EVIDENCE_CLASSES = {
    "SIMULATED",
    "REAL_ON_CHAIN",
    "MEASURED_LAB",
    "FIELD_VALIDATED",
    "RESEARCH_SUPPORTED",
    "UNVERIFIED",
    "ASSUMED",
}


class EvidenceError(ValueError):
    pass


def validate_evidence_record(record: dict[str, Any], repository: Path) -> None:
    required = {
        "evidence_id",
        "source_sha",
        "source_tree",
        "tested_sha",
        "tested_tree",
        "patch_sha256",
        "config_sha256",
        "config_path",
        "seed",
        "environment",
        "artifact_path",
        "artifact_sha256",
        "scenario",
        "backend",
        "evidence_classification",
    }
    missing = sorted(required - record.keys())
    if missing:
        raise EvidenceError(f"evidence record missing fields: {', '.join(missing)}")
    if record["evidence_classification"] not in EVIDENCE_CLASSES:
        raise EvidenceError("unknown evidence classification")
    for key in ("source_tree", "tested_tree"):
        if not isinstance(record[key], str) or not re.fullmatch(r"[0-9a-f]{40,64}", record[key]):
            raise EvidenceError(f"{key} must be a Git tree object ID")
    for key in ("patch_sha256", "config_sha256", "artifact_sha256"):
        if not isinstance(record[key], str) or not SHA256.fullmatch(record[key]):
            raise EvidenceError(f"{key} must be a lowercase SHA-256 digest")
    source_sha = record["source_sha"]
    if not isinstance(source_sha, str) or not re.fullmatch(r"[0-9a-f]{40,64}", source_sha):
        raise EvidenceError("source_sha must be a Git object ID")
    try:
        actual_tree = subprocess.check_output(
            ["git", "rev-parse", f"{source_sha}^{{tree}}"], cwd=repository, text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError as exc:
        raise EvidenceError("source_sha does not resolve to a commit in this repository") from exc
    if actual_tree != record["source_tree"]:
        raise EvidenceError("source_tree does not match source_sha")
    tested_sha = record["tested_sha"]
    if not isinstance(tested_sha, str) or not re.fullmatch(r"[0-9a-f]{40,64}", tested_sha):
        raise EvidenceError("tested_sha must be a Git object ID")
    try:
        tested_tree = subprocess.check_output(
            ["git", "rev-parse", f"{tested_sha}^{{tree}}"], cwd=repository, text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        patch = subprocess.check_output(
            ["git", "diff", "--binary", source_sha, tested_sha], cwd=repository,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as exc:
        raise EvidenceError("tested_sha does not resolve in this repository") from exc
    if tested_tree != record["tested_tree"]:
        raise EvidenceError("tested_tree does not match tested_sha")
    if hashlib.sha256(patch).hexdigest() != record["patch_sha256"]:
        raise EvidenceError("patch_sha256 does not identify source_sha to tested_sha")

    artifact = (repository / record["artifact_path"]).resolve()
    if not artifact.is_relative_to(repository.resolve()) or not artifact.is_file():
        raise EvidenceError("artifact_path must name a repository-contained file")
    actual_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    if actual_hash != record["artifact_sha256"]:
        raise EvidenceError("artifact_sha256 does not match artifact bytes")
    if not record["scenario"] or not record["backend"] or not isinstance(record["environment"], dict):
        raise EvidenceError("scenario, backend, and environment must be explicit")
    if record["seed"] is None or isinstance(record["seed"], bool):
        raise EvidenceError("seed must be explicit; use a recorded integer")
    if not isinstance(record["seed"], (int, str)) or (isinstance(record["seed"], str) and record["seed"] != "not_applicable"):
        raise EvidenceError("seed must be an integer or explicitly marked not_applicable")
    config_path = record["config_path"]
    config = (repository / config_path).resolve()
    if not config.is_relative_to(repository.resolve()) or not config.is_file():
        raise EvidenceError("config_path must name a repository-contained file")
    if hashlib.sha256(config.read_bytes()).hexdigest() != record["config_sha256"]:
        raise EvidenceError("config_sha256 does not match config_path bytes")

    classification = record["evidence_classification"]
    backend = str(record["backend"]).lower()
    if classification == "REAL_ON_CHAIN":
        if any(marker in backend for marker in ("mock", "local", "ganache", "anvil")):
            raise EvidenceError("mock and local EVM evidence cannot be REAL_ON_CHAIN")
        if (
            not record.get("network")
            or not record.get("receipt_id")
            or type(record.get("chain_id")) is not int
            or record.get("receipt_verified") is not True
        ):
            raise EvidenceError("REAL_ON_CHAIN requires a verified receipt, network, and chain_id")
        receipt_path = record.get("receipt_artifact_path")
        receipt_hash = record.get("receipt_artifact_sha256")
        if not isinstance(receipt_path, str) or not isinstance(receipt_hash, str) or not SHA256.fullmatch(receipt_hash):
            raise EvidenceError("REAL_ON_CHAIN requires a hashed receipt artifact")
        receipt_artifact = (repository / receipt_path).resolve()
        if not receipt_artifact.is_relative_to(repository.resolve()) or not receipt_artifact.is_file():
            raise EvidenceError("receipt artifact must be a repository-contained file")
        if hashlib.sha256(receipt_artifact.read_bytes()).hexdigest() != receipt_hash:
            raise EvidenceError("receipt artifact hash does not match bytes")
    if classification == "MEASURED_LAB":
        provenance = record.get("measurement_provenance")
        if not isinstance(provenance, dict) or not all(
            provenance.get(key) for key in ("physical_source_ref", "capture_ref", "reviewer")
        ):
            raise EvidenceError("MEASURED_LAB requires physical capture and reviewer provenance")
    if classification == "FIELD_VALIDATED":
        provenance = record.get("field_provenance")
        if not isinstance(provenance, dict) or not all(
            provenance.get(key) for key in ("field_run_ref", "reviewer", "protocol_ref")
        ):
            raise EvidenceError("FIELD_VALIDATED requires field run, protocol, and reviewer provenance")
    if classification == "SIMULATED" and any(
        marker in backend for marker in ("mainnet", "testnet", "field", "hardware")
    ):
        raise EvidenceError("simulation classification conflicts with physical or chain backend")


def validate_claims(claims: dict[str, Any], evidence: list[dict[str, Any]], repository: Path) -> None:
    evidence_by_id = {item.get("evidence_id"): item for item in evidence}
    if len(evidence_by_id) != len(evidence) or None in evidence_by_id:
        raise EvidenceError("evidence IDs must be present and unique")
    for item in evidence:
        validate_evidence_record(item, repository)
    seen_claim_ids: set[str] = set()
    for claim in claims.get("claims", []):
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str) or claim_id in seen_claim_ids:
            raise EvidenceError("claim IDs must be present and unique")
        seen_claim_ids.add(claim_id)
        classification = claim.get("evidence_classification")
        if classification not in EVIDENCE_CLASSES:
            raise EvidenceError(f"claim {claim_id} has unknown evidence classification")
        refs = claim.get("evidence_ids")
        if not isinstance(refs, list) or not refs:
            raise EvidenceError(f"claim {claim_id} has no linked evidence")
        linked = [evidence_by_id.get(ref) for ref in refs]
        if any(item is None for item in linked):
            raise EvidenceError(f"claim {claim_id} references missing evidence")
        if any(item["evidence_classification"] != classification for item in linked):
            raise EvidenceError(f"claim {claim_id} promotes or mixes evidence classifications")


def validate_package(package_dir: Path) -> None:
    manifest_path = package_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "riose.sc4-evidence-manifest/v1":
        raise EvidenceError("unsupported evidence package manifest schema")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise EvidenceError("manifest must inventory package artifacts")
    for relpath, digest in artifacts.items():
        path = (package_dir / relpath).resolve()
        if not path.is_relative_to(package_dir.resolve()) or not path.is_file():
            raise EvidenceError(f"manifest artifact is missing or escapes package: {relpath}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise EvidenceError(f"manifest hash mismatch: {relpath}")
    required = {
        "discovery.json", "ci_capability_matrix.json", "gate_architecture.json",
        "scientific_invariants.json", "claim_rules.json", "evidence_rules.json",
        "skip_classification.json", "test_costs.json", "local_ci_results.json",
        "workflow_security.json", "red_team_report.md", "limitations.json",
        "environment.json", "claims.json", "evidence_records.json", "final_report.md",
    }
    if required - artifacts.keys():
        raise EvidenceError(f"evidence package inventory missing: {sorted(required - artifacts.keys())}")
    repository = package_dir.parent
    evidence = json.loads((package_dir / "evidence_records.json").read_text(encoding="utf-8"))
    claims = json.loads((package_dir / "claims.json").read_text(encoding="utf-8"))
    validate_claims(claims, evidence["records"], repository)
