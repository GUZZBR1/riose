#!/usr/bin/env python3
"""Reproducible 24-hour current budget from editable component assumptions."""
import argparse
import csv
import json
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "power_profile.json"


def calculate(config: dict, capacity_override=None):
    n = int(config["tx_count_per_day"])
    tx_s = float(config["tx_duration_s"])
    awake_s = float(config["mcu_awake_s_per_beacon"])
    rx_s = float(config["rx_window_s_per_beacon"])
    seconds = {"RF_TX": n * tx_s, "RF_RX": n * rx_s,
               "MCU_ACTIVE": n * awake_s}
    seconds["DEEP_SLEEP"] = 86400.0 - sum(seconds.values())
    if seconds["DEEP_SLEEP"] < 0:
        raise ValueError("Configured per-beacon durations exceed 24 hours")

    c = config["components"]
    sleep_ma = c["mcu_stop"]["current_ma"] + c["radio_sleep"]["current_ma"] + c["imu_low_power"]["current_ma"]
    active_ma = c["mcu_run"]["current_ma"] + c["imu_low_power"]["current_ma"]
    tx_ma = c["radio_tx"]["current_ma"] + active_ma
    rx_ma = c["radio_rx"]["current_ma"] + active_ma
    state_current = {"DEEP_SLEEP": sleep_ma, "MCU_ACTIVE": active_ma,
                     "RF_TX": tx_ma, "RF_RX": rx_ma}
    rows = []
    for state in ("DEEP_SLEEP", "MCU_ACTIVE", "RF_TX", "RF_RX"):
        duration = seconds[state]
        current = state_current[state]
        rows.append({"state": state, "duration_s_day": duration,
                     "duration_h_day": duration / 3600,
                     "current_ma": current,
                     "charge_mah_day": current * duration / 3600,
                     "status": "MIXED_INPUTS_ASSUMED_AND_DATASHEET"})
    daily = sum(r["charge_mah_day"] for r in rows)
    capacity = capacity_override if capacity_override is not None else config.get("battery_capacity_mah")
    life_days = float(capacity) / daily if capacity is not None and daily > 0 else None
    return {
        "status": "SIMULATED",
        "assumptions_notice": config["notice"],
        "daily_charge_mah": daily,
        "average_current_ma": daily / 24,
        "peak_configured_current_ma": max(state_current.values()),
        "messages_per_day": n,
        "battery_capacity_mah": capacity,
        "estimated_battery_life_days": life_days,
        "estimated_battery_life_years": life_days / 365.25 if life_days is not None else None,
        "autonomy_status": "CALCULATED_FROM_EXPLICIT_CAPACITY" if life_days is not None else "NOT_CALCULATED_CAPACITY_UNCONFIGURED",
        "states": rows,
        "component_inputs": c,
    }


def spice_deck(config, output_dir: Path):
    c = config["components"]
    p = config["ngspice_pulse_model"]
    idle = c["mcu_stop"]["current_ma"] + c["radio_sleep"]["current_ma"] + c["imu_low_power"]["current_ma"]
    tx = c["radio_tx"]["current_ma"] + c["mcu_run"]["current_ma"] + c["imu_low_power"]["current_ma"]
    duration_ms = float(config["tx_duration_s"]) * 1000
    return f"""* Virtual cattle tag: battery + series impedance + reservoir capacitor + TX load
* SIMULATED. RBAT and Cbulk are configurable assumptions, not a selected cell model.
.param VBAT={float(config['battery_voltage_v'])}
.param RBAT={float(p['battery_internal_resistance_ohm'])}
.param CBULK={float(p['bulk_capacitance_f'])}
.param I_IDLE={idle / 1000:.12g}
.param I_TX={(tx / 1000):.12g}
.param T_TX={duration_ms / 1000:.9g}
Vcell source 0 DC {{VBAT}}
Vsense source battery 0
Rcell battery vtag {{RBAT}}
Cbulk vtag 0 {{CBULK}} IC={{VBAT}}
* One beacon pulse, representative transient only; daily charge is integrated by energy_model.py.
Iload vtag 0 PULSE({{I_IDLE}} {{I_TX}} 10m 10u 10u {{T_TX}} 1s)
.control
set noaskquit
set wr_singlescale
tran 10u 250m 0 10u uic
meas tran vtag_min MIN v(vtag) FROM=10m TO=140m
meas tran battery_peak MAX i(Vsense) FROM=10m TO=140m
quit
.endc
.end
"""


def write_outputs(result, output_dir: Path, config, ngspice_path=None):
    output_dir.mkdir(parents=True, exist_ok=True)
    deck = output_dir / "tag_power_pulse.cir"
    deck.write_text(spice_deck(config, output_dir))
    executable = ngspice_path or shutil.which("ngspice")
    result["ngspice"] = {"status": "NOT_AVAILABLE", "netlist": str(deck)}
    if executable:
        process = subprocess.run([executable, "-b", str(deck)], text=True,
                                  capture_output=True, check=False)
        log = process.stdout + process.stderr
        (output_dir / "ngspice.log").write_text(log)
        status = "EXECUTED" if process.returncode == 0 else "FAILED"
        record = {"status": status, "executable": Path(executable).name,
                  "version": "ngspice 42" if "ngspice-42" in log else "not identified",
                  "return_code": process.returncode, "netlist": deck.name,
                  "log": "ngspice.log",
                  "run_command": "ngspice -b tag_power_pulse.cir (from this results directory)"}
        match = re.search(r"vtag_min\s*=\s*([-+0-9.eE]+)", log, re.IGNORECASE)
        if match:
            record["minimum_tag_voltage_v"] = float(match.group(1))
            record["brownout_threshold_v"] = config["ngspice_pulse_model"]["brownout_threshold_v"]
            record["below_configured_brownout"] = record["minimum_tag_voltage_v"] < record["brownout_threshold_v"]
        result["ngspice"] = record
    (output_dir / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    with (output_dir / "energy_24h.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=result["states"][0].keys())
        writer.writeheader()
        writer.writerows(result["states"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=ROOT / "results")
    parser.add_argument("--capacity-mah", type=float,
                        help="Only set when a battery capacity is explicitly selected/configured")
    parser.add_argument("--ngspice", type=str,
                        help="ngspice binary (auto-detected on PATH when omitted)")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if args.capacity_mah is not None and args.capacity_mah <= 0:
        parser.error("--capacity-mah must be positive")
    result = calculate(config, args.capacity_mah)
    write_outputs(result, args.output, config, args.ngspice)
    print(f"status={result['status']}")
    print(f"daily_charge_mah={result['daily_charge_mah']:.6f}")
    print(f"average_current_ma={result['average_current_ma']:.6f}")
    print(f"messages_per_day={result['messages_per_day']}")
    print(f"autonomy_status={result['autonomy_status']}")
    print(f"ngspice_status={result['ngspice']['status']}")
    if "minimum_tag_voltage_v" in result["ngspice"]:
        print(f"ngspice_minimum_tag_voltage_v={result['ngspice']['minimum_tag_voltage_v']:.6f}")
    if result["estimated_battery_life_days"] is not None:
        print(f"estimated_battery_life_days={result['estimated_battery_life_days']:.3f}")
    print(f"outputs={args.output.resolve()}")


if __name__ == "__main__":
    main()
