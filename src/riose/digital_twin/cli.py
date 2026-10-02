"""Headless MVP2 runner; missing solvers are reported, never replaced by fakes."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import platform
import random
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .spec import dump_json, evaluate_gate, load_spec, parameter_statuses


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SPEC = ROOT / "hardware" / "spec.yaml"
DEFAULT_OUTPUT = ROOT / "results" / "mvp2"
SCENARIOS = ("NORMAL", "ACTIVE", "ALERT", "WORST_REASONABLE_CASE")


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def preflight() -> dict[str, Any]:
    commands = {name: shutil.which(name) for name in (
        "python3", "west", "renode", "renode-test", "ngspice", "openEMS", "openscad",
    )}
    modules = {name: _module_available(name) for name in ("yaml", "cadquery", "openEMS", "CSXCAD", "torch", "sionna")}
    try:
        from hardware.antenna.capabilities import detect_capabilities
        gpu = detect_capabilities()
    except (ImportError, OSError):
        gpu = {"GPU_AVAILABLE": False, "GPU_TYPE": "UNKNOWN", "CUDA_AVAILABLE": False,
               "SIONNA_AVAILABLE": False, "status": "UNAVAILABLE", "experiment": "OPTIONAL_GPU_EXPERIMENT"}
    return {"status": "ENVIRONMENT_PROBE_ONLY", "platform": platform.platform(),
            "python": sys.version.split()[0], "commands": commands, "modules": modules,
            "gpu": gpu, "physical_hardware_used": False}


def _record(spec: dict[str, Any], dotted: str, fallback: float = 0.0) -> float:
    node: Any = spec
    for name in dotted.split("."):
        node = node.get(name) if isinstance(node, dict) else None
    if isinstance(node, dict) and "value" in node:
        return float(node["value"])
    return fallback


def _power_load_profile(spec: dict[str, Any]) -> dict[str, Any]:
    """Build explicit ASSUMED loads from the single hardware specification."""
    awake = _record(spec, "components.mcu.run_current_ma")
    sleep = _record(spec, "components.mcu.stop_current_ma")
    tx = _record(spec, "components.radio.tx_stress_current_ma")
    rx = _record(spec, "components.radio.rx_current_ma")
    imu = _record(spec, "power_profiles.imu_sample_current_ma")
    duration = _record(spec, "power_profiles.mcu_awake_s_per_event")
    sleep_duration = _record(spec, "power_profiles.normal_beacon_interval_s")
    tx_duration = _record(spec, "components.radio.tx_duration_s")
    rx_duration = _record(spec, "components.radio.rx_window_s")
    loads: dict[str, dict[str, Any]] = {
        "state:SLEEP": {"component": "mcu", "load_current_ma": sleep,
                         "fallback_duration_s": sleep_duration, "duration_status": "ASSUMED"},
        "pair:TX_START:TX_DONE": {"component": "sx1262", "load_current_ma": tx,
                                   "fallback_duration_s": tx_duration, "duration_status": "ASSUMED"},
        "pair:RX_START:RX_DONE": {"component": "sx1262", "load_current_ma": rx,
                                   "fallback_duration_s": rx_duration, "duration_status": "ASSUMED"},
        "event:IMU_READ": {"component": "lis2dw12", "load_current_ma": imu,
                            "fallback_duration_s": duration, "duration_status": "ASSUMED"},
    }
    for state in ("BOOT", "SELF_TEST", "IMU_MONITORING", "RF_TX", "RF_RX", "ALERT", "ERROR_RECOVERY"):
        loads[f"state:{state}"] = {"component": "mcu", "load_current_ma": awake,
                                    "fallback_duration_s": duration, "duration_status": "ASSUMED"}
    # Preserve source/status for every generated value. Current values originate
    # in the parameter record; the conversion remains a digital estimate.
    for key, value in loads.items():
        param = ("components.mcu.stop_current_ma" if key == "state:SLEEP" else
                 "components.mcu.run_current_ma" if key.startswith("state:") else
                 "components.radio.tx_stress_current_ma" if key.startswith("pair:TX") else
                 "components.radio.rx_current_ma" if key.startswith("pair:RX") else
                 "power_profiles.imu_sample_current_ma")
        node: Any = spec
        for part in param.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        value.update({"current_status": "ASSUMED", "source": node.get("source", param) if isinstance(node, dict) else param})
        if "fallback_duration_s" in value:
            duration_param = ("power_profiles.normal_beacon_interval_s" if key == "state:SLEEP"
                              else "components.radio.tx_duration_s" if key.startswith("pair:TX")
                              else "components.radio.rx_window_s" if key.startswith("pair:RX")
                              else "power_profiles.mcu_awake_s_per_event")
            duration_node: Any = spec
            for part in duration_param.split("."):
                duration_node = duration_node.get(part) if isinstance(duration_node, dict) else None
            if isinstance(duration_node, dict):
                value["source"] += f"; fallback duration ASSUMED from {duration_node['source']}"
                value["duration_source"] = f"{duration_param} ({duration_node.get('status', 'UNKNOWN')}: {duration_node['source']}); applied as ASSUMED fallback"
    return {"schema_version": "riose.power.loads/v1", "status": "ASSUMED",
            "note": "Currents are assumed/configuration-derived, not measured; modeled loads are additive to idle allowance.",
            "loads": loads}


def _power_assumptions(spec: dict[str, Any]) -> dict[str, Any]:
    """Project the canonical spec into the ngspice runner's model input schema."""
    def source(path: str) -> str:
        node: Any = spec
        for part in path.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if not isinstance(node, dict) or "value" not in node:
            raise ValueError(f"missing numeric power assumption: {path}")
        return f"hardware/spec.yaml:{path} ({node.get('status')}: {node.get('source')})"

    def numeric(path: str) -> float:
        return _record(spec, path)

    values = {
        "battery_voltage_v": (numeric("components.battery.nominal_voltage_v"), "V", source("components.battery.nominal_voltage_v")),
        "battery_esr_ohm": (numeric("components.battery.esr_ohm"), "ohm", source("components.battery.esr_ohm")),
        "regulator_output_v": (numeric("regulator.output_voltage_v"), "V", source("regulator.output_voltage_v")),
        "regulator_efficiency": (numeric("regulator.efficiency"), "fraction", source("regulator.efficiency")),
        "regulator_quiescent_ma": (numeric("regulator.quiescent_current_a") * 1000, "mA", source("regulator.quiescent_current_a") + "; converted A to mA"),
        "regulator_output_resistance_ohm": (numeric("regulator.effective_output_resistance_ohm"), "ohm", source("regulator.effective_output_resistance_ohm")),
        "output_capacitance_f": (numeric("capacitors.rail_output_f"), "F", source("capacitors.rail_output_f")),
        "brownout_threshold_v": (numeric("gate.provisional_limits.minimum_rail_voltage_v"), "V", source("gate.provisional_limits.minimum_rail_voltage_v")),
        "temperature_c": (numeric("power_profiles.temperature_c"), "degC", source("power_profiles.temperature_c")),
        "pwl_edge_s": (numeric("power_profiles.pwl_edge_s"), "s", source("power_profiles.pwl_edge_s")),
    }
    # The sleep baseline includes the low-power IMU, sleeping radio, and
    # regulator IQ. MCU stop current is a separate state interval in the trace.
    idle = (numeric("components.imu.low_power_current_ma") +
            numeric("components.radio.sleep_current_ma") +
            values["regulator_quiescent_ma"][0])
    values["idle_current_ma"] = (idle, "mA", "; ".join((
        source("components.imu.low_power_current_ma"), source("components.radio.sleep_current_ma"),
        values["regulator_quiescent_ma"][2], "aggregate sleep baseline excludes MCU stop current")))
    return {"status": "ASSUMED", "model_status": "SIMULATED",
            "source_note": "Values projected from the canonical MVP2 hardware spec; no electrical measurements.",
            **{key: {"value": value, "unit": unit, "status": "ASSUMED", "source": provenance}
               for key, (value, unit, provenance) in values.items()}}


