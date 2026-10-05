from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from riose.beta_final.campaign import (
    CampaignError,
    build_campaign_manifest,
    campaign_digest,
    validate_request_alignment,
    validate_run_evidence,
)
from riose.beta_final.contract import BetaContractError, load_scenario, validate_scenario
from riose.beta_final.report import ReportError, render_results, verify_manifest
from riose.simulation_contract.v1 import validate_request


ROOT = Path(__file__).parents[2]
SPEC = json.loads((ROOT / "docs/research/beta-final/campaign-spec.json").read_text())


@pytest.mark.parametrize("row", SPEC["scenarios"])
def test_scenario_contract_and_request_preserve_identity_time_and_config(row):
    scenario = load_scenario(ROOT / row["scenario"])
    request = json.loads((ROOT / row["request_template"]).read_text())
    validate_request(request)
    validate_request_alignment(scenario, request)

    changed = copy.deepcopy(request)
    changed["trajectory"]["samples"][0]["timestamp_s"] += 0.5
    with pytest.raises(CampaignError, match="identity/time/position"):
        validate_request_alignment(scenario, changed)

    changed = copy.deepcopy(request)
    changed["radio"]["frequency_hz"] += 1
    with pytest.raises(CampaignError, match="RF frequency"):
        validate_request_alignment(scenario, changed)


def test_scenario_rejects_identity_aliasing_duplicate_ids_and_bad_time():
    scenario = load_scenario(ROOT / SPEC["scenarios"][0]["scenario"])
    changed = copy.deepcopy(scenario)
    changed["trajectory"]["samples"][0]["animal_id"] = "different-animal"
    with pytest.raises(BetaContractError, match="does not resolve"):
        validate_scenario(changed)

    changed = copy.deepcopy(scenario)
    changed["identities"].append(copy.deepcopy(changed["identities"][0]))
    with pytest.raises(BetaContractError, match="duplicate"):
        validate_scenario(changed)

    changed = copy.deepcopy(scenario)
    changed["trajectory"]["samples"][1]["timestamp_s"] = 0
    with pytest.raises(BetaContractError, match="increase strictly"):
        validate_scenario(changed)


def _runtime_output(*, dirty: bool = False, evidence: str = "SIMULATED",
                    include_config_provenance: bool = True):
    solver = {"status": "VERIFIED", "requested": {"los": True},
              "effective": {"los": True}, "effective_sources": {"los": "REQUESTED"}}
    if include_config_provenance:
        solver.update(source_config_sha256="a" * 64, effective_config_sha256="b" * 64)
    return {
        "manifest": {
            "schema_version": "riose.simulation.run-manifest/v1",
            "execution_status": "COMPLETED",
            "riose": {"revision": "c" * 40, "dirty": dirty},
            "engine": {"actual_sha": "d" * 40, "dirty": False},
            "evidence_classification": evidence,
            "request_sha256": "e" * 64,
            "parameter_binding": {
                "radio_and_backend": {"status": "VERIFIED"}, "solver": solver,
                "trajectory": {"status": "VERIFIED"}, "network": {"status": "VERIFIED"},
            },
        },
        "result": {"status": "SIMULATED"},
    }


def test_run_evidence_requires_clean_pinned_revisions_simulation_and_effective_config():
    validate_run_evidence(_runtime_output(), expected_riose="c" * 40,
                          expected_frequencia="d" * 40)
    for output, message in (
        (_runtime_output(dirty=True), "clean campaign RIOSE"),
        (_runtime_output(evidence="VALIDATED"), "remain SIMULATED"),
        (_runtime_output(include_config_provenance=False), "complete effective solver"),
    ):
        with pytest.raises(CampaignError, match=message):
            validate_run_evidence(output, expected_riose="c" * 40,
                                  expected_frequencia="d" * 40)


