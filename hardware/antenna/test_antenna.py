import csv
import hashlib
import json
from pathlib import Path

import pytest

from hardware.antenna import SCENARIOS
from hardware.antenna import run as antenna_run
from hardware.antenna import openems_backend
from hardware.antenna.capabilities import detect_capabilities

SPEC = Path("hardware/spec.yaml")


def refinement_metrics(**overrides):
    values = {
        "resonant_frequency_hz": 915e6, "s11_min_db": -10.0,
        "input_impedance_real_ohm": 50.0, "input_impedance_imag_ohm": 0.0,
        "vswr_min": 1.0, "efficiency_fraction": 0.8, "gain_dbi": 2.0,
        "directivity_dbi": 3.0, "s11_at_target_db": -9.0,
        "input_impedance_real_at_target_ohm": 51.0,
        "input_impedance_imag_at_target_ohm": 1.0, "vswr_at_target": 1.2,
    }
    return {**values, **overrides}


def refinement_mesh(factor):
    lines = {
        "x": [0.0, 1.0, 2.0] if factor == 1.5 else [0.0, 0.5, 1.0, 1.5, 2.0],
        "y": [0.0, 1.0],
        "z": [0.0, 1.0],
    }
    cell_counts = {axis: len(values) - 1 for axis, values in lines.items()}
    packed = json.dumps(lines, sort_keys=True, separators=(",", ":"))
    return {
        "lines": lines,
        "cell_counts": cell_counts,
        "cell_count_total": cell_counts["x"] * cell_counts["y"] * cell_counts["z"],
        "mesh_hash_sha256": hashlib.sha256(packed.encode()).hexdigest(),
    }


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


def test_all_scenarios_require_converged_coarse_and_fine_meshes(tmp_path, monkeypatch):
    unavailable(monkeypatch)
    calls = []

    def simulated(*args, **kwargs):
        factor = kwargs["mesh_resolution_factor"]
        calls.append(factor)
        return {"status": "COMPLETED", "metrics": refinement_metrics(),
                "evidence": {"mesh": refinement_mesh(factor)}}

    monkeypatch.setattr(antenna_run, "simulate_scenario", simulated)
    monkeypatch.setattr(antenna_run, "_validate_completion", lambda *args, **kwargs: None)
    result = antenna_run.run_experiments(SPEC, tmp_path)
    assert all(row["status"] == "COMPLETED" for row in result["scenarios"])
    assert calls == [1.5, 1.0] * len(SCENARIOS)
    assert result["status"] == "COMPLETED"
    assert result["mesh_refinement"]["status"] == "COMPLETED"
    assert result["mesh_refinement"]["converged"] is True
    assert all(row["mesh_refinement"]["converged"] for row in result["scenarios"])


def test_mesh_refinement_fails_closed_when_solver_metrics_do_not_agree():
    coarse = {"status": "COMPLETED", "metrics": refinement_metrics(
        resonant_frequency_hz=1_000_000_000, s11_min_db=-6.0),
        "evidence": {"mesh": refinement_mesh(1.5)}}
    fine = {"status": "COMPLETED", "metrics": refinement_metrics(),
            "evidence": {"mesh": refinement_mesh(1.0)}}
    result = antenna_run._mesh_refinement(coarse, fine)
    assert result["status"] == "NON_CONVERGED"
    assert result["converged"] is False
    assert result["resonant_frequency_relative_delta"] == pytest.approx(85_000_000 / 915_000_000)
    assert result["s11_min_delta_db"] == 4.0


def test_mesh_refinement_rejects_identical_grid_hashes():
    same_mesh = refinement_mesh(1.5)
    result = antenna_run._mesh_refinement(
        {"status": "COMPLETED", "metrics": refinement_metrics(), "evidence": {"mesh": same_mesh}},
        {"status": "COMPLETED", "metrics": refinement_metrics(), "evidence": {"mesh": same_mesh}},
    )
    assert result["status"] == "NON_CONVERGED"
    assert result["converged"] is False
    assert "same mesh hash" in result["detail"]


