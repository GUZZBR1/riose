import csv
import json
from pathlib import Path

import pytest

from hardware.antenna import SCENARIOS
from hardware.antenna import run as antenna_run
from hardware.antenna import openems_backend
from hardware.antenna.capabilities import detect_capabilities

SPEC = Path("hardware/spec.yaml")


def unavailable(monkeypatch):
    monkeypatch.setattr(openems_backend, "runtime_status", lambda: {
        "available": False, "bindings": {"openEMS": False, "CSXCAD": False},
        "executable": None, "solver_version": None, "reason": "test: solver unavailable"})


def test_missing_openems_writes_five_null_metric_scenarios(tmp_path, monkeypatch):
    unavailable(monkeypatch)
    result = antenna_run.run_experiments(SPEC, tmp_path)
    assert result["status"] == "NOT_AVAILABLE"
    assert result["result_class"] == "NO_SIMULATION_RESULT"
    assert [row["scenario"] for row in result["scenarios"]] == list(SCENARIOS)
    assert all(row["status"] in {"NOT_AVAILABLE", "INVALID_INPUT"} for row in result["scenarios"])
    assert result["scenarios"][0]["resonant_frequency_hz"] is None
    saved = json.loads((tmp_path / "antenna_experiments.json").read_text())
    assert saved["schema_version"] == antenna_run.SCHEMA_VERSION
    with (tmp_path / "antenna.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 5
    assert rows[0]["s11_min_db"] == ""
    assert len(saved["deltas_vs_free_space"]) == 5


def test_cli_returns_error_when_openems_is_unavailable(tmp_path, monkeypatch, capsys):
    unavailable(monkeypatch)
    status = antenna_run.main(["--spec", str(SPEC), "--output", str(tmp_path / "antenna")])
    assert status == 2
    assert json.loads(capsys.readouterr().out)["status"] == "NOT_AVAILABLE"


def test_spec_rejects_measured_status(tmp_path, monkeypatch):
    pytest.importorskip("yaml")
    import yaml
    spec_data = yaml.safe_load(SPEC.read_text())
    spec_data["antenna"]["center_frequency_hz"]["status"] = "MEASURED"
    spec = tmp_path / "spec.yaml"
    spec.write_text(yaml.safe_dump(spec_data))
    unavailable(monkeypatch)
    with pytest.raises(ValueError, match="cannot be MEASURED"):
        antenna_run.run_experiments(spec, tmp_path / "out")


def test_selecting_subset_never_marks_entire_issue_complete(tmp_path, monkeypatch):
    unavailable(monkeypatch)
    result = antenna_run.run_experiments(SPEC, tmp_path, [SCENARIOS[0]])
    assert result["status"] == "PARTIAL_OR_BLOCKED"
    assert result["deltas_vs_free_space"][0]["status"] == "NOT_COMPARABLE"


def test_native_runner_does_not_load_environment_adapter(tmp_path, monkeypatch):
    unavailable(monkeypatch)
    monkeypatch.setenv("RIOSE_OPENEMS_ADAPTER", "malicious_adapter_does_not_exist")
    result = antenna_run.run_experiments(SPEC, tmp_path, [SCENARIOS[0]])
    assert result["scenarios"][0]["status"] == "NOT_AVAILABLE"


def test_false_convergence_and_missing_mesh_fail_closed(tmp_path, monkeypatch):
    unavailable(monkeypatch)

    def forged(spec, spec_hash, geometry, output_dir, **kwargs):
        return {"status": "COMPLETED", "detail": "forged", "metrics": {
            "resonant_frequency_hz": 915e6, "s11_min_db": -20,
            "input_impedance_real_ohm": 50, "input_impedance_imag_ohm": 0,
            "vswr_min": 1.22, "efficiency_fraction": 0.8, "gain_dbi": 3,
        }, "evidence": {
            "spec_hash_sha256": spec_hash,
            "geometry_hash_sha256": geometry["geometry_hash_sha256"],
            "input_hash_sha256": openems_backend.expected_input_hash(spec_hash, geometry),
            "convergence": {"converged": "false"},
        }}

    monkeypatch.setattr(antenna_run, "simulate_scenario", forged)
    result = antenna_run.run_experiments(SPEC, tmp_path, [SCENARIOS[0]])
    assert result["scenarios"][0]["status"] == "FAILED"
    assert "does not prove boolean time-domain convergence" in result["scenarios"][0]["detail"]


def test_result_from_another_input_hash_is_rejected(tmp_path, monkeypatch):
    unavailable(monkeypatch)

    def stale(spec, spec_hash, geometry, output_dir, **kwargs):
        return {"status": "COMPLETED", "metrics": {}, "evidence": {
            "spec_hash_sha256": spec_hash,
            "geometry_hash_sha256": geometry["geometry_hash_sha256"],
            "input_hash_sha256": "0" * 64,
        }}

    monkeypatch.setattr(antenna_run, "simulate_scenario", stale)
    result = antenna_run.run_experiments(SPEC, tmp_path, [SCENARIOS[0]])
    assert result["scenarios"][0]["status"] == "FAILED"
    assert "hashes do not match" in result["scenarios"][0]["detail"]


def test_gpu_capabilities_report_is_optional_and_machine_readable():
    report = detect_capabilities()
    assert {"GPU_AVAILABLE", "GPU_TYPE", "CUDA_AVAILABLE", "SIONNA_AVAILABLE"} <= report.keys()
    assert report["experiment"] == "OPTIONAL_GPU_EXPERIMENT"
    assert report["result_status"] == "ENVIRONMENT_CAPABILITY_ONLY"


def test_openems_run_statistics_require_energy_decay_and_headroom():
    converged = openems_backend.parse_run_statistics([
        "time[s] timestep speed energy",
        "1e-9 100 12.0 1.0",
        "2e-9 200 12.0 1e-7",
    ], max_time_steps=300, end_criteria=1e-5)
    assert converged["converged"] is True
    assert converged["energy_residual_fraction"] == pytest.approx(1e-7)
    capped = openems_backend.parse_run_statistics(["2e-9 300 12.0 1e-8"],
                                                   max_time_steps=300, end_criteria=1e-5)
    assert capped["converged"] is False
    absent = openems_backend.parse_run_statistics(["no run data"])
    assert absent["status"] == "NON_CONVERGED"


def test_all_single_mesh_results_leave_refinement_gate_partial(tmp_path, monkeypatch):
    unavailable(monkeypatch)
    monkeypatch.setattr(antenna_run, "simulate_scenario", lambda *args, **kwargs: {
        "status": "COMPLETED", "metrics": {"resonant_frequency_hz": 915e6}, "evidence": {}})
    monkeypatch.setattr(antenna_run, "_validate_completion", lambda *args, **kwargs: None)
    result = antenna_run.run_experiments(SPEC, tmp_path)
    assert all(row["status"] == "COMPLETED" for row in result["scenarios"])
    assert result["status"] == "PARTIAL_OR_BLOCKED"
    assert result["mesh_refinement"]["status"] == "NOT_RUN"
    assert result["mesh_refinement"]["converged"] is False


def test_native_runner_rejects_hash_that_omits_solver_configuration(tmp_path):
    import yaml
    from hardware.antenna.geometry import build_geometry

    spec = yaml.safe_load(SPEC.read_text())
    geometry = build_geometry(spec, SCENARIOS[0])
    with pytest.raises(ValueError, match="does not match geometry and solver configuration"):
        openems_backend.simulate_scenario(spec, "a" * 64, geometry, tmp_path, input_hash="b" * 64)
