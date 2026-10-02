"""Projection of canonical ear-tag assumptions into analysis inputs."""

from __future__ import annotations

from typing import Any

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
        "regulator_dropout_v": (numeric("regulator.dropout_headroom_v"), "V", source("regulator.dropout_headroom_v")),
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