def test_campaign_manifest_hash_failure_accounting_and_report_generation(tmp_path):
    scenario_path = ROOT / SPEC["scenarios"][0]["scenario"]
    scenario = load_scenario(scenario_path)
    runs = [
        {"run_key": "baseline-11", "scenario_id": scenario["scenario_id"], "seed": 11,
         "status": "COMPLETED", "classification": "SIMULATED",
         "request_sha256": "a" * 64, "output_sha256": "b" * 64,
         "reproducibility_sha256": "f" * 64, "workspace": str(tmp_path / "run-1")},
        {"run_key": "baseline-11-repeat", "scenario_id": scenario["scenario_id"], "seed": 11,
         "status": "COMPLETED", "classification": "SIMULATED",
         "request_sha256": "a" * 64, "output_sha256": "b" * 64,
         "reproducibility_sha256": "f" * 64, "workspace": str(tmp_path / "run-2")},
        {"run_key": "baseline-29", "scenario_id": scenario["scenario_id"], "seed": 29,
         "status": "FAILED", "classification": "SIMULATED", "error": "simulator failed"},
    ]
    campaign = {**SPEC, "reproducibility_repeats": [
        {"scenario_id": scenario["scenario_id"], "seed": 11, "copies": 2}]}
    manifest = build_campaign_manifest(
        campaign=campaign, scenario_files=[(scenario_path, scenario)], runs=runs,
        riose={"revision": "c" * 40, "dirty": False},
        frequencia={"revision": "d" * 40, "dirty": False, "capabilities": {"ns3": "AVAILABLE"}},
    )
    verify_manifest(manifest)
    assert manifest["denominator_policy"] == {
        "scheduled_runs": 3, "successful_runs": 2, "failed_runs": 1,
        "failures_are_retained": True,
    }
    assert manifest["reproducibility"][0]["status"] == "PASS"
    report = render_results(manifest)
    assert "2 / 3 / 1" in report
    assert "same normalized simulator result digest: `True`" in report
    assert "simulator failed" in report
    assert campaign_digest(SPEC) == campaign_digest(copy.deepcopy(SPEC))

    changed = copy.deepcopy(manifest)
    changed["classification"] = "VALIDATED"
    with pytest.raises(ReportError, match="hash"):
        verify_manifest(changed)


def test_same_seed_reproduction_fails_on_changed_output_hash():
    scenario_path = ROOT / SPEC["scenarios"][0]["scenario"]
    scenario = load_scenario(scenario_path)
    campaign = {**SPEC, "reproducibility_repeats": [
        {"scenario_id": scenario["scenario_id"], "seed": 11, "copies": 2}]}
    runs = [{"run_key": f"run-{index}", "scenario_id": scenario["scenario_id"], "seed": 11,
             "status": "COMPLETED", "classification": "SIMULATED",
             "request_sha256": "a" * 64, "output_sha256": token * 64,
             "reproducibility_sha256": token * 64}
            for index, token in enumerate(("b", "c"))]
    manifest = build_campaign_manifest(campaign=campaign,
        scenario_files=[(scenario_path, scenario)], runs=runs,
        riose={"revision": "c" * 40, "dirty": False},
        frequencia={"revision": "d" * 40, "dirty": False, "capabilities": {}})
    assert manifest["reproducibility"][0]["same_request"] is True
    assert manifest["reproducibility"][0]["same_output"] is False
    assert manifest["reproducibility"][0]["status"] == "PARTIAL"


def test_repeat_with_missing_output_digest_cannot_pass():
    scenario_path = ROOT / SPEC["scenarios"][0]["scenario"]
    scenario = load_scenario(scenario_path)
    campaign = {**SPEC, "reproducibility_repeats": [
        {"scenario_id": scenario["scenario_id"], "seed": 11, "copies": 2}]}
    runs = [{"run_key": f"run-{index}", "scenario_id": scenario["scenario_id"], "seed": 11,
             "status": "COMPLETED", "classification": "SIMULATED",
             "request_sha256": "a" * 64, "output_sha256": None,
             "reproducibility_sha256": None}
            for index in (1, 2)]
    manifest = build_campaign_manifest(campaign=campaign,
        scenario_files=[(scenario_path, scenario)], runs=runs,
        riose={"revision": "c" * 40, "dirty": False},
        frequencia={"revision": "d" * 40, "dirty": False, "capabilities": {}})
    assert manifest["reproducibility"][0]["same_output"] is False
    assert manifest["reproducibility"][0]["status"] == "PARTIAL"
