from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from riose.simulation_contract.v1 import content_hash
from riose.simulation_evidence import EvidenceError, build_package, verify_package
from riose.simulation_evidence.pipeline import _validate_location_quality, _validate_temporal_binding
from riose.simulation_adapter import convert_result
from riose.simulation_lab.runner import FREQUENCIA_URL, run as run_simulation


FIXTURES = Path(__file__).parents[2] / "src/riose/simulation_contract/fixtures"
PLOT = Path(__file__).parents[2] / "src/riose/simulation_evidence/fixtures/link-overview.svg"
CAMPAIGN_FIXTURE = Path(__file__).parents[2] / "examples/simulation-evidence-campaign"


def campaign(tmp_path: Path) -> Path:
    root = tmp_path / "campaign"
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "request-v1.json", root / "request.json")
    shutil.copy(FIXTURES / "result-v1.json", root / "result.json")
    shutil.copy(PLOT, root / "link-overview.svg")
    return root


def build(root: Path, out: Path, **kwargs):
    return build_package(root, out, selected_artifacts=["link-overview.svg"], **kwargs)


def test_build_and_verify_fixture_are_simulated_and_auditable(tmp_path):
    out = tmp_path / "evidence"
    manifest = build(campaign(tmp_path), out)
    assert verify_package(out) == {"valid": True, "evidence_status": "SIMULATED", "artifacts": 4,
                                   "hashes": "PASS", "schema": "PASS", "errors": []}
    assert manifest["request_hash"] == content_hash(json.loads((out / "request.json").read_text()))
    assert manifest["run_id"] is None
    assert manifest["physical_validation_status"] == "NOT_VALIDATED"
    assert manifest["provenance"]["source_result_sha256"] == content_hash(
        json.loads((FIXTURES / "result-v1.json").read_text()))
    assert (out / "report.md").is_file() and (out / "plots/link-overview.svg").is_file()
    assert "NOT AVAILABLE" in (out / "report.md").read_text()


def test_committed_campaign_fixture_can_be_built(tmp_path):
    out = tmp_path / "package"
    build_package(CAMPAIGN_FIXTURE, out, selected_artifacts=["link-overview.svg"])
    assert verify_package(out)["valid"]


def test_summary_metrics_have_denominators_and_unavailable_values_are_null(tmp_path):
    out = tmp_path / "evidence"
    build(campaign(tmp_path), out)
    summary = json.loads((out / "summary.json").read_text())
    assert summary["network"]["pdr"] == {"value": None, "unit": "ratio", "status": "NOT_AVAILABLE", "numerator": None, "denominator": None}
    assert summary["localization"]["rmse"]["value"] is None
    assert summary["localization"]["rmse"]["status"] == "NOT_AVAILABLE"
    assert summary["rf"]["received_power_dbm"]["mean"]["value"] == -74.2


def test_quality_status_is_recomputed_from_declared_bounds_and_raw_estimate():
    request = json.loads((Path(__file__).parents[2] / "examples/farm_rf_v1.json").read_text())
    result = {"locations": [{"position_m": [120.0, 200.0], "solver_status": "CONVERGED",
        "quality_status": "ACCEPTED", "quality_reason": "WITHIN_DECLARED_OPERATIONAL_BOUNDS",
        "quality_bounds_m": request["operational_bounds_m"]}]}
    _validate_location_quality(request, result)
    assert result["locations"][0]["position_m"] == [120.0, 200.0]
    result["locations"][0]["quality_status"] = "ACCEPTED"
    result["locations"][0]["position_m"] = [1248.8, -4000.9]
    with pytest.raises(EvidenceError, match="does not match request-declared bounds"):
        _validate_location_quality(request, result)


def test_temporal_binding_rejects_wrong_run_request_effective_values_or_artifact():
    request = json.loads((Path(__file__).parents[2] / "examples/farm_rf_v1.json").read_text())
    temporal = request["solver"]["parameters"]["temporal"]
    binding = {"schema_version": "riose.simulation.temporal-binding/v1", "run_id": "run-1",
        "request_sha256": "a" * 64, "input_sha256": "b" * 64,
        "runtime_artifact_sha256": "c" * 64, "requested": temporal, "forwarded": temporal,
        "effective": {"clock_seed": request["seed"], **{key: temporal[key] for key in (
            "detector", "clocks", "correlated_jitter_std_s", "timestamp_error_std_s",
            "noise_figure_db", "snr_threshold_db", "detection_margin_db", "max_iterations")}},
        "effective_defaults": {"phy.preamble_symbols": {"requested": None, "effective": 8,
            "status": "VERIFIED"}, "sweep.noise_density_dbm_hz": {"requested": None,
            "effective": -174.0, "status": "VERIFIED"}},
        "observed_detector_modes": [temporal["detector"]["mode"]], "status": "VERIFIED"}
    artifacts = {"inputs.json": "b" * 64, "pipeline.json": "c" * 64}
    _validate_temporal_binding(binding, temporal, request["seed"], "a" * 64, "run-1", artifacts)
    for key, value in (("run_id", "run-2"), ("request_sha256", "d" * 64),
                       ("input_sha256", "d" * 64), ("runtime_artifact_sha256", "d" * 64)):
        changed = dict(binding, **{key: value})
        with pytest.raises(EvidenceError):
            _validate_temporal_binding(changed, temporal, request["seed"], "a" * 64, "run-1", artifacts)
    changed = json.loads(json.dumps(binding))
    changed["effective"]["max_iterations"] = 999
    with pytest.raises(EvidenceError, match="run-level evidence"):
        _validate_temporal_binding(changed, temporal, request["seed"], "a" * 64, "run-1", artifacts)


