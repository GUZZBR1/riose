from pathlib import Path

import pytest

from riose.digital_twin.cli import (_power_assumptions, _power_load_profile, _version_matches,
                                    _clear_previous_outputs, _report,
                                    _long_run_energy_uah, _stack_usage,
                                    generate_motion_profiles, preflight)
from riose.digital_twin.faults import FAULT_SCENARIOS
from riose.digital_twin.spec import SpecError, evaluate_gate, load_spec, validate_spec
from riose.products.ear_tag.digital_twin import cli as canonical_cli
from riose.products.ear_tag.digital_twin.paths import resolve_user_path
from riose.products.ear_tag.digital_twin.power import _repeat_period_arguments
from riose.products.ear_tag.digital_twin import spec as canonical_spec


ROOT = Path(__file__).resolve().parents[2]


def test_power_repeat_period_argument_preserves_spec_provenance():
    spec, _ = load_spec(ROOT / "hardware/spec.yaml")

    args = _repeat_period_arguments(spec)

    assert args[:2] == ["--period-s", "900.0"]
    assert args[2] == "--period-source"
    assert "hardware/spec.yaml:power_profiles.normal_beacon_interval_s" in args[3]
    assert "SIMULATED" in args[3]
    assert args[4:] == ["--period-status", "SIMULATED", "--period-unit", "s"]


def test_power_assumptions_preserve_nominal_capacity_provenance():
    spec, _ = load_spec(ROOT / "hardware/spec.yaml")

    capacity = _power_assumptions(spec)["nominal_capacity_mah"]

    assert capacity == {
        "value": 1100.0,
        "unit": "mAh",
        "status": "DATASHEET",
        "source": "hardware/spec.yaml:components.battery.nominal_capacity_mah "
                  "(DATASHEET: Datasheet rated at 1 mA to 2.0 V; not usable-capacity evidence for this rail)",
    }


@pytest.mark.parametrize("field,value", [
    ("value", 0), ("value", -1), ("value", float("nan")),
    ("value", float("inf")), ("value", True), ("unit", "ms"),
    ("status", "MEASURED"), ("status", []), ("source", ""), ("source", "   "),
])
def test_power_repeat_period_rejects_invalid_or_unproven_spec_records(field, value):
    spec, _ = load_spec(ROOT / "hardware/spec.yaml")
    spec["power_profiles"]["normal_beacon_interval_s"] = {
        **spec["power_profiles"]["normal_beacon_interval_s"], field: value}

    assert _repeat_period_arguments(spec) == []


def test_legacy_modules_forward_to_canonical_objects():
    from riose.digital_twin import cli as legacy_cli
    from riose.digital_twin import spec as legacy_spec

    assert legacy_cli.run_twin is canonical_cli.run_twin
    assert legacy_cli.preflight is canonical_cli.preflight
    assert legacy_cli.main is canonical_cli.main
    for name in ("dump_json", "evaluate_gate", "load_spec", "parameter_statuses"):
        assert getattr(legacy_cli, name) is getattr(canonical_spec, name)
    assert legacy_spec.load_spec is canonical_spec.load_spec
    assert legacy_spec.SpecError is canonical_spec.SpecError
    assert legacy_spec.validate_spec is canonical_spec.validate_spec
    assert canonical_cli.ROOT == ROOT
    assert canonical_cli.DEFAULT_SPEC == ROOT / "hardware/spec.yaml"
    assert canonical_cli.DEFAULT_OUTPUT == ROOT / "results/mvp2"


def test_runner_uses_the_configured_hardware_test_build_directory(tmp_path):
    from riose.products.ear_tag.digital_twin.runner import hardware_integration_executable

    assert hardware_integration_executable({}) == Path(
        "/tmp/riose-ear-tag-hardware-tests-v2/hardware_integration"
    )
    assert hardware_integration_executable({
        "HARDWARE_TEST_BUILD_DIR": str(tmp_path / "custom build")
    }) == tmp_path / "custom build" / "hardware_integration"


