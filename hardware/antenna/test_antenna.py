import csv
import json
import sys
import types

import pytest

from hardware.antenna import SCENARIOS
from hardware.antenna import run as antenna_run
from hardware.antenna.capabilities import detect_capabilities


def test_missing_openems_writes_five_null_metric_scenarios(tmp_path, monkeypatch):
    monkeypatch.setattr(antenna_run, "_openems_available", lambda: (False, None))
    out = tmp_path / "antenna"
    result = antenna_run.run_experiments(None, out)
    assert result["status"] == "NOT_AVAILABLE"
    assert result["result_class"] == "NO_SIMULATION_RESULT"
    assert [row["scenario"] for row in result["scenarios"]] == list(SCENARIOS)
    assert all(row["status"] == "NOT_AVAILABLE" for row in result["scenarios"])
    assert all(row["resonant_frequency_hz"] is None for row in result["scenarios"])
    saved = json.loads((out / "antenna_experiments.json").read_text())
    assert saved["schema_version"] == antenna_run.SCHEMA_VERSION
    with (out / "antenna.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 5
    assert rows[0]["s11_min_db"] == ""


def test_assumed_defaults_and_explicit_non_measurement(tmp_path, monkeypatch):
    monkeypatch.setattr(antenna_run, "_openems_available", lambda: (False, None))
    result = antenna_run.run_experiments(None, tmp_path)
    params = result["antenna_parameters"]
    assert params["center_frequency_hz"]["value"] == 915_000_000
    assert params["center_frequency_hz"]["status"] == "ASSUMED"
    assert params["element_length_mm"]["value"] == 82.0


def test_spec_rejects_measured_status(tmp_path, monkeypatch):
    pytest.importorskip("yaml")
    spec = tmp_path / "spec.yaml"
    spec.write_text("""antenna:\n  center_frequency_hz: {value: 915000000, unit: Hz, source: candidate, status: MEASURED}\n""")
    monkeypatch.setattr(antenna_run, "_openems_available", lambda: (False, None))
    with pytest.raises(ValueError, match="cannot be MEASURED"):
        antenna_run.run_experiments(spec, tmp_path / "out")


def test_spec_values_and_provenance_are_preserved(tmp_path, monkeypatch):
    pytest.importorskip("yaml")
    spec = tmp_path / "spec.yaml"
    spec.write_text("""antenna:\n  center_frequency_hz: {value: 868000000, unit: Hz, source: datasheet candidate, status: ASSUMED}\n  topology: {value: monopole, unit: text, source: design note, status: ASSUMED}\n  element_length_mm: {value: 86, unit: mm, source: initial geometry, status: ASSUMED}\n  feed_mm: {value: 1.5, unit: mm, source: initial feed, status: ASSUMED}\n  clearance_mm: {value: 3, unit: mm, source: placeholder, status: ASSUMED}\n""")
    monkeypatch.setattr(antenna_run, "_openems_available", lambda: (False, None))
    result = antenna_run.run_experiments(spec, tmp_path / "out", [SCENARIOS[0]])
    row = result["scenarios"][0]
    assert row["center_frequency_hz"] == 868000000
    assert row["center_frequency_status"] == "ASSUMED"
    assert row["topology"] == "monopole"
    assert result["spec_provenance"]["sha256"]


def test_gpu_capabilities_report_is_optional_and_machine_readable():
    report = detect_capabilities()
    assert {"GPU_AVAILABLE", "GPU_TYPE", "CUDA_AVAILABLE", "SIONNA_AVAILABLE"} <= report.keys()
    assert report["experiment"] == "OPTIONAL_GPU_EXPERIMENT"
    assert report["result_status"] == "ENVIRONMENT_CAPABILITY_ONLY"


def test_openems_adapter_cannot_mark_incomplete_metrics_as_completed(tmp_path, monkeypatch):
    monkeypatch.setattr(antenna_run, "_openems_available", lambda: (True, None))
    monkeypatch.setenv("RIOSE_OPENEMS_ADAPTER", "openems_test_adapter")
    adapter = types.SimpleNamespace(simulate=lambda **kwargs: {"status": "COMPLETED", "metrics": {}})
    monkeypatch.setitem(sys.modules, "openems_test_adapter", adapter)
    result = antenna_run.run_experiments(None, tmp_path, [SCENARIOS[0]])
    row = result["scenarios"][0]
    assert row["status"] == "FAILED"
    assert row["s11_min_db"] is None
    assert "incomplete openEMS result/provenance" in row["detail"]


def test_openems_adapter_requires_solver_and_mesh_evidence_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(antenna_run, "_openems_available", lambda: (True, None))
    monkeypatch.setenv("RIOSE_OPENEMS_ADAPTER", "openems_test_adapter")

    def simulate(**kwargs):
        output = __import__("pathlib").Path(kwargs["output_dir"])
        (output / "s11.csv").write_text("frequency_hz,s11_db\n915000000,-3\n")
        (output / "pattern.csv").write_text("theta,phi,gain_dbi\n0,0,1\n")
        return {
            "status": "COMPLETED", "metrics": {
                "resonant_frequency_hz": 915000000, "s11_min_db": -3,
                "input_impedance_real_ohm": 50, "input_impedance_imag_ohm": 0,
                "vswr_min": 1.2, "efficiency_fraction": 0.4, "gain_dbi": 1.0,
                "s11_curve_path": "s11.csv", "radiation_pattern_path": "pattern.csv",
            }, "evidence": {"solver_version": "test", "geometry_hash": "a" * 64,
                            "mesh": {"cells": 100}, "converged": True},
        }

    monkeypatch.setitem(sys.modules, "openems_test_adapter", types.SimpleNamespace(simulate=simulate))
    result = antenna_run.run_experiments(None, tmp_path, [SCENARIOS[0]])
    assert result["status"] == "COMPLETED"
    assert result["scenarios"][0]["solver_evidence"]["converged"] is True
    assert result["scenarios"][0]["s11_curve_path"] == "s11.csv"
