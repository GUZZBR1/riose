#!/usr/bin/env python3
"""Sweep a configurable TLL-5902/TPS62840 candidate transient model."""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_PROFILE = ROOT / "profile.json"


def render_deck(profile: dict, battery_voltage_v: float, esr_ohm: float, rail_cap_f: float) -> str:
    batt = profile["battery"]
    reg = profile["regulator"]
    load = profile["load"]
    caps = profile["capacitors"]
    sim = profile["simulation"]

    eff = float(reg["efficiency_assumption"])
    vbat = battery_voltage_v
    vout = float(reg["output_voltage_v"])
    iq = float(reg["quiescent_current_a"])
    sleep_a = float(load["sleep_load_current_ma"]) / 1000
    tx_a = (float(load["tx_radio_current_ma"]) + float(load["mcu_active_current_ma"])
            + float(load["imu_low_power_current_ma"])) / 1000
    rx_a = (float(load["rx_radio_current_ma"]) + float(load["mcu_active_current_ma"])
            + float(load["imu_low_power_current_ma"])) / 1000
    tx_s = float(load["tx_duration_s"])
    rx_s = float(load["rx_duration_s"])
    rise = float(load["tx_rise_time_s"])
    fall = float(load["tx_fall_time_s"])
    tx_start = 0.010
    tx_end = tx_start + tx_s
    rx_start = tx_end + 0.001
    rx_end = rx_start + rx_s
    # The cell-side behavioral source uses instantaneous modeled cell voltage
    # for an averaged power conversion estimate; it is not a switching model.
    step = float(sim["time_step_s"])
    stop = float(sim["stop_time_s"])
    return f"""* TLL-5902 + TPS62840 candidate transient; SIMULATED, averaged converter model.
* Battery ESR, converter efficiency/dynamics and capacitors are sweep assumptions.
.param VBAT={vbat:.9g}
.param RBAT={esr_ohm:.9g}
.param VOUT={vout:.9g}
.param EFF={eff:.9g}
.param VDROP={float(reg['dropout_assumption_v']):.9g}
.param RREG={float(reg['effective_output_resistance_ohm']):.9g}
.param CBAT={float(caps['battery_side_f']):.9g}
.param ESRBATCAP={float(caps['battery_side_esr_ohm']):.9g}
.param COUT={rail_cap_f:.9g}
.param ESROUT={float(caps['rail_output_esr_ohm']):.9g}
.param VMIN={float(sim['minimum_functional_rail_v']):.9g}
Vcell source 0 DC {{VBAT}}
Vsense source battery 0
Rcell battery raw {{RBAT}}
Resrb raw batcap {{ESRBATCAP}}
Cbat batcap 0 {{CBAT}} IC={{VBAT}}
* Simplified buck control: regulated setpoint while input headroom remains,
* then output follows input minus assumed dropout. No switching ripple/control loop.
Breg reg_target 0 V={{min(VOUT,max(0,V(raw)-VDROP))}}
Rreg reg_target pre_rail {{RREG}}
Resrout pre_rail rail {{ESROUT}}
Cout rail 0 {{COUT}} IC={{VOUT}}
* Output profile is represented as a behavioral voltage in amperes.
Vprofile profile 0 PWL(0 {sleep_a:.12g} {tx_start:.9g} {sleep_a:.12g} {tx_start + rise:.9g} {tx_a:.12g} {tx_end - fall:.9g} {tx_a:.12g} {tx_end:.9g} {sleep_a:.12g} {rx_start:.9g} {rx_a:.12g} {rx_end:.9g} {rx_a:.12g} {rx_end + 0.001:.9g} {sleep_a:.12g} {stop:.9g} {sleep_a:.12g})
Bload rail 0 I={{V(profile)}}
* Average cell-side current from Pout/(Vcell_loaded*assumed efficiency) + Iq.
* This is not TPS62840 transistor-level behavior and excludes current limit.
Bconv raw 0 I={{VOUT*V(profile)/(max(V(raw),1e-6)*EFF)+{iq:.12g}}}
.control
set noaskquit
tran {step:.9g} {stop:.9g} 0 {step:.9g} uic
meas tran vbat_min MIN v(raw) FROM={tx_start:.9g} TO={rx_end:.9g}
meas tran vrail_min MIN v(rail) FROM={tx_start:.9g} TO={rx_end:.9g}
meas tran ibat_max MAX i(Vsense) FROM={tx_start:.9g} TO={rx_end:.9g}
meas tran vbat_tx_end FIND v(raw) AT={tx_end:.9g}
meas tran vrail_tx_end FIND v(rail) AT={tx_end:.9g}
quit
.endc
.end
"""


