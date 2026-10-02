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
import re
import shutil
import subprocess
import sys
from importlib import metadata
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


def _version_matches(expected: str | None, observed: str | None) -> bool | None:
    if not expected or not observed:
        return None
    expected_token = re.search(r"\d+(?:\.\d+)+(?:[-.]?(?:rc|a|b|dev)\d+)?", expected, re.I)
    observed_token = re.search(r"\d+(?:\.\d+)+(?:[-.]?(?:rc|a|b|dev)\d+)?", observed, re.I)
    if not expected_token or not observed_token:
        return expected in observed
    expected_value = expected_token.group(0).lower().replace("-", "")
    observed_value = observed_token.group(0).lower().replace("-", "")
    if expected.endswith(".x"):
        return observed_value.startswith(expected_value)
    return observed_value == expected_value


def preflight() -> dict[str, Any]:
    toolchain_path = ROOT / "hardware" / "toolchain.json"
    toolchain = json.loads(toolchain_path.read_text(encoding="utf-8"))
    commands = {name: shutil.which(name) for name in (
        "python3", "uv", "micromamba", "ninja", "west", "renode", "renode-test",
        "ngspice", "openEMS", "openscad",
    )}
    modules = {name: _module_available(name) for name in ("yaml", "cadquery", "openEMS", "CSXCAD", "torch", "sionna")}
    distributions = {"yaml": "PyYAML", "cadquery": "cadquery", "openEMS": "openEMS",
                     "CSXCAD": "CSXCAD", "torch": "torch", "sionna": "sionna"}
    module_versions: dict[str, str | None] = {}
    for module, distribution in distributions.items():
        try:
            module_versions[module] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            module_versions[module] = None
    try:
        from hardware.antenna.capabilities import detect_capabilities
        gpu = detect_capabilities()
    except (ImportError, OSError):
        gpu = {"GPU_AVAILABLE": False, "GPU_TYPE": "UNKNOWN", "CUDA_AVAILABLE": False,
               "SIONNA_AVAILABLE": False, "status": "UNAVAILABLE", "experiment": "OPTIONAL_GPU_EXPERIMENT"}
    versions: dict[str, dict[str, Any]] = {}
    version_args = {
        "python3": ["--version"], "uv": ["--version"], "micromamba": ["--version"],
        "ninja": ["--version"], "west": ["--version"], "renode": ["--version"],
        # Renode's Robot wrapper has no --version flag; --help is its clean probe.
        "renode-test": ["--help"], "ngspice": ["--version"], "openEMS": ["--help"],
    }
    expected_commands = {
        "python3": toolchain.get("host", {}).get("python"),
        "uv": toolchain.get("host", {}).get("uv"),
        "micromamba": toolchain.get("host", {}).get("micromamba"),
        "ninja": toolchain.get("host", {}).get("ninja"),
        "west": toolchain.get("host", {}).get("west"),
        **toolchain.get("optional_external", {}),
    }
    for name, executable in commands.items():
        expected = expected_commands.get(name)
        if not executable:
            versions[name] = {"status": "NOT_AVAILABLE", "expected": expected,
                              "matches_expected": None}
            continue
        args = version_args.get(name)
        if not args:
            versions[name] = {"status": "PATH_ONLY", "path": executable,
                              "expected": expected, "matches_expected": None}
            continue
        try:
            result = subprocess.run([executable, *args], capture_output=True, text=True,
                                    timeout=5, check=False)
            output = (result.stdout or result.stderr).strip().splitlines()
            observed = next((line for line in output if _version_matches(expected, line) is True),
                            output[0] if output else None)
            matches = (None if result.returncode != 0 else _version_matches(expected, observed))
            versions[name] = {"status": "AVAILABLE" if result.returncode == 0 else "VERSION_PROBE_FAILED",
                              "path": executable, "version": observed, "expected": expected,
                              "matches_expected": matches, "return_code": result.returncode}
        except (OSError, subprocess.TimeoutExpired) as exc:
            versions[name] = {"status": "VERSION_PROBE_FAILED", "path": executable,
                              "expected": expected, "matches_expected": None, "detail": str(exc)}
    expected_modules = toolchain.get("optional_external", {})
    for module in modules:
        expected = expected_modules.get(module)
        observed = module_versions.get(module)
        versions[f"module:{module}"] = {
            "status": "AVAILABLE" if modules[module] else "NOT_AVAILABLE",
            "version": observed, "expected": expected,
            "matches_expected": _version_matches(expected, observed),
        }
    zephyr_base = os.environ.get("ZEPHYR_BASE")
    expected_zephyr = toolchain.get("host", {}).get("zephyr")
    zephyr_version: str | None = None
    if zephyr_base:
        version_file = Path(zephyr_base) / "VERSION"
        if version_file.is_file():
            fields = {}
            for line in version_file.read_text(encoding="utf-8").splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    fields[key.strip()] = value.strip()
            if all(key in fields for key in ("VERSION_MAJOR", "VERSION_MINOR", "PATCHLEVEL")):
                zephyr_version = ".".join(fields[key] for key in ("VERSION_MAJOR", "VERSION_MINOR", "PATCHLEVEL"))
    versions["zephyr"] = {"status": "AVAILABLE" if zephyr_version else "NOT_CONFIGURED",
                           "path": zephyr_base, "version": zephyr_version, "expected": expected_zephyr,
                           "matches_expected": (str(expected_zephyr) in zephyr_version if zephyr_version else None)}
    sdk_expected = toolchain.get("host", {}).get("zephyr_sdk")
    sdk_root = os.environ.get("ZEPHYR_SDK_INSTALL_DIR")
    if not sdk_root and sdk_expected:
        candidate = Path.home() / ".local" / "opt" / f"zephyr-sdk-{sdk_expected}"
        if candidate.is_dir():
            sdk_root = str(candidate)
    sdk_version_file = Path(sdk_root) / "sdk_version" if sdk_root else None
    sdk_version = sdk_version_file.read_text(encoding="utf-8").strip() if sdk_version_file and sdk_version_file.is_file() else None
    versions["zephyr_sdk"] = {"status": "AVAILABLE" if sdk_version else "NOT_AVAILABLE",
                               "path": sdk_root, "version": sdk_version, "expected": sdk_expected,
                               "matches_expected": (sdk_version == str(sdk_expected) if sdk_version else None)}
    return {"status": "ENVIRONMENT_PROBE_ONLY", "platform": platform.platform(),
            "python": sys.version.split()[0], "commands": commands, "modules": modules,
            "module_versions": module_versions, "versions": versions, "toolchain_manifest": str(toolchain_path),
            "gpu": gpu,
            "physical_hardware_used": False}


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


