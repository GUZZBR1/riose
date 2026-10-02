#!/usr/bin/env python3
"""MVP 2 trace-driven power analysis. All outputs are SIMULATED, never measured.

Input rows describe current-bearing intervals using timestamp_s, event, state,
component, duration_s, load_current_ma. Current is the rail load during that
interval. Overlapping component intervals add; unoccupied time uses the
explicit assumed idle_current_ma. CSV and JSONL are accepted.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
DEFAULT_ASSUMPTIONS = HERE / "mvp2_power_assumptions.json"
REQUIRED = ("timestamp_s", "event", "state", "component", "duration_s", "load_current_ma")


def load_schedule(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() in (".jsonl", ".ndjson"):
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    elif path.suffix.lower() == ".json":
        data = json.loads(path.read_text())
        rows = data["events"] if isinstance(data, dict) else data
    else:
        with path.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("Schedule contains no intervals")
    normalized = []
    for index, source in enumerate(rows):
        missing = [key for key in REQUIRED if key not in source or source[key] == ""]
        if missing:
            raise ValueError(f"Row {index + 1} missing fields: {', '.join(missing)}")
        row = dict(source)
        for name in ("timestamp_s", "duration_s", "load_current_ma"):
            if isinstance(row[name], bool):
                raise ValueError(f"Row {index + 1}: {name} must be numeric, not boolean")
            try:
                row[name] = float(row[name])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Row {index + 1}: {name} must be numeric") from exc
            if not math.isfinite(row[name]):
                raise ValueError(f"Row {index + 1}: {name} must be finite")
        if row["timestamp_s"] < 0 or row["duration_s"] <= 0 or row["load_current_ma"] < 0:
            raise ValueError(f"Row {index + 1}: timestamps/current must be nonnegative and duration positive")
        row["event"] = str(row["event"])
        row["state"] = str(row["state"])
        row["component"] = str(row["component"])
        row["end_s"] = row["timestamp_s"] + row["duration_s"]
        normalized.append(row)
    return sorted(normalized, key=lambda r: (r["timestamp_s"], r["end_s"], r["component"]))


def _value(assumptions: dict, key: str, override: float | None = None) -> float:
    value = override if override is not None else assumptions[key]["value"]
    if isinstance(value, bool):
        raise ValueError(f"{key} must be numeric, not boolean")
    return float(value)


def _trace_window(rows: list[dict]) -> tuple[float, float]:
    starts = {float(row["trace_window_start_s"]) for row in rows if "trace_window_start_s" in row}
    ends = {float(row["trace_window_end_s"]) for row in rows if "trace_window_end_s" in row}
    if len(starts) > 1 or len(ends) > 1:
        raise ValueError("schedule rows disagree on trace window")
    start = next(iter(starts), 0.0)
    end = next(iter(ends), max(float(row.get("end_s", row["timestamp_s"] + row["duration_s"]))
                               for row in rows))
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise ValueError("trace window must be finite, nonnegative, and nonempty")
    if any(float(row["timestamp_s"]) < start or
           float(row.get("end_s", row["timestamp_s"] + row["duration_s"])) > end for row in rows):
        raise ValueError("schedule interval falls outside the declared trace window")
    return start, end


def _validate_assumptions(assumptions: dict, overrides: dict[str, float] | None = None) -> None:
    overrides = overrides or {}
    values = {key: _value(assumptions, key, overrides.get(key)) for key in (
        "battery_voltage_v", "battery_esr_ohm", "regulator_output_v",
        "regulator_efficiency", "regulator_quiescent_ma",
        "regulator_output_resistance_ohm", "output_capacitance_f",
        "idle_current_ma", "brownout_threshold_v", "pwl_edge_s")}
    for key in values:
        record = assumptions.get(key)
        if not isinstance(record, dict) or record.get("status") not in {
                "DATASHEET", "ASSUMED", "SIMULATED"} or not record.get("source"):
            raise ValueError(f"{key} requires DATASHEET/ASSUMED/SIMULATED status and source provenance")
    if values["battery_voltage_v"] <= 0 or values["regulator_output_v"] <= 0:
        raise ValueError("battery and regulator voltages must be positive")
    if values["battery_esr_ohm"] < 0 or values["regulator_output_resistance_ohm"] < 0:
        raise ValueError("resistances must be nonnegative")
    if not 0 < values["regulator_efficiency"] <= 1:
        raise ValueError("regulator_efficiency must be in (0, 1]")
    if values["regulator_quiescent_ma"] < 0 or values["idle_current_ma"] < 0:
        raise ValueError("quiescent and idle currents must be nonnegative")
    if values["output_capacitance_f"] <= 0 or values["brownout_threshold_v"] <= 0:
        raise ValueError("output capacitance and functional voltage limit must be positive")
    if values["pwl_edge_s"] <= 0:
        raise ValueError("pwl_edge_s must be positive")
    for key, value in overrides.items():
        if not math.isfinite(float(value)):
            raise ValueError(f"{key} override must be finite")


def analyze_schedule(rows: list[dict], assumptions: dict, period_s: float | None = None) -> dict:
    """Integrate intervals and produce event/component charge and a complete timeline."""
    idle = _value(assumptions, "idle_current_ma")
    window_start, window_end = _trace_window(rows)
    if period_s is not None and (not math.isfinite(period_s) or period_s < window_end or period_s <= 0):
        raise ValueError("period_s must be finite and cover the full schedule")
    total_end = period_s or window_end
    boundaries = sorted({window_start, total_end, *(r["timestamp_s"] for r in rows), *(r["end_s"] for r in rows)})
    timeline = []
    by_event = defaultdict(float)
    by_component = defaultdict(float)
    charge_mah = 0.0
    for start, stop in zip(boundaries, boundaries[1:]):
        if stop <= start:
            continue
        active = [r for r in rows if r["timestamp_s"] < stop and r["end_s"] > start]
        current = idle + sum(r["load_current_ma"] for r in active)
        dt = stop - start
        amount_mah = current * dt / 3600.0
        charge_mah += amount_mah
        event_names = sorted({r["event"] for r in active}) or ["IDLE"]
        components = sorted({r["component"] for r in active})
        timeline.append({"timestamp_start_s": start, "timestamp_end_s": stop,
                         "duration_s": dt, "load_current_ma": current,
                         "active_events": ";".join(event_names),
                         "active_components": ";".join(components), "status": "SIMULATED"})
        # Allocate idle baseline separately; overlapping loads are attributed to each source.
        idle_q = idle * dt / 3600.0
        by_event[("IDLE_BASELINE", "idle_baseline")] += idle_q
        by_component["idle_baseline"] += idle_q
        for r in active:
            q = r["load_current_ma"] * dt / 3600.0
            by_event[(r["event"], r["component"])] += q
            by_component[r["component"]] += q
    event_rows = [{"event": event, "component": component,
                   "charge_uah": q * 1000, "status": "SIMULATED"}
                  for (event, component), q in sorted(by_event.items())]
    daily_period = period_s
    modeled_mah_day = charge_mah * 24 * 3600 / daily_period if daily_period else None
    rail_v = (_value(assumptions, "regulator_output_v")
              if "regulator_output_v" in assumptions else None)
    energy_status = ("SIMULATED_AT_ASSUMED_REGULATOR_OUTPUT_VOLTAGE" if rail_v is not None
                     else "NOT_CALCULATED_NO_REGULATOR_OUTPUT_VOLTAGE")
    event_rows = [{**row,
                   "energy_mj": row["charge_uah"] * rail_v * 3.6 if rail_v is not None else None,
                   "energy_status": energy_status}
                  for row in event_rows]
    energy_by_event = defaultdict(float)
    for row in event_rows:
        if row["energy_mj"] is not None:
            energy_by_event[row["event"]] += row["energy_mj"]
    wake_energy_mj = sleep_energy_mj = 0.0
    for segment in timeline:
        energy_mj = (segment["load_current_ma"] * segment["duration_s"] * rail_v
                     if rail_v is not None else None)
        active_states = {r["state"] for r in rows
                         if r["timestamp_s"] < segment["timestamp_end_s"] and r["end_s"] > segment["timestamp_start_s"]}
        if energy_mj is None:
            continue
        if active_states == {"SLEEP"}:
            sleep_energy_mj += energy_mj
        elif active_states:
            wake_energy_mj += energy_mj
    return {"status": "SIMULATED", "input_status": "ASSUMED_OR_TRACE_DERIVED_NOT_MEASURED",
            "modeled_window_s": total_end, "trace_window_s": window_end - window_start,
            "period_s": period_s,
            "total_charge_mah_window": charge_mah,
            "mAh_per_day": modeled_mah_day,
            "mAh_per_day_period_s": daily_period,
            "repeat_period_provenance": None,
            "mAh_per_day_status": ("SIMULATED_EXTRAPOLATION_FROM_DECLARED_REPEAT_PERIOD" if period_s else
                                   "NOT_REPORTED_NO_REPEAT_PERIOD"),
            "ideal_capacity_division": None,
            "ideal_capacity_division_status": "NOT_CALCULATED_NO_USABLE_CAPACITY_INPUT",
            "event_charge": event_rows,
            "component_charge_uah": {k: v * 1000 for k, v in sorted(by_component.items())},
            "energy_by_event_mj": dict(sorted(energy_by_event.items())),
            "energy_tx_mj": energy_by_event.get("TX", energy_by_event.get("TX_START", 0.0)),
            "energy_wake_mj": wake_energy_mj if rail_v is not None else None,
            "energy_sleep_mj": sleep_energy_mj if rail_v is not None else None,
            "energy_status": energy_status,
            "model_provenance": {key: value for key, value in assumptions.items()
                                 if isinstance(value, dict) and "value" in value},
            "idle_current_ma_assumed": idle,
            "timeline": timeline}


def pwl_points(rows: list[dict], assumptions: dict, period_s: float | None = None) -> list[tuple[float, float]]:
    idle = _value(assumptions, "idle_current_ma")
    window_start, window_end = _trace_window(rows)
    total_end = period_s or window_end
    bounds = sorted({window_start, total_end, *(r["timestamp_s"] for r in rows), *(r["end_s"] for r in rows)})
    edge = _value(assumptions, "pwl_edge_s")
    def current_at(time_s: float) -> float:
        return idle + sum(r["load_current_ma"] for r in rows
                          if r["timestamp_s"] <= time_s < r["end_s"])
    points = [(bounds[0], current_at(bounds[0]) / 1000.0)]
    for time_s in bounds[1:]:
        before = current_at(max(0.0, time_s - max(edge * 2, 1e-12))) / 1000.0
        after = current_at(time_s) / 1000.0
        # Preserve the preceding level to the boundary, then approximate the edge
        # over an explicit microsecond-scale interval (rather than ramping a whole event).
        points.append((time_s, before))
        next_boundary = next((b for b in bounds if b > time_s), total_end)
        transition_end = min(time_s + edge, time_s + (next_boundary - time_s) / 2, next_boundary)
        if transition_end > time_s:
            points.append((transition_end, after))
    if points[-1][0] < total_end:
        points.append((total_end, current_at(total_end) / 1000.0))
    # Ensure the final point is defined and the profile has nonzero duration.
    if len(points) == 1:
        points.append((points[0][0] + 1e-6, points[0][1]))
    return points


def generate_netlist(rows: list[dict], assumptions: dict, period_s: float | None = None,
                     overrides: dict[str, float] | None = None, data_path: str = "power_waveform.dat") -> str:
    overrides = overrides or {}
    _validate_assumptions(assumptions, overrides)
    vbat = _value(assumptions, "battery_voltage_v", overrides.get("battery_voltage_v"))
    esr = _value(assumptions, "battery_esr_ohm", overrides.get("battery_esr_ohm"))
    vreg = _value(assumptions, "regulator_output_v")
    efficiency = _value(assumptions, "regulator_efficiency", overrides.get("regulator_efficiency"))
    iq = _value(assumptions, "regulator_quiescent_ma") / 1000
    rout = _value(assumptions, "regulator_output_resistance_ohm")
    cap = _value(assumptions, "output_capacitance_f", overrides.get("output_capacitance_f"))
    brownout = _value(assumptions, "brownout_threshold_v")
    points = pwl_points(rows, assumptions, period_s)
    pwl = " ".join(f"{t:.12g} {i:.12g}" for t, i in points)
    max_time = points[-1][0]
    step = max(min(max_time / 10000, 1e-3), 1e-7)
    # Convert rail power to average battery current using the assumed converter efficiency.
    ibat_points = " ".join(f"{t:.12g} {i*vreg/(vbat*efficiency)+iq:.12g}" for t, i in points)
    return f"""* RIOSE MVP2 power twin -- SIMULATED; all component/regulator/cell values ASSUMED.