def generate_motion_profiles(path: Path, seed: int = 7, sample_rate_hz: float = 12.5,
                             samples_per_profile: int = 100) -> dict[str, Any]:
    """Generate synthetic sensor inputs for the virtual IMU, not animal data."""
    rng = random.Random(seed)
    names = ("STATIC", "WALK", "RUN", "IMPACT", "RANDOM_MOVEMENT")
    rows: list[dict[str, Any]] = []
    for profile_index, name in enumerate(names):
        for index in range(samples_per_profile):
            t = index / sample_rate_hz
            noise = lambda scale: rng.uniform(-scale, scale)
            if name == "STATIC":
                x, y, z = noise(8), noise(8), 1000 + noise(8)
            elif name == "WALK":
                x, y, z = 150 * math.sin(2 * math.pi * 1.5 * t), 60 * math.sin(2 * math.pi * 0.75 * t), 1000 + 90 * math.cos(2 * math.pi * 1.5 * t)
            elif name == "RUN":
                x, y, z = 420 * math.sin(2 * math.pi * 3.0 * t), 180 * math.sin(2 * math.pi * 1.5 * t), 1000 + 280 * math.cos(2 * math.pi * 3.0 * t)
            elif name == "IMPACT":
                pulse = 1800.0 if index == samples_per_profile // 2 else 0.0
                x, y, z = pulse + noise(12), noise(12), 1000 + pulse + noise(12)
            else:
                x, y, z = rng.uniform(-1500, 1500), rng.uniform(-1500, 1500), rng.uniform(-500, 2500)
            rows.append({"profile": name, "sample_index": index, "timestamp_s": round(t, 6),
                         "x_mg": round(x), "y_mg": round(y), "z_mg": round(z),
                         "sample_rate_hz": sample_rate_hz, "seed": seed,
                         "status": "SIMULATED", "animal_measurement": False})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return {"status": "COMPLETED", "result_class": "SIMULATED", "profiles": list(names),
            "sample_rate_hz": sample_rate_hz, "samples_per_profile": samples_per_profile,
            "seed": seed, "path": str(path), "physical_hardware_used": False}