def measured(log: str, name: str) -> float | None:
    match = re.search(rf"^{re.escape(name)}\s*=\s*([-+0-9.eE]+)", log, re.MULTILINE | re.IGNORECASE)
    return float(match.group(1)) if match else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--output", type=Path, default=ROOT / "results")
    parser.add_argument("--ngspice", default=shutil.which("ngspice"),
                        help="ngspice executable; auto-detected when on PATH")
    parser.add_argument("--keep-decks", action="store_true",
                        help="keep every generated .cir deck and .log (default: keep summary and CSV only)")
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text())
    if not args.ngspice:
        parser.error("ngspice is unavailable; the profile is parameterized but cannot be executed")

    args.output.mkdir(parents=True, exist_ok=True)
    result_rows = []
    for vbat in profile["battery"]["input_voltage_sweep_v"]:
        for esr in profile["battery"]["esr_sweep_ohm"]:
            for cap in profile["capacitors"]["rail_output_sweep_f"]:
                label = f"v_{vbat:g}_esr_{esr:g}_cout_{cap * 1e6:g}uF".replace(".", "p")
                deck_path = args.output / f"{label}.cir"
                log_path = args.output / f"{label}.log"
                deck_path.write_text(render_deck(profile, float(vbat), float(esr), float(cap)))
                run = subprocess.run([args.ngspice, "-b", str(deck_path)], capture_output=True,
                                     text=True, check=False)
                log = run.stdout + run.stderr
                log_path.write_text(log)
                row = {
                    "status": "SIMULATED" if run.returncode == 0 else "FAILED",
                    "battery_model": profile["battery"]["model"],
                    "regulator_model": profile["regulator"]["model"],
                    "battery_input_voltage_v_assumed": float(vbat),
                    "battery_esr_ohm_assumed": float(esr),
                    "rail_cap_f_assumed": float(cap),
                    "vbat_min_v": measured(log, "vbat_min"),
                    "vrail_min_v": measured(log, "vrail_min"),
                    "cell_peak_current_a": measured(log, "ibat_max"),
                    "vbat_tx_end_v": measured(log, "vbat_tx_end"),
                    "vrail_tx_end_v": measured(log, "vrail_tx_end"),
                    "minimum_functional_rail_v_assumed": float(profile["simulation"]["minimum_functional_rail_v"]),
                    "below_assumed_threshold": None,
                    "ngspice_return_code": run.returncode,
                    "deck": deck_path.name if args.keep_decks or run.returncode != 0 else None,
                    "log": log_path.name if args.keep_decks or run.returncode != 0 else None
                }
                if row["vrail_min_v"] is not None:
                    row["below_assumed_threshold"] = row["vrail_min_v"] < row["minimum_functional_rail_v_assumed"]
                result_rows.append(row)
                if run.returncode != 0:
                    print(f"FAIL {label}: see {log_path}")
                elif not args.keep_decks:
                    deck_path.unlink(missing_ok=True)
                    log_path.unlink(missing_ok=True)

    summary = {
        "status": "SIMULATED",
        "notice": "Candidate-only averaged source and converter model. ESR, efficiency, output impedance, dropout, and capacitor values are explicit assumptions; this does not validate a cell, regulator, PCB, RF transmission, or physical brownout.",
        "battery": profile["battery"],
        "regulator": profile["regulator"],
        "load_profile": profile["load"],
        "capacitors": profile["capacitors"],
        "simulation": profile["simulation"],
        "run_count": len(result_rows),
        "failed_runs": sum(row["status"] == "FAILED" for row in result_rows),
        "maximum_simulated_cell_peak_current_a": max(
            (row["cell_peak_current_a"] for row in result_rows if row["cell_peak_current_a"] is not None),
            default=None),
        "cell_max_pulse_current_a_datasheet": profile["battery"]["max_pulse_current_ma"] / 1000,
        "maximum_peak_within_pulse_limit": None,
        "per_run_decks_saved": bool(args.keep_decks),
        "results": result_rows
    }
    if summary["maximum_simulated_cell_peak_current_a"] is not None:
        summary["maximum_peak_within_pulse_limit"] = (
            summary["maximum_simulated_cell_peak_current_a"] <= summary["cell_max_pulse_current_a_datasheet"])
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if result_rows:
        with (args.output / "sweep.csv").open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=result_rows[0].keys(),
                                    lineterminator="\n")
            writer.writeheader()
            writer.writerows(result_rows)
    print(f"status={summary['status']}")
    print(f"runs={summary['run_count']}")
    print(f"failed_runs={summary['failed_runs']}")
    print(f"results={args.output.resolve()}")
    return 1 if summary["failed_runs"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
