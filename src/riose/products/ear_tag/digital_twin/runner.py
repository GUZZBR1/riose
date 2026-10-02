"""Composition of available firmware, mechanical, antenna and power stages."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .execution import _clear_previous_outputs, _run_command, _write_empty_csv
from .motion import generate_motion_profiles
from .paths import ROOT, SCENARIOS, resolve_user_path
from .power import _power_assumptions, _power_load_profile
from .preflight import preflight
from .reporting import _metrics_csv, _report
from .spec import dump_json, evaluate_gate, load_spec, parameter_statuses


DEFAULT_HARDWARE_TEST_BUILD_DIR = Path("/tmp/riose-ear-tag-hardware-tests-v2")


def hardware_integration_executable(environ: dict[str, str] | None = None) -> Path:
    """Resolve the same configurable C integration binary used by Makefile."""
    source = os.environ if environ is None else environ
    build_dir = Path(source.get("HARDWARE_TEST_BUILD_DIR", str(DEFAULT_HARDWARE_TEST_BUILD_DIR)))
    return build_dir.expanduser().resolve() / "hardware_integration"


def run_twin(spec_path: Path, output: Path, seed: int = 7) -> dict[str, Any]:
    # Child tools run from ROOT, so normalize both user paths against the
    # invoking process before any subprocess receives them.
    spec_path = resolve_user_path(spec_path)
    output = resolve_user_path(output)
    spec, spec_hash = load_spec(spec_path)
    output.mkdir(parents=True, exist_ok=True)
    dirs = {name: output / name for name in ("firmware", "power", "antenna", "mechanical", "integration")}
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    env = preflight()
    zephyr_elf: Path | None = Path(os.environ["RIOSE_ZEPHYR_ELF"]) if os.environ.get("RIOSE_ZEPHYR_ELF") else None
    dump_json(dirs["integration"] / "preflight.json", env)
    motion = generate_motion_profiles(dirs["firmware"] / "motion_profiles.csv", seed=seed)
    from hardware.antenna.sionna_experiment import run_experiment as run_sionna_experiment
    sionna = run_sionna_experiment(dirs["antenna"] / "sionna", spec_path=spec_path,
                                  capabilities=env["gpu"])

    stages: dict[str, dict[str, Any]] = {
        "synthetic_motion": motion,
        "gpu_optional": {**env["gpu"], "required": False,
                          "result_class": "ENVIRONMENT_CAPABILITY_ONLY",
                          "experiment_status": sionna["status"],
                          "scenario_statuses": {row["scenario"]: row["status"] for row in sionna["scenarios"]},
                          "detail": "Sionna RT is optional; no GPU scenario blocks the digital twin core"},
    }

    # Run the preserved host integration tests; they validate software models, not Renode or electronics.
    hardware_build_dir = hardware_integration_executable().parent
    c_tests = _run_command(
        "mvp1_c_tests",
        ["make", f"HARDWARE_TEST_BUILD_DIR={hardware_build_dir}", "hardware-test"],
        ROOT, timeout_s=300,
    )
    c_tests["result_class"] = "SIMULATED_SOFTWARE_TESTS"
    stages["mvp1_c_tests"] = c_tests

    zephyr_base = os.environ.get("ZEPHYR_BASE")
    if env["commands"].get("west") and zephyr_base and Path(zephyr_base).is_dir():
        zephyr_build = _run_command("zephyr_build", [env["commands"]["west"], "build",
            "-b", "nucleo_l031k6", str(ROOT / "hardware" / "firmware" / "zephyr"),
            "-d", str(dirs["firmware"] / "zephyr-build")], ROOT, timeout_s=1800)
        elf = dirs["firmware"] / "zephyr-build" / "zephyr" / "zephyr.elf"
        elf_built = zephyr_build["status"] == "PASSED" and elf.is_file()
        if elf_built:
            zephyr_elf = elf
        stages["zephyr_firmware"] = {**zephyr_build,
            "status": "PASSED" if elf_built else "FAILED",
            "required": True, "elf": str(elf) if elf_built else None,
            "detail": "Built target firmware for nucleo_l031k6" if elf_built
            else "west build failed or did not produce the expected Zephyr ELF"}
    else:
        stages["zephyr_firmware"] = {"status": "NOT_AVAILABLE", "required": True,
            "detail": "west/Zephyr workspace is not configured; set ZEPHYR_BASE and install the pinned SDK/workspace"}

    if env["commands"].get("renode") and env["commands"].get("renode-test"):
        robot = ROOT / "hardware" / "renode" / "tests" / "platform-smoke.robot"
        firmware_configured = bool(zephyr_elf and zephyr_elf.is_file())
        robot_env = os.environ.copy()
        if firmware_configured and zephyr_elf is not None:
            robot_env["RIOSE_ZEPHYR_ELF"] = str(zephyr_elf.resolve())
        check = _run_command("renode_smoke", [env["commands"]["renode-test"], str(robot)], ROOT,
                             timeout_s=180, env=robot_env)
        output_text = check.get("stdout", "") + check.get("stderr", "")
        check["status"] = "PASSED" if check["status"] == "PASSED" and firmware_configured else (
            "PARTIAL" if check["status"] == "PASSED" else check["status"]
        )
        check["detail"] = ("Renode platform smoke and Zephyr ELF execution completed" if firmware_configured
                            else "Renode platform/peripheral smoke ran; firmware execution is pending RIOSE_ZEPHYR_ELF")
        check["firmware_elf_supplied"] = firmware_configured
        check["firmware_elf"] = str(zephyr_elf.resolve()) if firmware_configured and zephyr_elf else None
        check["log_excerpt"] = output_text[-1000:]
        stages["renode_firmware"] = check
    else:
        stages["renode_firmware"] = {"status": "NOT_AVAILABLE", "required": True,
                                      "detail": "Renode and renode-test are required for the MCU/bus twin"}

    # Export one deterministic C-FSM trace per requested behavioral profile.
    trace_path = dirs["firmware"] / "firmware_trace.jsonl"
    hardware_bin = hardware_build_dir / "hardware_integration"
    scenario_traces: dict[str, Path] = {}
    trace_runs: dict[str, dict[str, Any]] = {}
    if c_tests["status"] == "PASSED" and hardware_bin.exists():
        for scenario in SCENARIOS:
            path = dirs["firmware"] / "scenarios" / f"{scenario.lower()}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            trace_run = subprocess.run(
                [str(hardware_bin), "--trace-output", str(path), "--trace-scenario", scenario],
                cwd=ROOT, capture_output=True, text=True, timeout=120, check=False,
            )
            trace_runs[scenario] = {
                "status": "PASSED" if trace_run.returncode == 0 and path.is_file() else "FAILED",
                "return_code": trace_run.returncode, "path": str(path),
                "stderr": trace_run.stderr[-3000:], "result_class": "SIMULATED_SOFTWARE_TRACE",
            }
            if trace_runs[scenario]["status"] == "PASSED":
                scenario_traces[scenario] = path
        normal = trace_runs.get("NORMAL", {})
        trace_path = scenario_traces.get("NORMAL", trace_path)
        if trace_path.is_file():
            (dirs["firmware"] / "firmware_trace.jsonl").write_bytes(trace_path.read_bytes())
        stages["host_trace_export"] = {
            **normal, "status": "PASSED" if normal.get("status") == "PASSED" else "FAILED",
            "required": True, "result_class": "SIMULATED_SOFTWARE_TRACE",
            "scenarios": trace_runs,
        }
    else:
        stages["host_trace_export"] = {"status": "NOT_AVAILABLE", "required": True,
                                       "detail": "Host C integration executable was not built"}

    stages["firmware_scenarios"] = {
        "status": "COMPLETED" if len(scenario_traces) == len(SCENARIOS) else "NOT_AVAILABLE",
        "required": True, "result_class": "SIMULATED_SOFTWARE_TESTS",
        "scenarios": trace_runs,
        "detail": "C FSM traces exported for all four requested profiles" if len(scenario_traces) == len(SCENARIOS)
                  else "One or more C FSM profile traces could not be produced",
    }

    long_run_results: dict[str, dict[str, Any]] = {}
    if c_tests["status"] == "PASSED" and hardware_bin.exists():
        for days in (1, 7, 30):
            for scenario in SCENARIOS:
                key = f"{scenario}_{days}d"
                try:
                    result = subprocess.run(
                        [str(hardware_bin), "--long-run-days", str(days), "--scenario", scenario],
                        cwd=ROOT, capture_output=True, text=True, timeout=120, check=False,
                    )
                    payload = json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else {}
                    long_run_results[key] = {**payload,
                        "status": payload.get("status", "FAILED") if result.returncode == 0 else "FAILED",
                        "return_code": result.returncode,
                    }
                except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
                    long_run_results[key] = {"status": "FAILED", "detail": str(exc)}
    all_long_runs = len(long_run_results) == 12 and all(
        result.get("status") == "COMPLETED" for result in long_run_results.values()
    )
    stages["long_duration_1_7_30_days"] = {
        "status": "COMPLETED" if all_long_runs else "NOT_AVAILABLE", "required": True,
        "result_class": "SIMULATED_SOFTWARE_RUN", "runs": long_run_results,
        "detail": "12 deterministic FSM long runs completed" if all_long_runs
                  else "One or more NORMAL/ACTIVE/ALERT/WORST_REASONABLE_CASE runs for 1/7/30 days failed",
    }

    # Host C tests classify reset flags but cannot provoke an MCU reset. The
    # Zephyr target build proves the IWDG code compiles for the selected board;
    # only physical target execution can prove watchdog reset behavior.
    host_faults = ["one_shot_i2c_failure_recovery", "one_shot_spi_failure_recovery",
                   "late_tx_done_timeout_recovery", "digital_fault_crc_corruption",
                   "digital_fault_sx1262_busy_stuck", "digital_fault_irq_missing",
                   "digital_reset_cause_flag_classification"]
    remaining_faults = ["battery_voltage_drop", "high_esr", "regulator_instability",
                        "watchdog_reset_executed_on_target", "unexpected_reboot"]
    stages["adversarial_fault_injection"] = {
        "status": "PARTIAL" if c_tests["status"] == "PASSED" else "NOT_AVAILABLE",
        "required": True, "completed_host_cases": host_faults if c_tests["status"] == "PASSED" else [],
        "pending_cases": remaining_faults,
        "watchdog_target_build": {
            "status": "CONFIGURED_AND_COMPILED" if stages["zephyr_firmware"]["status"] == "PASSED" else "NOT_VERIFIED",
            "timeout_ms": 10_000,
            "result_class": "TARGET_FIRMWARE_BUILD_EVIDENCE",
            "detail": "The NUCLEO-L031K6 image configures the STM32 IWDG and reports/clears reset flags; no physical watchdog reset was triggered",
        },
        "detail": "Host C tests cover transient I2C/SPI/TX recovery, CRC rejection, bounded SX1262 BUSY wait, TX/RX IRQ deadlines, and deterministic reset-flag classification. The Zephyr target build configures the MCU watchdog, but reset behavior is not physically executed. Analog power faults require electrical models; unexpected reboot needs a persistent expected-reset contract",
    }

    mechanical_report = dirs["mechanical"] / "geometry.json"
    cad_step = dirs["mechanical"] / "ear_tag_assumed.step"
    cad_stl = dirs["mechanical"] / "ear_tag_assumed.stl"
    _clear_previous_outputs(mechanical_report, cad_step, cad_stl)
    mechanical_cmd = [sys.executable, str(ROOT / "hardware" / "mechanical" / "model.py"),
                      "--spec", str(spec_path), "--output", str(mechanical_report)]
    if env["modules"].get("cadquery"):
        mechanical_cmd += ["--step", str(cad_step), "--stl", str(cad_stl)]
    if (ROOT / "hardware" / "mechanical" / "model.py").exists():
        mech = _run_command("mechanical", mechanical_cmd, ROOT, timeout_s=120)
        if mechanical_report.exists():
            geometry = json.loads(mechanical_report.read_text())
            mech["checks"] = [{"name": "envelope_fit", "passed": geometry.get("fit", {}).get("fits"),
                               "status": "SIMULATED", "value": geometry.get("fit", {}).get("issues")}]
            mech["detail"] = "; ".join(geometry.get("fit", {}).get("issues", [])) or "Bounding-box fit estimate completed"
            mech["fit"] = geometry.get("fit", {})
            mech["cadquery_available"] = geometry.get("cadquery_available", False)
            mech["dimensions_status"] = geometry.get("specification_statuses", [])
            mech["result_class"] = "SIMULATED_GEOMETRY_ESTIMATE"
            if not geometry.get("cadquery_available"):
                mech["status"] = "NOT_AVAILABLE"
                mech["detail"] += "; CadQuery STEP export unavailable"
            elif mech.get("status") != "PASSED":
                mech["status"] = "FAILED"
                command_error = mech.get("stderr") or mech.get("stdout") or "CAD command failed"
                mech["detail"] = f"Mechanical report/export command failed: {command_error[-1000:]}"
            else:
                mech["status"] = "COMPLETED" if geometry.get("fit", {}).get("fits") else "FAILED"
        stages["mechanical"] = mech
    else:
        stages["mechanical"] = {"status": "NOT_AVAILABLE", "required": True,
                                 "detail": "Mechanical model implementation is absent"}

    antenna_cmd = [sys.executable, "-m", "hardware.antenna.run", "--spec", str(spec_path),
                   "--output", str(dirs["antenna"])]
    antenna_manifest = dirs["antenna"] / "antenna_experiments.json"
    antenna_csv = dirs["antenna"] / "antenna.csv"
    _clear_previous_outputs(antenna_manifest, antenna_csv)
    ant = _run_command("antenna", antenna_cmd, ROOT, timeout_s=1800)
    if antenna_manifest.exists():
        ant_json = json.loads(antenna_manifest.read_text())
        ant["status"] = "COMPLETED" if ant_json.get("status") == "COMPLETED" else ant_json.get("status", "NOT_AVAILABLE")
        ant["result_class"] = ant_json.get("result_class")
        ant["scenarios"] = ant_json.get("scenarios", [])
        incomplete = [row for row in ant["scenarios"] if row.get("status") != "COMPLETED"]
        if incomplete:
            ant["detail"] = "; ".join(
                f"{row.get('scenario', 'scenario')}: {row.get('status', 'UNKNOWN')} ({row.get('detail', '')})"
                for row in incomplete
            )
        else:
            ant["detail"] = ant_json.get("limitations", [""])[0]
        if ant.get("return_code") not in (None, 0) and ant_json.get("status") == "COMPLETED":
            ant["status"] = "FAILED"
            ant["detail"] = "Antenna runner returned an error despite a completed manifest"
    elif ant.get("status") == "PASSED":
        ant["status"] = "FAILED"
        ant["detail"] = "Antenna runner exited successfully without producing a manifest"
    stages["antenna"] = ant

    power_scenarios: dict[str, dict[str, Any]] = {}
    schedule_statuses: dict[str, str] = {}
    if scenario_traces and (ROOT / "hardware" / "spice" / "trace_adapter.py").exists():
        loads_path = dirs["power"] / "assumed_load_profile.json"
        dump_json(loads_path, _power_load_profile(spec))
        power_assumptions_path = dirs["power"] / "assumptions.json"
        dump_json(power_assumptions_path, _power_assumptions(spec))
        for scenario, input_trace in scenario_traces.items():
            scenario_dir = dirs["power"] / scenario.lower()
            schedule_path = scenario_dir / "schedule.jsonl"
            adapter = [sys.executable, str(ROOT / "hardware" / "spice" / "trace_adapter.py"),
                       str(input_trace), "--loads", str(loads_path), "--output", str(schedule_path)]
            adapted = _run_command("trace_schedule", adapter, ROOT, timeout_s=120)
            if adapted["status"] != "PASSED" or not schedule_path.is_file():
                schedule_statuses[scenario] = "FAILED"
                power_scenarios[scenario] = {"status": "NOT_AVAILABLE", "detail": "Trace conversion failed"}
                continue
            schedule_statuses[scenario] = "PASSED"
            power_cmd = [sys.executable, str(ROOT / "hardware" / "spice" / "mvp2_power.py"),
                         str(schedule_path), "--assumptions", str(power_assumptions_path),
                         "--output", str(scenario_dir)]
            powered = _run_command("power", power_cmd, ROOT, timeout_s=1800)
            result_path = scenario_dir / "summary.json"
            if powered["status"] == "PASSED" and result_path.is_file():
                result = json.loads(result_path.read_text())
                power_scenarios[scenario] = {
                    "status": "COMPLETED" if result.get("ngspice", {}).get("status") == "EXECUTED" else "NOT_AVAILABLE",
                    "ngspice_status": result.get("ngspice", {}).get("status", "UNKNOWN"),
                    "modeled_charge_uah": result.get("total_charge_mah_window", 0) * 1000,
                    "modeled_window_s": result.get("modeled_window_s"),
                    "event_charge": result.get("event_charge", []),
                    "result_class": "SIMULATED", "outputs": str(scenario_dir),
                }
            else:
                power_scenarios[scenario] = {"status": "FAILED", "detail": powered.get("stderr", "power runner failed")}
        all_power = len(power_scenarios) == len(SCENARIOS) and all(
            result.get("status") == "COMPLETED" for result in power_scenarios.values()
        )
        # Keep the original top-level power artifact shape for downstream users.
        normal_power = power_scenarios.get("NORMAL", {})
        normal_summary_path = dirs["power"] / "normal" / "summary.json"
        if normal_summary_path.exists():
            import shutil as _shutil
            _shutil.copy2(normal_summary_path, dirs["power"] / "summary.json")
            _shutil.copy2(dirs["power"] / "normal" / "power.csv", dirs["power"] / "power.csv")
        stages["power"] = {
            "status": "COMPLETED" if all_power else "NOT_AVAILABLE", "required": True,
            "result_class": "SIMULATED", "scenarios": power_scenarios,
            "ngspice_status": normal_power.get("ngspice_status", "NOT_RUN"),
            "modeled_charge_uah": normal_power.get("modeled_charge_uah"),
            "modeled_window_s": normal_power.get("modeled_window_s"),
            "event_charge": normal_power.get("event_charge", []),
            "detail": "Four scenario rail simulations completed" if all_power
                      else "Trace charge integration is available where produced; ngspice execution remains required for rail results",
        }
        stages["four_power_scenarios"] = {
            "status": "COMPLETED" if all_power else "NOT_AVAILABLE", "required": True,
            "scenarios": power_scenarios,
            "detail": "NORMAL/ACTIVE/ALERT/WORST_REASONABLE_CASE were converted from firmware traces and analyzed",
        }
        schedules_complete = len(schedule_statuses) == len(SCENARIOS) and all(
            status == "PASSED" for status in schedule_statuses.values()
        )
        stages["trace_schedule"] = {"status": "PASSED" if schedules_complete else "FAILED",
                                     "required": True, "scenarios": schedule_statuses}
    else:
        stages["power"] = {"status": "NOT_AVAILABLE", "required": True,
                            "detail": "Firmware traces and the trace-to-power adapter are required"}
        stages["four_power_scenarios"] = {"status": "NOT_AVAILABLE", "required": True,
                                          "detail": "Four scenario traces could not be generated"}

    failures: list[dict[str, Any]] = []
    failures.extend({"scenario": "adversarial_fault_injection", "failure": case,
                     "detail": "NOT_RUN: persistent fault injection is not implemented in the configured backend",
                     "status": "NOT_RUN"} for case in remaining_faults)
    failures.extend({"scenario": name, "failure": result.get("status", "FAILED"),
                     "detail": result.get("detail", "long virtual run did not complete"),
                     "status": "NOT_RUN"}
                    for name, result in long_run_results.items()
                    if result.get("status") != "COMPLETED")
    for name, result in stages.items():
        status = result.get("status", "UNKNOWN")
        if status not in {"COMPLETED", "PASSED"} and result.get("required", True):
            failures.append({"scenario": name, "failure": status,
                             "detail": result.get("detail", result.get("stderr", "")),
                             "status": "SIMULATED_OR_TOOLCHAIN_BLOCKER"})
        for check in result.get("checks", []):
            if check.get("passed") is False:
                failures.append({"scenario": name, "failure": check.get("name", "check_failed"),
                                 "detail": json.dumps(check.get("value")), "status": "SIMULATED"})

    # An unavailable submodel produces headers only, never invented numeric data.
    power_csv = dirs["power"] / "power.csv"
    if not power_csv.exists():
        _write_empty_csv(power_csv, ["timestamp_start_s", "timestamp_end_s", "duration_s", "load_current_ma", "active_events", "active_components", "status"])
    antenna_csv = dirs["antenna"] / "antenna.csv"
    if not antenna_csv.exists():
        _write_empty_csv(antenna_csv, ["scenario", "status", "resonant_frequency_hz", "s11_min_db", "input_impedance_real_ohm", "input_impedance_imag_ohm", "vswr_min", "efficiency_fraction", "gain_dbi", "s11_curve_path", "radiation_pattern_path"])
    with (output / "failures.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = ["scenario", "failure", "detail", "status"]
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(failures)

    gate = evaluate_gate(spec, stages, required_stage_names=(
        "zephyr_firmware", "renode_firmware", "long_duration_1_7_30_days",
        "adversarial_fault_injection", "four_power_scenarios", "mechanical",
        "antenna", "power",
    ))
    summary = {"schema_version": "riose.mvp2.digital-twin/v1", "milestone": "MVP2_DIGITAL_TWIN",
               "result_class": "SIMULATED", "spec_path": str(spec_path), "spec_sha256": spec_hash,
               "parameter_statuses": parameter_statuses(spec), "environment": env, "stages": stages,
               "gate": gate, "failure_count": len(failures),
               "outputs": {"root": str(output), "firmware": str(dirs["firmware"]),
                         "power": str(dirs["power"]), "antenna": str(dirs["antenna"]),
                         "mechanical": str(dirs["mechanical"]), "integration": str(dirs["integration"]),
                         "failures_csv": str(output / "failures.csv")},
               "physical_measurements_used": False, "gpu_issue": "OPTIONAL_GPU_EXPERIMENT"}
    dump_json(output / "summary.json", summary)
    _metrics_csv(output / "metrics.csv", stages)
    (ROOT / "docs" / "mvp2-digital-twin-report.md").write_text(_report(spec, summary), encoding="utf-8")
    dump_json(dirs["integration"] / "summary.json", summary)
    return summary
