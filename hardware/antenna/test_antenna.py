import csv
import json

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