@pytest.mark.parametrize("field,delta", [
    ("gain_dbi", 0.6),
    ("efficiency_fraction", 0.06),
    ("input_impedance_real_ohm", 5.1),
    ("input_impedance_imag_ohm", 5.1),
])
def test_mesh_refinement_checks_gain_efficiency_and_impedance(field, delta):
    coarse_metrics = refinement_metrics()
    fine_metrics = refinement_metrics(**{field: coarse_metrics[field] + delta})
    result = antenna_run._mesh_refinement(
        {"status": "COMPLETED", "metrics": coarse_metrics,
         "evidence": {"mesh": refinement_mesh(1.5)}},
        {"status": "COMPLETED", "metrics": fine_metrics,
         "evidence": {"mesh": refinement_mesh(1.0)}},
    )
    assert result["converged"] is False
    assert field in result["failed_metrics"]


def test_mesh_refinement_rejects_hash_not_matching_serialized_grid():
    forged_mesh = refinement_mesh(1.5)
    forged_mesh["lines"]["x"][-1] = 3.0
    result = antenna_run._mesh_refinement(
        {"status": "COMPLETED", "metrics": refinement_metrics(), "evidence": {"mesh": refinement_mesh(1.5)}},
        {"status": "COMPLETED", "metrics": refinement_metrics(), "evidence": {"mesh": forged_mesh}},
    )
    assert result["status"] == "BLOCKED"
    assert "do not match" in result["detail"]


def test_solver_rf_extraction_failure_is_distinguished_from_invalid_input(tmp_path, monkeypatch):
    unavailable(monkeypatch)
    monkeypatch.setattr(antenna_run, "expected_input_hash", lambda *args, **kwargs: "c" * 64)
    monkeypatch.setattr(antenna_run, "simulate_scenario", lambda *args, **kwargs: {
        "status": "FAILED", "failure_class": "SOLVER_RESULT_INVALID",
        "detail": "radiated power exceeds accepted power", "metrics": None,
    })
    result = antenna_run._simulate_mesh({}, "a" * 64, {"geometry_hash_sha256": "b" * 64}, tmp_path, 1.0)
    assert result["status"] == "FAILED"
    assert result["failure_class"] == "SOLVER_RESULT_INVALID"
    assert result["status"] != "INVALID_INPUT"


def test_mesh_refinement_requires_both_native_solver_runs():
    result = antenna_run._mesh_refinement({"status": "NOT_AVAILABLE"}, {"status": "COMPLETED"})
    assert result["status"] == "BLOCKED"
    assert result["converged"] is False


def test_native_runner_rejects_hash_that_omits_solver_configuration(tmp_path):
    import yaml
    from hardware.antenna.geometry import build_geometry

    spec = yaml.safe_load(SPEC.read_text())
    geometry = build_geometry(spec, SCENARIOS[0])
    with pytest.raises(ValueError, match="does not match geometry and solver configuration"):
        openems_backend.simulate_scenario(spec, "a" * 64, geometry, tmp_path, input_hash="b" * 64)


def test_native_s11_clamps_only_tiny_passive_limit_roundoff():
    values, clamped = openems_backend._normalize_s11_magnitude_db([-3.0, 0.01])
    assert list(values) == [-3.0, 0.0]
    assert clamped
    with pytest.raises(ValueError, match="passive limit"):
        openems_backend._normalize_s11_magnitude_db([-3.0, 0.06])


def test_native_resonance_uses_nearest_input_reactance_zero_crossing():
    frequency, impedance = openems_backend._reactance_resonance(
        [800e6, 900e6, 1.0e9, 1.1e9],
        [20 - 10j, 30 + 10j, 40 - 20j, 50 + 20j],
        915e6,
    )
    assert frequency == pytest.approx(933_333_333.3333334)
    assert impedance == pytest.approx(33.333333333333336 + 0j)
    with pytest.raises(ValueError, match="does not cross zero"):
        openems_backend._reactance_resonance([800e6, 900e6], [1 + 2j, 2 + 3j], 850e6)