def _run_command(name: str, command: list[str], cwd: Path, timeout_s: int = 120,
                 env: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                                timeout=timeout_s, check=False, env=env)
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
    long_runs = stages.get("long_duration_1_7_30_days", {})
    fault_stage = stages.get("adversarial_fault_injection", {})
    mechanical = stages.get("mechanical", {})
    antenna = stages.get("antenna", {})
    antenna_rows = antenna.get("scenarios", [])
    failed_checks = mechanical.get("fit", {}).get("issues", [])
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
              f"1. Estabilidade do firmware: long runs C host `{long_runs.get('status', 'NOT_RUN')}`; Zephyr `{stages.get('zephyr_firmware', {}).get('status', 'NOT_RUN')}`.",
              f"2. Coerência dos periféricos virtuais: Renode `{stages.get('renode_firmware', {}).get('status', 'NOT_RUN')}`; {stages.get('renode_firmware', {}).get('detail', 'firmware/backend unavailable')}.",
              f"3. Energia digital estimada na janela observada: {energy_answer}",
              f"4. Estabilidade do rail: ngspice `{power.get('ngspice_status', 'NOT_RUN')}`; sem medição física ou resultado de rail quando não executado.",
              f"5. Evento com maior carga integrada: {largest_answer}",
              f"6. A antena cabe: análise geométrica `{mechanical.get('status', 'NOT_RUN')}`; {('; '.join(failed_checks) if failed_checks else 'sem conflito de envelope reportado')}.",
              f"7. Frequência de ressonância/S11: openEMS `{antenna.get('status', 'NOT_RUN')}`; os campos permanecem nulos sem solver.",
              f"8. Degradação por PCB/bateria/carcaça/animal: {len(antenna_rows)} cenários listados; resultados exigem openEMS; aproximação animal é experimental.",
              f"9. Encaixe físico digital: `{'PASS' if mechanical.get('fit', {}).get('fits') else 'BLOCKED'}`; CadQuery disponível `{mechanical.get('cadquery_available', False)}`.",
              f"10. Falhas encontradas: {summary.get('failure_count', 'ver failures.csv')} entradas; falhas de host cobertas `{', '.join(fault_stage.get('completed_host_cases', []))}`; pendentes `{', '.join(fault_stage.get('pending_cases', []))}`.",
              "11. Hipóteses a revisar: parâmetros ASSUMED e limites provisórios em hardware/spec.yaml; dimensões, antena e encaixe aguardam aprovação.",
              f"12. Parâmetros por status: `{json.dumps(summary['parameter_statuses'], sort_keys=True)}`; provenance completa na spec.",
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
    c_tests = _run_command("mvp1_c_tests", ["make", "hardware-test"], ROOT, timeout_s=300)
    c_tests["result_class"] = "SIMULATED_SOFTWARE_TESTS"
    stages["mvp1_c_tests"] = c_tests

    zephyr_base = os.environ.get("ZEPHYR_BASE")
    if env["commands"].get("west") and zephyr_base and Path(zephyr_base).is_dir():
        zephyr_build = _run_command("zephyr_build", [env["commands"]["west"], "build",
            "-b", "nucleo_l031k6", str(ROOT / "hardware" / "firmware" / "zephyr"),
            "-d", str(dirs["firmware"] / "zephyr-build")], ROOT, timeout_s=1800)
        elf = dirs["firmware"] / "zephyr-build" / "zephyr" / "zephyr.elf"
        if elf.is_file():
            zephyr_elf = elf
        stages["zephyr_firmware"] = {**zephyr_build,
            "status": "PASSED" if zephyr_build["status"] == "PASSED" and elf.is_file() else "FAILED",
            "required": True, "elf": str(elf), "detail": "Built target firmware for nucleo_l031k6" if elf.is_file()
            else "west build did not produce the expected Zephyr ELF"}
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
    hardware_bin = Path("/tmp/cattle-rf-hardware-tests/hardware_integration")
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

    # The C integration executable covers transient host-model faults. Persistent
    # Renode pin/bus faults and analog rail/reset injection stay explicit blockers.
    host_faults = ["one_shot_i2c_failure_recovery", "one_shot_spi_failure_recovery",
                   "late_tx_done_timeout_recovery"]
    remaining_faults = ["sx1262_busy_stuck", "irq_missing", "crc_corruption",
                        "battery_voltage_drop", "high_esr", "regulator_instability",
                        "watchdog_reset", "unexpected_reboot"]
    stages["adversarial_fault_injection"] = {
        "status": "PARTIAL" if c_tests["status"] == "PASSED" else "NOT_AVAILABLE",
        "required": True, "completed_host_cases": host_faults if c_tests["status"] == "PASSED" else [],
        "pending_cases": remaining_faults,
        "detail": "Host C models cover transient I2C/SPI/TX timeout recovery; persistent pin and analog power faults require Renode or electrical models",
    }

    mechanical_report = dirs["mechanical"] / "geometry.json"
    mechanical_cmd = [sys.executable, str(ROOT / "hardware" / "mechanical" / "model.py"),
                      "--spec", str(spec_path), "--output", str(mechanical_report)]
    if env["modules"].get("cadquery"):
        mechanical_cmd += ["--step", str(dirs["mechanical"] / "ear_tag_assumed.step"),
                           "--stl", str(dirs["mechanical"] / "ear_tag_assumed.stl")]
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
        ant["scenarios"] = ant_json.get("scenarios", [])
    stages["antenna"] = ant

    power_scenarios: dict[str, dict[str, Any]] = {}
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
                power_scenarios[scenario] = {"status": "NOT_AVAILABLE", "detail": "Trace conversion failed"}
                continue
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
        stages["trace_schedule"] = {"status": "PASSED" if len(power_scenarios) == 4 else "FAILED",
                                     "required": True, "scenarios": list(power_scenarios)}
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
