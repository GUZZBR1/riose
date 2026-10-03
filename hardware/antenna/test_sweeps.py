from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from hardware.antenna.sweeps import SweepError, plan_sweeps, run_sweeps


@pytest.fixture
def spec():
    return yaml.safe_load(Path("hardware/spec.yaml").read_text())


def test_sweep_plan_covers_four_axes_and_is_deterministic(spec):
    first = plan_sweeps(spec)
    second = plan_sweeps(spec)
    assert first == second
    assert {row["sweep"] for row in first} == {"material", "thickness", "gap", "animal_orientation"}
    assert len({row["case_id"] for row in first}) == len(first)
    assert all(len(row["input_hash_sha256"]) == 64 for row in first)
    assert all(row["provenance"] == "ASSUMED" for row in first)


def test_sweep_inputs_retain_sources_units_and_exact_override(spec):
    cases = plan_sweeps(spec)
    material_case = next(row for row in cases if row["sweep"] == "material")
    assert material_case["override_key"] == "enclosure_relative_permittivity"
    assert material_case["unit"] == "ratio"
    assert "ASSUMED" in material_case["source"]


def test_sweep_runner_retains_failed_and_exception_cases(spec):
    def simulate(**kwargs):
        if kwargs["output_id"].startswith("gap-"):
            raise RuntimeError("controlled test failure")
        return {"status": "NON_CONVERGED", "detail": "energy limit reached"}

    rows = run_sweeps(spec, simulate)
    assert len(rows) == len(plan_sweeps(spec))
    assert all(row["status"] == "NON_CONVERGED" for row in rows if row["sweep"] != "gap")
    assert all(row["status"] == "FAILED" for row in rows if row["sweep"] == "gap")
    assert all("controlled test failure" in row["detail"] for row in rows if row["sweep"] == "gap")


def test_sweep_runner_keeps_each_case_bound_to_its_declared_scenario(spec):
    calls = []

    def simulate(**kwargs):
        calls.append((kwargs["output_id"], kwargs["scenario"]))
        return {"status": "NOT_AVAILABLE", "detail": "solver unavailable"}

    rows = run_sweeps(spec, simulate)
    assert [(row["case_id"], row["scenario"]) for row in rows] == calls
    expected_scenarios = {name: config["scenario"]
                          for name, config in spec["antenna"]["sweeps"].items()}
    assert all(row["scenario"] == expected_scenarios[row["sweep"]] for row in rows)


def test_invalid_sweep_shapes_values_or_provenance_rejected(spec):
    invalid = copy.deepcopy(spec)
    del invalid["antenna"]["sweeps"]["gap"]
    with pytest.raises(SweepError, match="missing required sweep axes"):
        plan_sweeps(invalid)
    invalid = copy.deepcopy(spec)
    invalid["antenna"]["sweeps"]["animal_orientation"]["values"][0]["value"] = 45
    with pytest.raises(SweepError, match="supports 0 and 90"):
        plan_sweeps(invalid)
    invalid = copy.deepcopy(spec)
    invalid["antenna"]["sweeps"]["material"]["values"][0]["status"] = "MEASURED"
    with pytest.raises(SweepError, match="forbidden status"):
        plan_sweeps(invalid)


def test_sweep_unit_mismatch_is_rejected(spec):
    invalid = copy.deepcopy(spec)
    invalid["antenna"]["sweeps"]["gap"]["values"][0]["unit"] = "inch"
    with pytest.raises(SweepError, match="unit must be mm"):
        plan_sweeps(invalid)


@pytest.mark.parametrize("source", [None, "", "  "])
def test_sweep_rejects_empty_provenance_source(spec, source):
    spec["antenna"]["sweeps"]["gap"]["values"][0]["source"] = source
    with pytest.raises(SweepError, match="source must be a non-empty string"):
        plan_sweeps(spec)


def test_sweep_hash_includes_native_solver_configuration(spec, monkeypatch):
    from hardware.antenna import openems_backend
    from hardware.antenna.geometry import build_geometry

    spec_hash = "a" * 64
    first = plan_sweeps(spec, spec_hash=spec_hash)
    for case in first:
        overrides = {case["override_key"]: case["value"]}
        geometry = build_geometry(spec, case["scenario"], overrides)
        assert case["input_hash_sha256"] == openems_backend.expected_input_hash(spec_hash, geometry, overrides)
    monkeypatch.setattr(openems_backend, "END_CRITERIA", 1e-6)
    second = plan_sweeps(spec, spec_hash=spec_hash)
    assert all(a["input_hash_sha256"] != b["input_hash_sha256"] for a, b in zip(first, second))
