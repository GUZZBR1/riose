"""Sensitivity artifacts must be requested, fresh and complete before READY."""

import copy
import csv
import json
from pathlib import Path

import pytest
import yaml

from riose.products.ear_tag.digital_twin import runner
from riose.products.ear_tag.digital_twin.reporting import _report
from riose.products.ear_tag.digital_twin.spec import evaluate_gate, load_spec, validate_spec


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def sweep_inputs():
    spec, _ = load_spec(ROOT / "hardware/spec.yaml")
    axes = (
        ("material", "ANTENNA_WITH_ENCLOSURE", "materials.enclosure_relative_permittivity", 3.5, "ratio"),
        ("thickness", "ANTENNA_WITH_ENCLOSURE", "mechanical.enclosure.wall_thickness_mm", 1.2, "mm"),
        ("gap", "ANTENNA_WITH_PCB", "antenna.feed_gap_mm", 0.5, "mm"),
        ("animal_orientation", "ANTENNA_NEAR_ANIMAL_APPROXIMATION", "antenna.animal_orientation_deg", 90, "deg"),
    )
    spec["antenna"]["sweeps"] = {}
    rows = []
    for name, scenario, parameter, value, unit in axes:
        spec["antenna"]["sweeps"][name] = {
            "scenario": scenario, "parameter": parameter,
            "values": [{"value": value, "unit": unit, "source": "test assumed sensitivity", "status": "ASSUMED"}],
        }
        rows.append({"case_id": name, "scenario": scenario, "parameter": parameter,
                     "value": value, "unit": unit, "input_hash_sha256": "a" * 64,
                     "status": "COMPLETED"})
    return spec, {"status": "COMPLETED", "scenarios": [], "sweeps": rows}


def write_sweeps(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_central_spec_accepts_orientation_degrees_and_meander_counts(sweep_inputs):
    spec, _ = sweep_inputs
    spec["antenna"]["meander_turns"] = {
        "value": 4, "unit": "count", "source": "ASSUMED antenna geometry", "status": "ASSUMED",
    }
    validate_spec(spec)


@pytest.mark.parametrize("supported", [True, False])
def test_runner_requests_supported_sweeps_and_clears_old_artifacts(tmp_path, monkeypatch, sweep_inputs, supported):
    from hardware.antenna import sionna_experiment

    spec, manifest = sweep_inputs
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec))
    (tmp_path / "docs").mkdir()
    output = tmp_path / "output"
    sweep_csv = output / "antenna" / "sweeps.csv"
    write_sweeps(sweep_csv, manifest["sweeps"])
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "FAULT_SCENARIOS", [])
    monkeypatch.setattr(runner, "preflight", lambda: {
        "platform": "test", "commands": {}, "modules": {}, "gpu": {},
    })
    monkeypatch.setattr(sionna_experiment, "run_experiment", lambda *args, **kwargs: {
        "status": "NOT_AVAILABLE", "scenarios": [],
    })
    calls = []

    def run_command(name, command, cwd, **kwargs):
        calls.append((name, command))
        if name == "antenna_capabilities":
            return {"status": "PASSED", "stdout": "usage: run [--sweeps] --sweeps" if supported else "usage: run --spec --output"}
        if name == "antenna":
            assert not sweep_csv.exists()
            result = copy.deepcopy(manifest)
            if supported:
                assert "--sweeps" in command
                write_sweeps(sweep_csv, result["sweeps"])
            else:
                assert "--sweeps" not in command
                del result["sweeps"]
            (sweep_csv.parent / "antenna_experiments.json").write_text(json.dumps(result))
            return {"status": "PASSED", "return_code": 0}
        return {"status": "NOT_AVAILABLE", "detail": "unrelated tool omitted in integration test"}

    monkeypatch.setattr(runner, "_run_command", run_command)
    summary = runner.run_twin(spec_path, output)
    assert any(name == "antenna" for name, _ in calls)
    sweep_stage = summary["stages"]["antenna_sweeps"]
    assert sweep_stage["status"] == ("COMPLETED" if supported else "NOT_AVAILABLE")
    assert summary["outputs"]["antenna_sweeps_csv"] == (str(sweep_csv) if supported else None)
    assert summary["stages"]["gpu_optional"]["required"] is False
    report = (tmp_path / "docs" / "mvp2-digital-twin-report.md").read_text()
    assert "sweeps.csv" in report
    expected_report = "4/4 casos configurados concluídos" if supported else "NOT_AVAILABLE"
    assert expected_report in report
    if not supported:
        assert not sweep_csv.exists()
        assert "antenna_sweeps: NOT_AVAILABLE" in summary["gate"]["blockers"]