def _run_command(name: str, command: list[str], cwd: Path, timeout_s: int = 120) -> dict[str, Any]:
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                                timeout=timeout_s, check=False)
    except FileNotFoundError:
        return {"status": "NOT_AVAILABLE", "detail": f"command not found: {command[0]}", "required": True}
    except subprocess.TimeoutExpired as exc:
        return {"status": "TIMED_OUT", "detail": str(exc), "required": True}
    return {"status": "PASSED" if result.returncode == 0 else "FAILED",
            "return_code": result.returncode, "stdout": result.stdout[-12000:],
            "stderr": result.stderr[-12000:], "command": command, "required": True}


def _write_empty_csv(path: Path, fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.DictWriter(stream, fieldnames=fields, lineterminator="\n").writeheader()


def _metrics_csv(path: Path, stages: dict[str, dict[str, Any]]) -> None:
    rows = []
    for stage_name, result in stages.items():
        rows.append({"metric": f"stage.{stage_name}", "value": result.get("status"), "unit": "status",
                     "provenance": result.get("result_class", "ENVIRONMENT_OR_TEST_RESULT"),
                     "notes": result.get("detail", "")})
        for check in result.get("checks", []):
            rows.append({"metric": f"{stage_name}.{check.get('name', 'check')}",
                         "value": check.get("value", check.get("passed")),
                         "unit": check.get("unit", "boolean"), "provenance": check.get("status", "SIMULATED"),
                         "notes": check.get("source", "")})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["metric", "value", "unit", "provenance", "notes"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _report(spec: dict[str, Any], summary: dict[str, Any]) -> str:
    gate = summary["gate"]
    stages = summary["stages"]
    power = stages.get("power", {})
    charge = power.get("modeled_charge_uah")
    event_charge = power.get("event_charge", [])
    largest_event = max(event_charge, key=lambda row: row.get("charge_uah", 0), default=None)
    energy_answer = (f"`{charge:.6g} µAh` pela integração SIMULATED de correntes ASSUMED/trace; "
                    f"ngspice: {power.get('ngspice_status', 'NOT_RUN')}." if charge is not None else
                    "Sem integração disponível; conferir o estágio power e seus bloqueadores.")
    largest_answer = (f"`{largest_event['event']}` / `{largest_event['component']}` "
                      f"({largest_event['charge_uah']:.6g} µAh) na janela simulada."
                      if largest_event else "Sem breakdown disponível.")
    lines = [
        "# RIOSE MVP 2 — Digital twin report", "",
        f"**Gate: {gate['state']}**", "",
        "Este relatório descreve um fluxo digital e SIMULATED. Nenhum hardware físico, laboratório ou medição foi usado. READY significaria apenas plausibilidade digital para justificar a fabricação do primeiro protótipo.", "",
        "## Execução", "",
        f"- Spec SHA-256: `{summary['spec_sha256']}`",
        f"- Plataforma: `{summary['environment']['platform']}`",
        f"- Parâmetros por status: `{json.dumps(summary['parameter_statuses'], sort_keys=True)}`",
        f"- GPU: `{json.dumps(summary['environment']['gpu'], sort_keys=True)}`", "",
        "## Estágios", "",
        "| Estágio | Status | Evidência/limitação |", "|---|---|---|",
    ]
    for name, result in stages.items():
        detail = str(result.get("detail", result.get("notes", ""))).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {name} | {result.get('status', 'UNKNOWN')} | {detail} |")
    lines += ["", "## Gate e bloqueadores", ""]
    if gate["blockers"]:
        lines += [f"- {item}" for item in gate["blockers"]]
    else:
        lines.append("Nenhum bloqueador digital registrado.")
    lines += ["", "## Respostas técnicas", "",
              "1. Estabilidade do firmware: depende da execução Renode; testes C host são reportados separadamente.",
              "2. Coerência dos periféricos virtuais: depende de Renode; comparar com os modelos C do MVP1.",
              f"3. Energia digital estimada na janela observada: {energy_answer}",
              "4. Estabilidade do rail: sem resultado se ngspice não executar; nenhuma queda física é inferida.",
              f"5. Evento com maior carga integrada: {largest_answer}",
              "6. A antena cabe: envelope mecânico inicial ASSUMED; revisar saída CAD.",
              "7. Frequência de ressonância/S11: somente solver openEMS; null quando indisponível.",
              "8. Degradação por PCB/bateria/carcaça/animal: somente comparação openEMS; aproximação animal ASSUMED.",
              "9. Encaixe físico digital: estimativa geométrica; envelope ainda não aprovado.",
              "10. Falhas encontradas: ver failures.csv e status dos testes; estágio ausente não significa sucesso.",
              "11. Hipóteses a revisar: todos os valores ASSUMED e limites do modelo listados na spec.",
              "12. Parâmetros ASSUMED: consultar hardware/spec.yaml e provenance exportada.",
              "13. Sem hardware real não são validados consumo, brownout, potência RF, sintonia, materiais ou comportamento animal.",
              "14. Este gate não é validação comercial, clínica ou de campo.", "",
              "## Integridade da evidência", "",
              "Nenhum campo MEASURED é permitido na spec do MVP2. Capacidades GPU são metadados de ambiente e o experimento Sionna é opcional.", ""]
    return "\n".join(lines)


def run_twin(spec_path: Path, output: Path, seed: int = 7) -> dict[str, Any]:
    spec, spec_hash = load_spec(spec_path)
    output.mkdir(parents=True, exist_ok=True)
    dirs = {name: output / name for name in ("firmware", "power", "antenna", "mechanical", "integration")}
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    env = preflight()
    dump_json(dirs["integration"] / "preflight.json", env)
    motion = generate_motion_profiles(dirs["firmware"] / "motion_profiles.csv", seed=seed)

    stages: dict[str, dict[str, Any]] = {
        "synthetic_motion": motion,
        "gpu_optional": {**env["gpu"], "required": False, "result_class": "ENVIRONMENT_CAPABILITY_ONLY"},
        "zephyr_firmware": {"status": "NOT_AVAILABLE", "required": True,
                            "detail": "Zephyr SDK/workspace is not configured; host C tests do not validate the Zephyr target"},
        "long_duration_1_7_30_days": {"status": "NOT_AVAILABLE", "required": True,
                                      "detail": "Accelerated virtual-time execution for 1/7/30 days is not implemented in the available host harness"},
        "adversarial_fault_injection": {"status": "NOT_AVAILABLE", "required": True,
                                        "detail": "Fault injection requires the Renode peripheral platform/backend, unavailable in this environment"},
        "four_power_scenarios": {"status": "NOT_AVAILABLE", "required": True,
                                 "detail": "Only one host-harness trace is available; NORMAL/ACTIVE/ALERT/WORST_REASONABLE_CASE must run through the FSM before energy comparison"},
    }

    # Run the preserved host integration tests; they validate software models, not Renode or electronics.
    c_tests = _run_command("mvp1_c_tests", ["make", "hardware-test"], ROOT, timeout_s=300)
    c_tests["result_class"] = "SIMULATED_SOFTWARE_TESTS"
    stages["mvp1_c_tests"] = c_tests

    if env["commands"].get("renode") and env["commands"].get("renode-test"):
        checker = ROOT / "hardware" / "renode" / "scripts" / "check_tools.py"
        if checker.exists():
            check = _run_command("renode_smoke", [sys.executable, str(checker)], ROOT, timeout_s=60)
            check["detail"] = check.get("stdout", "")[-1000:]
            stages["renode_firmware"] = check
        else:
            stages["renode_firmware"] = {"status": "NOT_AVAILABLE", "required": True,
                                           "detail": "Renode platform/check script is absent"}
    else:
        stages["renode_firmware"] = {"status": "NOT_AVAILABLE", "required": True,
                                      "detail": "Renode and renode-test are required for the MCU/bus twin"}

    # The host firmware trace export is optional until the C harness trace sink is built.
    trace_path = dirs["firmware"] / "firmware_trace.jsonl"
    hardware_bin = Path("/tmp/cattle-rf-hardware-tests/hardware_integration")
    if c_tests["status"] == "PASSED" and hardware_bin.exists():
        trace_env = os.environ.copy()
        trace_env["RIOSE_TRACE_OUTPUT"] = str(trace_path)
        trace_run = subprocess.run([str(hardware_bin)], cwd=ROOT, env=trace_env,
                                   capture_output=True, text=True, timeout=120, check=False)
        stages["host_trace_export"] = {"status": "PASSED" if trace_run.returncode == 0 and trace_path.exists() else "NOT_AVAILABLE",
                                       "required": False, "result_class": "SIMULATED_SOFTWARE_TRACE",
                                       "stdout": trace_run.stdout[-3000:], "stderr": trace_run.stderr[-3000:],
                                       "path": str(trace_path)}
    else:
        stages["host_trace_export"] = {"status": "NOT_AVAILABLE", "required": False,
                                       "detail": "C harness trace exporter not available"}

    mechanical_report = dirs["mechanical"] / "geometry.json"
    mechanical_cmd = [sys.executable, str(ROOT / "hardware" / "mechanical" / "model.py"),
                      "--spec", str(spec_path), "--output", str(mechanical_report)]
    if env["modules"].get("cadquery"):
        mechanical_cmd += ["--step", str(dirs["mechanical"] / "ear_tag_assumed.step")]
    if (ROOT / "hardware" / "mechanical" / "model.py").exists():
        mech = _run_command("mechanical", mechanical_cmd, ROOT, timeout_s=120)
        if mechanical_report.exists():
            geometry = json.loads(mechanical_report.read_text())
            mech["checks"] = [{"name": "envelope_fit", "passed": geometry.get("fit", {}).get("fits"),
                               "status": "SIMULATED", "value": geometry.get("fit", {}).get("issues")}]
            mech["detail"] = "; ".join(geometry.get("fit", {}).get("issues", [])) or "Bounding-box fit estimate completed"
            mech["status"] = "COMPLETED" if geometry.get("fit", {}).get("fits") else "FAILED"
            mech["result_class"] = "SIMULATED_GEOMETRY_ESTIMATE"
            if not geometry.get("cadquery_available"):
                mech["status"] = "NOT_AVAILABLE"
                mech["detail"] += "; CadQuery STEP export unavailable"
        stages["mechanical"] = mech
    else:
        stages["mechanical"] = {"status": "NOT_AVAILABLE", "required": True,
                                 "detail": "Mechanical model implementation is absent"}

    antenna_cmd = [sys.executable, "-m", "hardware.antenna.run", "--spec", str(spec_path),
                   "--output", str(dirs["antenna"])]
    ant = _run_command("antenna", antenna_cmd, ROOT, timeout_s=1800)
    antenna_manifest = dirs["antenna"] / "antenna_experiments.json"
    if antenna_manifest.exists():
        ant_json = json.loads(antenna_manifest.read_text())
        ant["status"] = "COMPLETED" if ant_json.get("status") == "COMPLETED" else ant_json.get("status", "NOT_AVAILABLE")
        ant["result_class"] = ant_json.get("result_class")
        ant["detail"] = ant_json.get("limitations", [""])[0]
    stages["antenna"] = ant

    power_summary = dirs["power"] / "summary.json"
    if trace_path.exists() and (ROOT / "hardware" / "spice" / "trace_adapter.py").exists():
        loads_path = dirs["power"] / "assumed_load_profile.json"
        dump_json(loads_path, _power_load_profile(spec))
        power_assumptions_path = dirs["power"] / "assumptions.json"
        dump_json(power_assumptions_path, _power_assumptions(spec))
        adapter = [sys.executable, str(ROOT / "hardware" / "spice" / "trace_adapter.py"),
                   str(trace_path), "--loads", str(loads_path), "--output", str(dirs["power"] / "schedule.jsonl")]
        adapted = _run_command("trace_schedule", adapter, ROOT, timeout_s=120)
        stages["trace_schedule"] = adapted
        schedule_path = dirs["power"] / "schedule.jsonl"
        if adapted["status"] == "PASSED" and schedule_path.exists():
            power_cmd = [sys.executable, str(ROOT / "hardware" / "spice" / "mvp2_power.py"),
                         str(schedule_path), "--assumptions", str(power_assumptions_path),
                         "--output", str(dirs["power"])]
            power = _run_command("power", power_cmd, ROOT, timeout_s=1800)
            if power_summary.exists():
                power_json = json.loads(power_summary.read_text())
                power["ngspice_status"] = power_json.get("ngspice", {}).get("status", "UNKNOWN")
                power["modeled_charge_uah"] = power_json.get("total_charge_mah_window", 0) * 1000
                power["event_charge"] = power_json.get("event_charge", [])
                power["modeled_window_s"] = power_json.get("modeled_window_s")
                power["status"] = "COMPLETED" if power["ngspice_status"] == "EXECUTED" else "NOT_AVAILABLE"
                if power["status"] == "NOT_AVAILABLE":
                    power["detail"] = "Assumed-current charge integration completed; ngspice rail simulation was not executed"
                power["result_class"] = "SIMULATED"
            stages["power"] = power
        else:
            stages["power"] = {"status": "NOT_AVAILABLE", "required": True,
                                "detail": "Trace could not be converted to an event schedule"}
    else:
        stages["power"] = {"status": "NOT_AVAILABLE", "required": True,
                            "detail": "A firmware trace and trace-to-power adapter are required; no synthetic schedule substituted"}

    failures: list[dict[str, Any]] = []
    not_run_faults = (
        "SPI_TIMEOUT", "I2C_TIMEOUT", "SX1262_BUSY_STUCK", "IRQ_MISSING", "IMU_FAILURE",
        "CORRUPT_TELEMETRY", "BATTERY_VOLTAGE_DROP", "HIGH_ESR", "REGULATOR_INSTABILITY",
        "WATCHDOG_RESET", "UNEXPECTED_REBOOT",
    )
    failures.extend({"scenario": "adversarial_fault_injection", "failure": case,
                     "detail": "NOT_RUN: Renode backend/toolchain is unavailable",
                     "status": "NOT_RUN"} for case in not_run_faults)
    failures.extend({"scenario": f"long_duration_{days}_days", "failure": "virtual_time_not_executed",
                     "detail": "NOT_RUN: accelerated long-duration backend is unavailable",
                     "status": "NOT_RUN"} for days in (1, 7, 30))
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
        _write_empty_csv(antenna_csv, ["scenario", "status", "resonant_frequency_hz", "s11_min_db", "input_impedance_real_ohm", "input_impedance_imag_ohm", "vswr_min", "efficiency_fraction", "gain_dbi", "radiation_pattern_path"])
    with (output / "failures.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = ["scenario", "failure", "detail", "status"]
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(failures)

    gate = evaluate_gate(spec, stages)
    summary = {"schema_version": "riose.mvp2.digital-twin/v1", "milestone": "MVP2_DIGITAL_TWIN",
               "result_class": "SIMULATED", "spec_path": str(spec_path), "spec_sha256": spec_hash,
               "parameter_statuses": parameter_statuses(spec), "environment": env, "stages": stages,
               "gate": gate, "outputs": {"root": str(output), "firmware": str(dirs["firmware"]),
                         "power": str(dirs["power"]), "antenna": str(dirs["antenna"]),
                         "mechanical": str(dirs["mechanical"]), "integration": str(dirs["integration"]),
                         "failures_csv": str(output / "failures.csv")},
               "physical_measurements_used": False, "gpu_issue": "OPTIONAL_GPU_EXPERIMENT"}
    dump_json(output / "summary.json", summary)
    _metrics_csv(output / "metrics.csv", stages)
    (ROOT / "docs" / "mvp2-digital-twin-report.md").write_text(_report(spec, summary), encoding="utf-8")
    dump_json(dirs["integration"] / "summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m riose.digital_twin", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight", help="report headless toolchain/GPU availability")
    validate = sub.add_parser("validate-spec", help="validate hardware parameters and provenance")
    validate.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    run = sub.add_parser("run", help="run available digital-twin stages and generate report")
    run.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    run.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    run.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    if args.command == "preflight":
        print(json.dumps(preflight(), indent=2, sort_keys=True))
        return 0
    if args.command == "validate-spec":
        try:
            spec, digest = load_spec(args.spec)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        print(json.dumps({"status": "VALID", "sha256": digest, "parameter_statuses": parameter_statuses(spec)}, sort_keys=True))
        return 0
    try:
        summary = run_twin(args.spec, args.output, args.seed)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"digital twin run failed before report generation: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "REPORT_GENERATED", "gate": summary["gate"]["state"],
                      "blockers": summary["gate"]["blockers"], "output": str(args.output)}, sort_keys=True))
    return 1 if summary["gate"]["state"] == "NOT_READY_FOR_PHYSICAL_PROTOTYPE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