def test_mechanical_fit_failure_keeps_specific_report_diagnostics():
    from riose.products.ear_tag.digital_twin.runner import _classify_mechanical_result

    result = _classify_mechanical_result(
        {"status": "FAILED", "detail": "battery envelope exceeds enclosure cavity",
         "stderr": "mechanical model error: CAD export blocked"},
        {"cadquery_available": True,
         "fit": {"fits": False, "issues": ["battery envelope exceeds enclosure cavity"]}},
    )
    assert result["status"] == "FAILED"
    assert "battery envelope exceeds enclosure cavity" in result["detail"]
    assert "Mechanical report/export command failed" not in result["detail"]


def test_mechanical_fit_failure_takes_precedence_when_cadquery_is_unavailable():
    from riose.products.ear_tag.digital_twin.runner import _classify_mechanical_result

    result = _classify_mechanical_result(
        {"status": "NOT_AVAILABLE", "detail": "battery outside cavity"},
        {"cadquery_available": False,
         "fit": {"fits": False, "issues": ["battery outside cavity"]}},
    )
    assert result["status"] == "FAILED"
    assert "battery outside cavity" in result["detail"]
    assert "CadQuery unavailable, export was not attempted" in result["detail"]


@pytest.mark.parametrize("module", ["riose.products.ear_tag.digital_twin", "riose.digital_twin"])
def test_canonical_and_legacy_module_commands(module):
    import json
    import subprocess
    import sys

    help_result = subprocess.run([sys.executable, "-m", module, "--help"], cwd=ROOT,
                                 capture_output=True, text=True, check=False)
    assert help_result.returncode == 0, help_result.stderr
    assert "validate-spec" in help_result.stdout
    assert "python -m riose.products.ear_tag.digital_twin" in help_result.stdout

    validate_result = subprocess.run(
        [sys.executable, "-m", module, "validate-spec", "--spec", "hardware/spec.yaml"],
        cwd=ROOT, capture_output=True, text=True, check=False)
    assert validate_result.returncode == 0, validate_result.stderr
    assert json.loads(validate_result.stdout)["status"] == "VALID"

    preflight_result = subprocess.run([sys.executable, "-m", module, "preflight"], cwd=ROOT,
                                      capture_output=True, text=True, check=False)
    assert preflight_result.returncode == 0, preflight_result.stderr
    assert json.loads(preflight_result.stdout)["status"] == "ENVIRONMENT_PROBE_ONLY"


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


def test_rerun_discards_old_stage_outputs_before_invoking_tools(tmp_path):
    stale = [tmp_path / name for name in ("geometry.json", "antenna.csv", "antenna_experiments.json")]
    for path in stale:
        path.write_text("stale success")
    _clear_previous_outputs(*stale)
    assert all(not path.exists() for path in stale)


def test_user_paths_are_resolved_from_invoking_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert resolve_user_path(Path("inputs/spec.yaml")) == (tmp_path / "inputs/spec.yaml").resolve()
    assert resolve_user_path(Path("results/mvp2")).is_absolute()


def test_run_resolves_spec_and_output_before_tools_use_checkout_cwd(tmp_path, monkeypatch):
    import shutil

    from riose.products.ear_tag.digital_twin import runner

    shutil.copy2(ROOT / "hardware/spec.yaml", tmp_path / "spec.yaml")
    (tmp_path / "docs").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "preflight", lambda: {
        "platform": "test", "commands": {}, "modules": {}, "gpu": {"GPU_AVAILABLE": False},
    })
    commands = []

    def unavailable(name, command, cwd, **kwargs):
        commands.append((name, command, cwd))
        return {"status": "NOT_AVAILABLE", "detail": "test stub", "required": True}

    monkeypatch.setattr(runner, "_run_command", unavailable)
    summary = runner.run_twin(Path("spec.yaml"), Path("relative-output"))

    assert summary["spec_path"] == str((tmp_path / "spec.yaml").resolve())
    assert summary["outputs"]["root"] == str((tmp_path / "relative-output").resolve())
    antenna_command = next(command for name, command, _ in commands if name == "antenna")
    spec_argument = antenna_command[antenna_command.index("--spec") + 1]
    output_argument = antenna_command[antenna_command.index("--output") + 1]
    assert Path(spec_argument).is_absolute()
    assert Path(output_argument).is_absolute()