@pytest.mark.parametrize("status, expected", [
    ("FAILED", "PARTIAL_OR_BLOCKED"), ("NON_CONVERGED", "PARTIAL_OR_BLOCKED"),
    ("INVALID_INPUT", "PARTIAL_OR_BLOCKED"), ("NOT_AVAILABLE", "NOT_AVAILABLE"),
    ("COMPLETED", "COMPLETED"),
])
def test_sweep_statuses_control_ready_without_optional_sionna(tmp_path, sweep_inputs, status, expected):
    spec, manifest = sweep_inputs
    for row in manifest["sweeps"]:
        row["status"] = status
    csv_path = tmp_path / "sweeps.csv"
    write_sweeps(csv_path, manifest["sweeps"])
    result = runner._antenna_sweep_result(spec, manifest, csv_path, supported=True)
    assert result["status"] == expected
    assert result["status_counts"] == {status: 4}
    spec["gate"]["approval"] = {key: "APPROVED" for key in spec["gate"]["approval"]}
    stages = {"antenna": {"status": "COMPLETED"}, "antenna_sweeps": result,
              "gpu_optional": {"status": "NOT_AVAILABLE", "required": False}}
    gate = evaluate_gate(spec, stages)
    assert gate["state"] == ("READY_FOR_PHYSICAL_PROTOTYPE" if status == "COMPLETED"
                             else "NOT_READY_FOR_PHYSICAL_PROTOTYPE")


@pytest.mark.parametrize("corruption", ["missing_manifest", "empty_manifest", "missing_case", "duplicate_case",
                                        "wrong_value", "missing_csv", "csv_status_mismatch", "csv_missing_case",
                                        "invalid_hash", "missing_axis"])
def test_incomplete_sweep_evidence_fails_closed(tmp_path, sweep_inputs, corruption):
    spec, manifest = sweep_inputs
    csv_path = tmp_path / "sweeps.csv"
    if corruption == "missing_manifest":
        del manifest["sweeps"]
    elif corruption == "empty_manifest":
        manifest["sweeps"] = []
    elif corruption == "missing_case":
        manifest["sweeps"].pop()
    elif corruption == "duplicate_case":
        manifest["sweeps"][1] = manifest["sweeps"][0].copy()
    elif corruption == "wrong_value":
        manifest["sweeps"][0]["value"] = 100
    elif corruption == "invalid_hash":
        manifest["sweeps"][0]["input_hash_sha256"] = "stale"
    elif corruption == "missing_axis":
        del spec["antenna"]["sweeps"]["gap"]
    csv_rows = copy.deepcopy(manifest.get("sweeps", []))
    if corruption == "csv_status_mismatch":
        csv_rows[0]["status"] = "FAILED"
    elif corruption == "csv_missing_case":
        csv_rows.pop()
    if csv_rows and corruption != "missing_csv":
        write_sweeps(csv_path, csv_rows)
    result = runner._antenna_sweep_result(spec, manifest, csv_path, supported=True)
    assert result["status"] == "FAILED"
    assert evaluate_gate(spec, {"antenna_sweeps": result})["state"] == "NOT_READY_FOR_PHYSICAL_PROTOTYPE"


def test_report_records_partial_sweep_counts_artifact_and_limitations(tmp_path, sweep_inputs):
    spec, manifest = sweep_inputs
    manifest["sweeps"][0]["status"] = "NON_CONVERGED"
    csv_path = tmp_path / "sweeps.csv"
    write_sweeps(csv_path, manifest["sweeps"])
    stage = runner._antenna_sweep_result(spec, manifest, csv_path, supported=True)
    summary = {"gate": evaluate_gate(spec, {"antenna_sweeps": stage}),
               "stages": {"antenna_sweeps": stage}, "spec_sha256": "test",
               "environment": {"platform": "test", "gpu": {}}, "parameter_statuses": {}}
    report = _report(spec, summary)
    assert "3/4 casos configurados concluídos" in report
    assert "NON_CONVERGED" in report
    assert str(csv_path) in report
    assert "Sensibilidade incompleta bloqueia READY" in report
    assert "Sionna continua opcional" in report
