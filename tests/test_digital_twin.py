from pathlib import Path

import pytest

from riose.digital_twin.cli import (_power_assumptions, _power_load_profile, _version_matches,
                                    generate_motion_profiles, preflight)
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
    assert evaluate_gate(spec, stages, required_stage_names=("renode",))["state"] == "NOT_READY_FOR_PHYSICAL_PROTOTYPE"
    assert "renode: MISSING" in evaluate_gate(spec, stages, required_stage_names=("renode",))["blockers"]


def test_spec_rejects_incomplete_or_nonfinite_parameter_records():
    spec, _ = load_spec(ROOT / "hardware/spec.yaml")
    del spec["components"]["mcu"]["run_current_ma"]["source"]
    with pytest.raises(SpecError, match="missing source"):
        validate_spec(spec)

    spec, _ = load_spec(ROOT / "hardware/spec.yaml")
    spec["components"]["mcu"]["run_current_ma"]["value"] = float("nan")
    with pytest.raises(SpecError, match="finite"):
        validate_spec(spec)


def test_spec_rejects_unreviewable_gate_approval_value():
    spec, _ = load_spec(ROOT / "hardware/spec.yaml")
    spec["gate"]["approval"]["antenna"] = "MAYBE"
    with pytest.raises(SpecError, match="PENDING or APPROVED"):
        validate_spec(spec)


def test_spec_rejects_unknown_unit():
    spec, _ = load_spec(ROOT / "hardware/spec.yaml")
    spec["components"]["mcu"]["run_current_ma"]["unit"] = "milliamps-ish"
    with pytest.raises(SpecError, match="unit is unsupported"):
        validate_spec(spec)


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


def test_preflight_reports_versions_without_requiring_optional_solvers():
    report = preflight()
    assert report["status"] == "ENVIRONMENT_PROBE_ONLY"
    assert report["versions"]["python3"]["status"] == "AVAILABLE"
    assert report["versions"]["ngspice"]["status"] in {"AVAILABLE", "NOT_AVAILABLE"}
    assert report["versions"]["python3"]["expected"] == "3.12.x"
    assert report["versions"]["python3"]["matches_expected"] in {True, False}
    assert report["versions"]["zephyr"]["status"] in {"AVAILABLE", "NOT_CONFIGURED"}
    assert Path(report["toolchain_manifest"]).is_file()
    assert report["gpu"]["experiment"] == "OPTIONAL_GPU_EXPERIMENT"


def test_preflight_version_comparison_handles_prereleases_and_minor_pins():
    assert _version_matches("4.2.1", "Zephyr 4.2.1") is True
    assert _version_matches("0.37.0-rc3", "openEMS 0.37.0rc3") is True
    assert _version_matches("3.12.x", "Python 3.12.14") is True
    assert _version_matches("3.12.x", "Python 3.13.0") is False