def test_report_does_not_invent_antenna_metrics_when_scenarios_are_missing():
    summary = {
        "gate": {"state": "NOT_READY_FOR_PHYSICAL_PROTOTYPE", "blockers": []},
        "stages": {"antenna": {"status": "PARTIAL_OR_BLOCKED"}},
        "spec_sha256": "test",
        "environment": {"platform": "test", "gpu": {}},
        "parameter_statuses": {},
    }
    report = _report({}, summary)
    assert "Nenhum cenário de RF produziu resultado do solver." in report


def test_fault_catalog_defines_injection_recovery_attempts_terminal_and_trace():
    required = {"fault", "injection", "recovery_expected", "attempts", "terminal_state", "trace_event", "host_argument"}
    assert len({row["fault"] for row in FAULT_SCENARIOS}) == 10
    assert all(required <= row.keys() for row in FAULT_SCENARIOS)
    assert all(row["attempts"] > 0 for row in FAULT_SCENARIOS if row["host_argument"])
    assert all(row.get("blocker") for row in FAULT_SCENARIOS if row["host_argument"] is None)


def test_reset_cases_are_synthetic_classification_probes_not_recovery_claims():
    probes = {row["fault"]: row for row in FAULT_SCENARIOS
              if row["fault"].startswith("synthetic_")}
    assert set(probes) == {"synthetic_watchdog_classification_probe",
                           "synthetic_reset_classification_probe"}
    assert all(not row["recovery_expected"] for row in probes.values())
    assert all(row["host_argument"].startswith("host:") for row in probes.values())
    assert "classification flag" in probes["synthetic_watchdog_classification_probe"]["injection"]
    assert "firmware init" in probes["synthetic_reset_classification_probe"]["injection"]


def test_long_run_energy_integrates_assumed_currents_and_observed_packet_count():
    spec, _ = load_spec(ROOT / "hardware/spec.yaml")
    one = _long_run_energy_uah(1, 100, spec)
    two = _long_run_energy_uah(2, 200, spec)
    assert one["status"] == "SIMULATED_FROM_ASSUMED_PROFILE"
    assert one["value_uah"] > 0
    assert two["value_uah"] == pytest.approx(2 * one["value_uah"])
    assert one["packet_count"] == 100


def test_stack_report_distinguishes_static_frames_from_runtime_high_water(tmp_path):
    (tmp_path / "unit.su").write_text("main.c:main\t32\tstatic\nfoo.c:foo\t48\tstatic\n")
    report = _stack_usage(tmp_path)
    assert report["status"] == "STATIC_FRAME_USAGE"
    assert report["max_frame_bytes"] == 48
    assert "excludes call-chain" in report["limitation"]
def test_report_summarizes_completed_antenna_scenarios_without_claiming_physical_validation():
    summary = {
        "gate": {"state": "NOT_READY_FOR_PHYSICAL_PROTOTYPE", "blockers": []},
        "stages": {"antenna": {"status": "PARTIAL_OR_BLOCKED", "scenarios": [
            {"scenario": "ANTENNA_WITH_ENCLOSURE", "status": "COMPLETED"},
            {"scenario": "ANTENNA_WITH_BATTERY", "status": "FAILED"},
        ]}},
        "spec_sha256": "test",
        "environment": {"platform": "test", "gpu": {}},
        "parameter_statuses": {},
    }
    report = _report({}, summary)
    assert "1/2 cenários passaram a comparação numérica de malha" in report
    assert "não validam desempenho físico" in report