@pytest.mark.parametrize("changed", ["request", "summary", "plot", "report", "manifest"])
def test_tampering_is_detected(tmp_path, changed):
    out = tmp_path / "evidence"
    build(campaign(tmp_path), out)
    path = out / ("plots/link-overview.svg" if changed == "plot" else f"{changed}.json" if changed in {"request", "summary", "manifest"} else "report.md")
    path.write_text(path.read_text() + "tampered", encoding="utf-8")
    assert not verify_package(out)["valid"]


def test_missing_and_unlisted_files_fail_closed(tmp_path):
    out = tmp_path / "evidence"
    build(campaign(tmp_path), out)
    (out / "request.json").unlink()
    assert not verify_package(out)["valid"]
    out2 = tmp_path / "evidence2"
    out2_campaign = tmp_path / "campaign-two"
    out2_campaign.mkdir()
    shutil.copy(FIXTURES / "request-v1.json", out2_campaign / "request.json")
    shutil.copy(FIXTURES / "result-v1.json", out2_campaign / "result.json")
    shutil.copy(PLOT, out2_campaign / "link-overview.svg")
    build(out2_campaign, out2)
    (out2 / "extra.bin").write_bytes(b"raw")
    assert not verify_package(out2)["valid"]


@pytest.mark.parametrize("name", ["../outside.txt", "/tmp/outside.txt", "C:/secret.txt", ".env", "credentials.json"])
def test_unsafe_or_sensitive_artifacts_are_rejected(tmp_path, name):
    with pytest.raises(EvidenceError):
        build_package(campaign(tmp_path), tmp_path / "evidence", selected_artifacts=[name])


def test_symlink_escape_and_size_gate_are_rejected(tmp_path):
    root = campaign(tmp_path)
    outside = tmp_path / "outside.svg"
    outside.write_text("private")
    (root / "escape.svg").symlink_to(outside)
    with pytest.raises(EvidenceError):
        build_package(root, tmp_path / "evidence", selected_artifacts=["escape.svg"])
    with pytest.raises(EvidenceError):
        build_package(root, tmp_path / "too-large", selected_artifacts=["link-overview.svg"], max_package_bytes=8)


def test_validated_promotion_and_backend_mismatch_are_rejected(tmp_path):
    root = campaign(tmp_path)
    result_path = root / "result.json"
    result = json.loads(result_path.read_text())
    result["status"] = "VALIDATED"
    result_path.write_text(json.dumps(result))
    with pytest.raises(EvidenceError):
        build(root, tmp_path / "invalid")
    result["status"] = "SIMULATED"
    result["backend"] = "other-backend"
    result_path.write_text(json.dumps(result))
    with pytest.raises(EvidenceError):
        build(root, tmp_path / "mismatch")


def test_failure_campaign_is_packaged_without_success_metrics(tmp_path):
    root = campaign(tmp_path)
    (root / "result.json").unlink()
    (root / "failure.json").write_text(json.dumps({
        "status": "FAILED", "error_category": "SOLVER_ERROR", "message": "fixture failure",
        "completed_at": "2026-10-03T00:00:01Z", "warnings": [], "limitations": ["Fixture failure only."],
    }))
    out = tmp_path / "failed-evidence"
    build(root, out)
    assert verify_package(out)["valid"]
    summary = json.loads((out / "summary.json").read_text())
    assert summary["status"] == "FAILED"
    assert summary["network"]["pdr"]["value"] is None
    assert summary["network"]["pdr"]["status"] == "NOT_RUN"


def test_failure_log_with_local_path_is_rejected(tmp_path):
    root = campaign(tmp_path)
    (root / "result.json").unlink()
    (root / "failure.json").write_text(json.dumps({
        "status": "FAILED", "error_category": "SOLVER_ERROR", "message": "failed at /home/user/private.log",
        "completed_at": "2026-10-03T00:00:01Z", "warnings": [], "limitations": [],
    }))
    with pytest.raises(EvidenceError):
        build(root, tmp_path / "failed-evidence")


