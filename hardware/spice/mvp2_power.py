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
    return float(override if override is not None else assumptions[key]["value"])


def analyze_schedule(rows: list[dict], assumptions: dict, period_s: float | None = None) -> dict:
    """Integrate intervals and produce event/component charge and a complete timeline."""
    idle = _value(assumptions, "idle_current_ma")
    end = max(r["end_s"] for r in rows)
    if period_s is not None and (not math.isfinite(period_s) or period_s < end or period_s <= 0):
        raise ValueError("period_s must be finite and cover the full schedule")
    total_end = period_s or end
    boundaries = sorted({0.0, total_end, *(r["timestamp_s"] for r in rows), *(r["end_s"] for r in rows)})
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
    modeled_mah_day = charge_mah * 24 * 3600 / total_end
    return {"status": "SIMULATED", "input_status": "ASSUMED_OR_TRACE_DERIVED_NOT_MEASURED",
            "modeled_window_s": total_end, "period_s": period_s,
            "total_charge_mah_window": charge_mah,
            "mAh_per_day": modeled_mah_day if period_s is not None else None,
            "mAh_per_day_status": "SIMULATED_EXTRAPOLATION_FROM_DECLARED_REPEAT_PERIOD" if period_s else "NOT_REPORTED_NO_REPEAT_PERIOD",
            "ideal_capacity_division": None,
            "ideal_capacity_division_status": "NOT_CALCULATED_NO_USABLE_CAPACITY_INPUT",
            "event_charge": event_rows,
            "component_charge_uah": {k: v * 1000 for k, v in sorted(by_component.items())},
            "idle_current_ma_assumed": idle,
            "timeline": timeline}


def pwl_points(rows: list[dict], assumptions: dict, period_s: float | None = None) -> list[tuple[float, float]]:
    idle = _value(assumptions, "idle_current_ma")
    end = max(r["end_s"] for r in rows)
    total_end = period_s or end
    bounds = sorted({0.0, total_end, *(r["timestamp_s"] for r in rows), *(r["end_s"] for r in rows)})
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
        transition_end = min(time_s + edge, next_boundary)
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
    executable = binary or shutil.which("ngspice")
    if not executable:
        return {"status": "NOT_AVAILABLE", "detail": "ngspice absent; netlist generated but not executed"}
    run = subprocess.run([executable, "-b", deck.name], cwd=deck.parent, capture_output=True,
                         text=True, check=False)
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
    waveform = deck.parent / "power_waveform.dat"
    if vreg is not None and waveform.exists():
        # `wrdata` with wr_singlescale emits time followed by requested vectors.
        try:
            points = []
            for line in waveform.read_text().splitlines():
                fields = line.split()
                if len(fields) >= 2:
                    points.append((float(fields[0]), float(fields[1])))
            schedule_end = max(float(r["end_s"]) for r in rows) if rows else None
            if schedule_end is not None:
                recovery = next((t - schedule_end for t, voltage in points
                                 if t >= schedule_end and voltage >= 0.99 * vreg), None)
        except (ValueError, OSError):
            recovery = None
    return {"status": status, "return_code": run.returncode,
            "rail_min_v": rail_min, "rail_max_v": rail_max,
            "battery_min_v": measurement("battery_min"),
            "battery_current_peak_a": (-measurement("battery_current_peak")
                                         if measurement("battery_current_peak") is not None else None),
            "voltage_droop_v": (rail_max - rail_min) if rail_min is not None and rail_max is not None else None,
            "recovery_to_99pct_s": recovery,
            "brownout_threshold_v_assumed": None,
            "log": "ngspice.log", "trace": "power_waveform.dat",
            "note": "Average regulator model; recovery is found from the raw waveform after the last schedule interval."}


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
        output.append({"case": case["case"], "overrides": overrides,
                       "temperature_status": "ASSUMED_SCENARIO_ONLY_NO_TEMPERATURE_MODEL" if "temperature_c_assumption" in overrides else None,
                       "netlist": generate_netlist(adjusted, assumptions, period_s, electrical),
                       "status": "SIMULATED_DECK_GENERATED_NOT_EXECUTED"})
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
    parser.add_argument("--output", type=Path, default=Path("results/mvp2/power"))
    parser.add_argument("--ngspice", help="ngspice executable; auto-detected when omitted")
    args = parser.parse_args(argv)
    rows = load_schedule(args.schedule)
    assumptions = json.loads(args.assumptions.read_text())
    result = analyze_schedule(rows, assumptions, args.period_s)
    args.output.mkdir(parents=True, exist_ok=True)
    deck = args.output / "power_trace.cir"
    deck.write_text(generate_netlist(rows, assumptions, args.period_s))
    result["ngspice"] = _run_ngspice(deck, args.ngspice, rows)
    result["ngspice"]["brownout_threshold_v_assumed"] = _value(assumptions, "brownout_threshold_v")
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