* Average regulator abstraction. Not a switching-regulator, cell, PCB, or physical validation model.
.param VBAT={vbat:.12g} RBAT={esr:.12g} VREG={vreg:.12g} RREG={rout:.12g} COUT={cap:.12g}
.param BROWNOUT={brownout:.12g} EFF={efficiency:.12g}
Vcell cell_src 0 DC {{VBAT}}
Rcell cell_src battery {{RBAT}}
Ibattery battery 0 PWL({ibat_points})
* Rail transient is an averaged ideal source plus assumed output resistance/capacitance.
Vreg reg_src 0 DC {{VREG}}
Rreg reg_src rail {{RREG}}
Cout rail 0 {{COUT}} IC={{VREG}}
Iload rail 0 PWL({pwl})
.control
set noaskquit
set wr_singlescale
tran {step:.12g} {max_time:.12g} 0 {step:.12g} uic
meas tran rail_min MIN v(rail)
meas tran rail_max MAX v(rail)
meas tran battery_min MIN v(battery)
meas tran battery_current_peak MIN i(Vcell)
wrdata {data_path} v(rail) i(Vcell)
quit
.endc
.end
"""


def _run_ngspice(deck: Path, binary: str | None, rows: list[dict]) -> dict:
    waveform = deck.parent / "power_waveform.dat"
    electrical_csv = deck.parent / "electrical_trace.csv"
    waveform.unlink(missing_ok=True)
    electrical_csv.unlink(missing_ok=True)
    executable = binary or shutil.which("ngspice")
    if not executable:
        return {"status": "NOT_AVAILABLE", "detail": "ngspice absent; netlist generated but not executed"}
    try:
        run = subprocess.run([executable, "-b", deck.name], cwd=deck.parent, capture_output=True,
                             text=True, check=False, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:
        (deck.parent / "ngspice.log").write_text(str(exc) + "\n")
        return {"status": "FAILED", "detail": f"ngspice could not complete: {exc}",
                "log": "ngspice.log", "trace": None}
    log = run.stdout + run.stderr
    (deck.parent / "ngspice.log").write_text(log)
    import re
    def measurement(name):
        found = re.search(rf"{name}\s*=\s*([-+0-9.eE]+)", log, re.I)
        return float(found.group(1)) if found else None
    status = "EXECUTED" if run.returncode == 0 else "FAILED"
    rail_min = measurement("rail_min")
    rail_max = measurement("rail_max")
    # Deck execution is also used independently of the repository path, so infer the
    # steady-state rail target from the netlist's VREG parameter.
    netlist_text = deck.read_text()
    vreg_match = re.search(r"VREG=([-+0-9.eE]+)", netlist_text)
    vreg = float(vreg_match.group(1)) if vreg_match else None
    recovery = None
    waveform_points = []
    validation_error = None
    try:
        if not waveform.is_file():
            raise ValueError("ngspice waveform output is missing")
        for line in waveform.read_text().splitlines():
            fields = line.split()
            if len(fields) < 3:
                continue
            values = [float(value) for value in fields[:3]]
            if not all(math.isfinite(value) for value in values):
                raise ValueError("waveform contains a non-finite sample")
            waveform_points.append((values[0], values[1], values[2]))
        if len(waveform_points) < 2 or any(b[0] <= a[0] for a, b in zip(waveform_points, waveform_points[1:])):
            raise ValueError("waveform has fewer than two increasing-time samples")
        if vreg is not None:
            schedule_end = _trace_window(rows)[1]
            recovery = next((t - schedule_end for t, voltage, _ in waveform_points
                             if t >= schedule_end and voltage >= 0.99 * vreg), None)
    except (ValueError, OSError) as exc:
        validation_error = str(exc)
    required = {"rail_min": rail_min, "rail_max": rail_max,
                "battery_min": measurement("battery_min"),
                "battery_current_peak": measurement("battery_current_peak")}
    missing = [name for name, value in required.items()
               if value is None or not math.isfinite(value)]
    convergence_failure = any(marker in log.lower() for marker in (
        "convergence failed", "timestep too small", "tran analysis failed", "singular matrix"))
    if run.returncode == 0 and (missing or validation_error or convergence_failure):
        status = "FAILED"
    details = []
    if run.returncode != 0:
        details.append(f"ngspice exited {run.returncode}")
    if missing:
        details.append("missing/invalid measurements: " + ", ".join(missing))
    if validation_error:
        details.append(validation_error)
    if convergence_failure:
        details.append("ngspice reported a convergence/analysis failure")
    battery_min = required["battery_min"]
    battery_current_peak = (abs(required["battery_current_peak"])
                            if required["battery_current_peak"] is not None else None)
    if status != "EXECUTED":
        rail_min = rail_max = battery_min = battery_current_peak = None
        recovery = None
    result = {"status": status, "return_code": run.returncode,
            "rail_min_v": rail_min, "rail_max_v": rail_max,
            "battery_min_v": battery_min,
            "battery_current_peak_a": battery_current_peak,
            "voltage_droop_v": (vreg - rail_min) if rail_min is not None and vreg is not None else None,
            "recovery_to_99pct_s": recovery,
            "recovery_status": ("RECOVERED_TO_99PCT" if recovery is not None else
                                "NOT_RECOVERED_WITHIN_SIMULATED_WINDOW" if status == "EXECUTED" else
                                "NOT_AVAILABLE_WITHOUT_VALID_SIMULATION"),
            "functional_margin_v": None,
            "detail": "; ".join(details) if status == "FAILED" else None,
            "log": "ngspice.log", "trace": "power_waveform.dat",
            "note": "Average regulator model; recovery is found from the raw waveform after the last schedule interval."}
    if status == "EXECUTED":
        write_csv(deck.parent / "electrical_trace.csv", [
            {"timestamp_s": t, "rail_voltage_v": voltage,
             "battery_current_a": abs(current), "status": "SIMULATED"}
            for t, voltage, current in waveform_points
        ])
        result["electrical_trace_csv"] = "electrical_trace.csv"
    return result


def parameter_sweep(rows: list[dict], assumptions: dict, period_s: float | None = None) -> list[dict]:
    """Generate deterministic sensitivity cases and their ngspice deck parameters."""
    axes = {
        "battery_voltage_v": [3.0, 3.3, 3.6],
        "battery_esr_ohm": [0.1, 0.25, 0.5],
        "regulator_efficiency": [0.7, 0.85, 0.95],
        "output_capacitance_f": [float(assumptions["output_capacitance_f"]["value"]) * x for x in (0.8, 1.0, 1.2)],
        "temperature_c_assumption": [-10.0, 25.0, 50.0],
        "tx_current_scale": [0.8, 1.0, 1.2],
    }
    # One-factor-at-a-time avoids an unmanageable Cartesian product while retaining named sensitivity axes.
    cases = [{"case": "BASELINE", "overrides": {}}]
    for key, values in axes.items():
        for value in values:
            cases.append({"case": f"{key}={value:g}", "overrides": {key: value}})
    output = []
    for case in cases:
        overrides = case["overrides"]
        adjusted = [dict(r) for r in rows]
        if "tx_current_scale" in overrides:
            scale = overrides["tx_current_scale"]
            adjusted = [dict(r, load_current_ma=r["load_current_ma"] * scale)
                        if str(r["component"]).lower() in ("radio", "sx1262", "tx") or "tx" in str(r["event"]).lower()
                        else r for r in adjusted]
        electrical = {k: v for k, v in overrides.items() if k in (
            "battery_voltage_v", "battery_esr_ohm", "regulator_efficiency", "output_capacitance_f")}
        override_provenance = {
            key: {"value": value, "status": "ASSUMED",
                  "source": f"MVP2 one-factor-at-a-time sensitivity axis: {key}"}
            for key, value in overrides.items()
        }
        temperature_only = "temperature_c_assumption" in overrides
        output.append({"case": case["case"], "overrides": overrides,
                       "override_provenance": override_provenance,
                       "temperature_status": "ASSUMED_SCENARIO_ONLY_NO_TEMPERATURE_MODEL" if "temperature_c_assumption" in overrides else None,
                       "netlist": None if temperature_only else generate_netlist(adjusted, assumptions, period_s, electrical),
                       "status": ("NOT_MODELED_NO_TEMPERATURE_DEPENDENCY" if temperature_only
                                  else "SIMULATED_DECK_GENERATED_NOT_EXECUTED")})
    return output


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("schedule", type=Path, help="CSV, JSON array/object, or JSONL interval schedule")
    parser.add_argument("--assumptions", type=Path, default=DEFAULT_ASSUMPTIONS)
    parser.add_argument("--period-s", type=float, help="Declared repeat period; enables simulated mAh/day extrapolation")
    parser.add_argument("--period-source", help="Provenance for the declared repeat period")
    parser.add_argument("--output", type=Path, default=Path("results/mvp2/power"))
    parser.add_argument("--ngspice", help="ngspice executable; auto-detected when omitted")
    args = parser.parse_args(argv)
    if args.period_s is not None and not args.period_source:
        parser.error("--period-source is required with --period-s to preserve provenance")
    rows = load_schedule(args.schedule)
    assumptions = json.loads(args.assumptions.read_text())
    result = analyze_schedule(rows, assumptions, args.period_s)
    if args.period_source:
        result["repeat_period_provenance"] = args.period_source
    args.output.mkdir(parents=True, exist_ok=True)
    deck = args.output / "power_trace.cir"
    deck.write_text(generate_netlist(rows, assumptions, args.period_s))
    result["ngspice"] = _run_ngspice(deck, args.ngspice, rows)
    result["ngspice"]["brownout_threshold_v_assumed"] = _value(assumptions, "brownout_threshold_v")
    result["ngspice"]["brownout_threshold_provenance"] = assumptions["brownout_threshold_v"]
    if result["ngspice"]["status"] == "EXECUTED" and result["ngspice"]["rail_min_v"] is not None:
        result["ngspice"]["functional_margin_v"] = (
            result["ngspice"]["rail_min_v"] - result["ngspice"]["brownout_threshold_v_assumed"])
        result["ngspice"]["functional_margin_status"] = "SIMULATED_VS_ASSUMED_FUNCTIONAL_LIMIT"
    else:
        result["ngspice"]["functional_margin_status"] = "NOT_AVAILABLE_WITHOUT_VALID_SIMULATION"
    result["sweep"] = {"status": "GENERATED_NOT_EXECUTED", "cases": len(parameter_sweep(rows, assumptions, args.period_s))}
    write_csv(args.output / "power.csv", result["timeline"])
    write_csv(args.output / "event_energy.csv", result["event_charge"])
    (args.output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    (args.output / "sweep.json").write_text(json.dumps(parameter_sweep(rows, assumptions, args.period_s), indent=2) + "\n")
    print(f"status=SIMULATED ngspice={result['ngspice']['status']} window_s={result['modeled_window_s']:.6g}")
    print(f"charge_uah={result['total_charge_mah_window']*1000:.9g} mAh_per_day={result['mAh_per_day']}")
    print(f"outputs={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
