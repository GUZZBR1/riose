from pathlib import Path

import pytest

from riose.digital_twin.cli import _power_assumptions, _power_load_profile, generate_motion_profiles
from riose.digital_twin.spec import SpecError, evaluate_gate, load_spec, validate_spec


ROOT = Path(__file__).resolve().parents[1]


def test_mvp2_spec_validates_and_forbids_measured_values():
    spec, digest = load_spec(ROOT / "hardware/spec.yaml")
    assert len(digest) == 64
    spec["components"]["mcu"]["run_current_ma"]["status"] = "MEASURED"
    with pytest.raises(SpecError, match="MEASURED"):
        validate_spec(spec)


def test_gate_requires_success_then_human_approvals():
    spec, _ = load_spec(ROOT / "hardware/spec.yaml")
    stages = {"core": {"status": "PASSED", "required": True}}
    gate = evaluate_gate(spec, stages)
    assert gate["state"] == "CONDITIONALLY_READY_PENDING_THRESHOLD_APPROVAL"
    assert set(gate["blockers"]) == {
        "approval pending: thresholds", "approval pending: dimensions",
        "approval pending: antenna", "approval pending: fit",
    }
    spec["gate"]["approval"] = {key: "APPROVED" for key in ("thresholds", "dimensions", "antenna", "fit")}
    assert evaluate_gate(spec, stages)["state"] == "READY_FOR_PHYSICAL_PROTOTYPE"
    stages["core"]["status"] = "NOT_AVAILABLE"
    assert evaluate_gate(spec, stages)["state"] == "NOT_READY_FOR_PHYSICAL_PROTOTYPE"


def test_power_profile_carries_assumed_current_sources():
    spec, _ = load_spec(ROOT / "hardware/spec.yaml")
    profile = _power_load_profile(spec)
    assert profile["status"] == "ASSUMED"
    assert profile["loads"]["pair:TX_START:TX_DONE"]["current_status"] == "ASSUMED"
    assert profile["loads"]["event:IMU_READ"]["duration_status"] == "ASSUMED"
    assert profile["loads"]["pair:TX_START:TX_DONE"]["load_current_ma"] == 45.0
    assert profile["loads"]["pair:TX_START:TX_DONE"]["duration_status"] == "ASSUMED"


def test_power_assumptions_derive_idle_without_double_counting_mcu():
    spec, _ = load_spec(ROOT / "hardware/spec.yaml")
    assumptions = _power_assumptions(spec)
    assert assumptions["idle_current_ma"]["value"] == pytest.approx(0.00146)
    assert "excludes MCU stop current" in assumptions["idle_current_ma"]["source"]
    assert assumptions["battery_esr_ohm"]["value"] == pytest.approx(0.25)


def test_motion_inputs_are_seeded_and_explicitly_synthetic(tmp_path):
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    generate_motion_profiles(first, seed=19, samples_per_profile=4)
    generate_motion_profiles(second, seed=19, samples_per_profile=4)
    assert first.read_bytes() == second.read_bytes()
    assert first.read_text().count("SIMULATED") == 20
    assert "animal_measurement" in first.read_text()