def test_deterministic_summary_and_report_and_existing_destination_is_preserved(tmp_path):
    root = campaign(tmp_path)
    first, second = tmp_path / "first", tmp_path / "second"
    build(root, first)
    build(root, second)
    for name in ("request.json", "summary.json", "report.md", "plots/link-overview.svg"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    with pytest.raises(EvidenceError):
        build(root, first)
    assert verify_package(first)["valid"]


def test_request_hash_mismatch_rejected(tmp_path):
    root = campaign(tmp_path)
    result_path = root / "result.json"
    result = json.loads(result_path.read_text())
    result["provenance"]["request_sha256"] = "0" * 64
    result_path.write_text(json.dumps(result))
    with pytest.raises(EvidenceError):
        build(root, tmp_path / "invalid")


def test_duplicate_selection_and_partial_build_leave_no_package(tmp_path):
    root = campaign(tmp_path)
    with pytest.raises(EvidenceError):
        build_package(root, tmp_path / "duplicate", selected_artifacts=["link-overview.svg", "link-overview.svg"])
    invalid = tmp_path / "partial"
    with pytest.raises(EvidenceError):
        build_package(root, invalid, selected_artifacts=["../escape.svg"])
    assert not invalid.exists()
    with pytest.raises(EvidenceError):
        build_package(root, root / "nested-package", selected_artifacts=["link-overview.svg"])


def test_verifier_rejects_unknown_schema_size_and_configuration_mismatch(tmp_path):
    out = tmp_path / "evidence"
    build(campaign(tmp_path), out)
    manifest_path = out / "manifest.json"
    original = json.loads(manifest_path.read_text())

    malformed = dict(original, schema_version="riose.simulation.evidence-manifest/v999")
    manifest_path.write_text(json.dumps(malformed))
    assert not verify_package(out)["valid"]

    malformed = dict(original)
    malformed["outputs"] = [dict(item) for item in original["outputs"]]
    malformed["outputs"][0]["size_bytes"] += 1
    manifest_path.write_text(json.dumps(malformed))
    assert not verify_package(out)["valid"]

    malformed = dict(original)
    malformed["configuration"] = dict(original["configuration"], frequency_hz_requested=433_000_000)
    manifest_path.write_text(json.dumps(malformed))
    assert not verify_package(out)["valid"]

    manifest_path.write_text("[]")
    assert not verify_package(out)["valid"]


def test_verifier_rejects_changed_report_manifest_backend_and_package_symlinks(tmp_path):
    out = tmp_path / "evidence"
    build(campaign(tmp_path), out)
    (out / "report.md").write_text((out / "report.md").read_text() + "\nInjected report text")
    assert not verify_package(out)["valid"]

    clean = tmp_path / "clean-evidence"
    build(campaign(tmp_path), clean)
    manifest_path = clean / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["engine"]["backend_used"] = "forged-backend"
    manifest_path.write_text(json.dumps(manifest))
    assert not verify_package(clean)["valid"]

    clean2 = tmp_path / "clean-evidence-two"
    build(campaign(tmp_path), clean2)
    (clean2 / "plots/escape.svg").symlink_to(tmp_path / "outside.svg")
    assert not verify_package(clean2)["valid"]


def test_request_rejects_machine_paths_and_credentials(tmp_path):
    root = campaign(tmp_path)
    request_path = root / "request.json"
    request = json.loads(request_path.read_text())
    request["trajectory"] = {"samples": None, "reference": "/home/alice/private/track.csv"}
    request_path.write_text(json.dumps(request))
    with pytest.raises(EvidenceError):
        build(root, tmp_path / "local-path")

    request["trajectory"] = {"samples": None, "reference": "trajectory-abc"}
    request["solver"]["parameters"]["api_token"] = "not-a-real-secret"
    request_path.write_text(json.dumps(request))
    with pytest.raises(EvidenceError):
        build(root, tmp_path / "credential")


def test_runner_workspace_layout_is_packaged_without_leaking_runner_paths(tmp_path):
    root = tmp_path / "run-workspace"
    (root / "request").mkdir(parents=True)
    (root / "result").mkdir()
    request = json.loads((FIXTURES / "request-v1.json").read_text())
    result = json.loads((FIXTURES / "result-v1.json").read_text())
    (root / "request/request.json").write_text(json.dumps(request))
    (root / "result/result.json").write_text(json.dumps(result))
    shutil.copy(PLOT, root / "selected.svg")
    (root / "manifest.json").write_text(json.dumps({
        "schema_version": "riose.simulation.run-manifest/v1",
        "campaign_id": request["campaign_id"],
        "riose": {"revision": "a" * 40, "dirty": False},
        "engine": {"repository_url": "GUZZBR1/frequencia", "path": "/private/engine/path",
                   "expected_sha": "b" * 40, "actual_sha": "b" * 40, "dirty": False,
                   "capabilities": {"analytic": "AVAILABLE", "sionna_rt": "UNAVAILABLE", "ns3": "UNAVAILABLE"}},
        "backend_requested": request["backend"], "backend_used": result["backend"],
        "evidence_classification": "SIMULATED", "request_sha256": content_hash(request),
        "started_at": "2026-10-03T00:00:00Z", "finished_at": "2026-10-03T00:00:01Z",
        "duration_seconds": 1.0, "exit_code": 0, "dry_run": False,
        "config_sha256": "c" * 64, "trajectory_sha256": "d" * 64,
        "command": ["/private/engine/path/runner.py"], "working_directory": "/private/engine/path",
    }))
    output = tmp_path / "evidence"
    manifest = build_package(root, output, selected_artifacts=["selected.svg"])
    assert verify_package(output)["valid"]
    assert manifest["provenance"]["riose"]["sha"] == "a" * 40
    assert manifest["provenance"]["frequencia"]["sha"] == "b" * 40
    assert manifest["execution"]["runtime_seconds"] == 1.0
    assert manifest["configuration"]["input_hashes"] == ["c" * 64, "d" * 64]
    assert "/private/engine/path" not in (output / "manifest.json").read_text()


def test_run_manifest_mismatch_and_artifactless_build(tmp_path):
    root = tmp_path / "run-workspace"
    root.mkdir()
    request = json.loads((FIXTURES / "request-v1.json").read_text())
    result = json.loads((FIXTURES / "result-v1.json").read_text())
    (root / "request.json").write_text(json.dumps(request))
    (root / "result.json").write_text(json.dumps(result))
    run_manifest = {"schema_version": "riose.simulation.run-manifest/v1", "campaign_id": request["campaign_id"],
                    "request_sha256": "0" * 64, "backend_requested": request["backend"],
                    "backend_used": result["backend"], "evidence_classification": "SIMULATED", "exit_code": 0}
    (root / "manifest.json").write_text(json.dumps(run_manifest))
    with pytest.raises(EvidenceError):
        build_package(root, tmp_path / "mismatch")

    (root / "manifest.json").unlink()
    output = tmp_path / "without-plots"
    build_package(root, output)
    assert verify_package(output)["valid"]
    assert not (output / "plots").exists()


def test_runner_adapter_evidence_verifier_flow(tmp_path):
    engine_root = tmp_path / "frequencia engine"
    entrypoint = engine_root / "experiments/farm_rf/run_experiment.py"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("""import json, pathlib, sys
output = pathlib.Path(sys.argv[sys.argv.index('--output-dir') + 1])
output.mkdir(parents=True, exist_ok=True)
(output / 'summary.json').write_text(json.dumps({
  'classification': 'SIMULAÇÃO',
  'backend': 'analytic_free_space_plus_flat_ground_reflection'
}))
print('fixture engine succeeded')
""", encoding="utf-8")
    import subprocess
    subprocess.run(["git", "init", "-q", str(engine_root)], check=True)
    subprocess.run(["git", "-C", str(engine_root), "config", "user.name", "RIOSE test"], check=True)
    subprocess.run(["git", "-C", str(engine_root), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(engine_root), "remote", "add", "origin", FREQUENCIA_URL], check=True)
    subprocess.run(["git", "-C", str(engine_root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(engine_root), "commit", "-qm", "Add analytic fixture"], check=True)
    engine_sha = subprocess.run(["git", "-C", str(engine_root), "rev-parse", "HEAD"], check=True,
                                capture_output=True, text=True).stdout.strip()

    request = json.loads((FIXTURES / "request-v1.json").read_text())
    request["backend"] = "analytic"
    request["provenance"]["frequencia_revision"] = engine_sha
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    run = run_simulation(request_path, repo=engine_root, expected_sha=engine_sha,
                         output_root=tmp_path / "runs")
    result_path = Path(run["workspace"]) / "result/result.json"
    result = json.loads(result_path.read_text())
    converted = convert_result(result, run_manifest=run["manifest"])
    assert converted.report.input_observations == 0
    package = tmp_path / "package"
    build_package(run["workspace"], package)
    assert verify_package(package)["valid"]
    assert json.loads((package / "summary.json").read_text())["rf"]["links"]["value"] == 0
    packaged_config = json.loads((package / "manifest.json").read_text())["configuration"]
    assert packaged_config["seed_requested"] == request["seed"]
    assert packaged_config["seed_used"] is None
    assert packaged_config["parameter_binding"]["radio_and_backend"]["status"] == "REQUEST_SPECIFIC_PARAMETERS_UNSUPPORTED"
