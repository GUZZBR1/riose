#!/usr/bin/env python3
"""Integrate synchronized physical tag current/voltage captures from CSV."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

REQUIRED = (
    "scenario", "run_id", "timestamp_s", "state", "battery_current_ma",
    "rail_voltage_v", "battery_voltage_v", "tx_count", "firmware_sha",
    "board_revision", "instrument_id", "instrument_range", "burden_voltage_mv",
    "sample_rate_hz", "calibration_date", "tx_power_dbm", "antenna_load", "ambient_c",
)
PROVENANCE_FIELDS = (
    "firmware_sha", "board_revision", "instrument_id", "instrument_range",
    "burden_voltage_mv", "sample_rate_hz", "calibration_date", "tx_power_dbm",
    "antenna_load",
)


def integrate(path: Path) -> dict:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        missing = sorted(set(REQUIRED) - set(reader.fieldnames or []))
        if missing:
            raise ValueError(f"missing required CSV columns: {', '.join(missing)}")
        rows = list(reader)
    if len(rows) < 2:
        raise ValueError("capture needs at least two samples")

    captures: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row_number, row in enumerate(rows, start=2):
        for field in ("scenario", "run_id", "state", *PROVENANCE_FIELDS):
            if not row[field].strip():
                raise ValueError(f"row {row_number}: {field} must not be blank")
        try:
            sample = {
                **row,
                "timestamp_s": float(row["timestamp_s"]),
                "battery_current_ma": float(row["battery_current_ma"]),
                "rail_voltage_v": float(row["rail_voltage_v"]),
                "battery_voltage_v": float(row["battery_voltage_v"]),
                "tx_count": int(row["tx_count"]),
                "burden_voltage_mv": float(row["burden_voltage_mv"]),
                "sample_rate_hz": float(row["sample_rate_hz"]),
                "tx_power_dbm": float(row["tx_power_dbm"]),
                "ambient_c": float(row["ambient_c"]),
            }
        except (TypeError, ValueError) as exc:
            raise ValueError(f"row {row_number}: invalid numeric value ({exc})") from exc
        numeric_fields = ("timestamp_s", "battery_current_ma", "rail_voltage_v",
                          "battery_voltage_v", "burden_voltage_mv", "sample_rate_hz",
                          "tx_power_dbm", "ambient_c")
        if not all(math.isfinite(sample[key]) for key in numeric_fields):
            raise ValueError(f"row {row_number}: non-finite numeric value")
        if sample["sample_rate_hz"] <= 0:
            raise ValueError(f"row {row_number}: sample_rate_hz must be positive")
        captures[(row["scenario"], row["run_id"])].append(sample)

    results = []
    for (scenario, run_id), samples in sorted(captures.items()):
        for field in PROVENANCE_FIELDS:
            if len({sample[field] for sample in samples}) != 1:
                raise ValueError(f"scenario {scenario}/{run_id}: mixed {field}; split captures")
        if any(right["timestamp_s"] <= left["timestamp_s"]
               for left, right in zip(samples, samples[1:])):
            raise ValueError(f"scenario {scenario}/{run_id}: timestamps must strictly increase in input order")
        if any(right["tx_count"] < left["tx_count"]
               for left, right in zip(samples, samples[1:])):
            raise ValueError(f"scenario {scenario}/{run_id}: tx_count must be cumulative and monotonic")

        state_data: dict[str, dict[str, float]] = defaultdict(
            lambda: {"seconds": 0.0, "charge_mah": 0.0, "rail_min_v": math.inf,
                     "battery_min_v": math.inf, "peak_sampled_current_ma": -math.inf}
        )
        for sample in samples:
            data = state_data[sample["state"]]
            data["rail_min_v"] = min(data["rail_min_v"], sample["rail_voltage_v"])
            data["battery_min_v"] = min(data["battery_min_v"], sample["battery_voltage_v"])
            data["peak_sampled_current_ma"] = max(data["peak_sampled_current_ma"],
                                                  sample["battery_current_ma"])
        for previous, current in zip(samples, samples[1:]):
            dt = current["timestamp_s"] - previous["timestamp_s"]
            state = state_data[previous["state"]]
            state["seconds"] += dt
            state["charge_mah"] += (previous["battery_current_ma"] +
                                    current["battery_current_ma"]) * 0.5 * dt / 3600.0
        total_seconds = sum(item["seconds"] for item in state_data.values())
        if total_seconds <= 0:
            raise ValueError(f"scenario {scenario}/{run_id}: capture duration must be positive")
        total_charge = sum(item["charge_mah"] for item in state_data.values())
        results.append({
            "scenario": scenario,
            "run_id": run_id,
            "status": "USER_SUPPLIED_MEASURED_CAPTURE_NOT_INDEPENDENTLY_AUTHENTICATED",
            "elapsed_seconds": total_seconds,
            "charge_mah": total_charge,
            "mean_battery_current_ma": total_charge * 3600.0 / total_seconds,
            "peak_sampled_battery_current_ma": max(
                item["peak_sampled_current_ma"] for item in state_data.values()),
            "minimum_rail_voltage_v": min(item["rail_min_v"] for item in state_data.values()),
            "minimum_battery_voltage_v": min(item["battery_min_v"] for item in state_data.values()),
            "tx_count": samples[-1]["tx_count"],
            "provenance": {field: samples[0][field] for field in PROVENANCE_FIELDS},
            "ambient_c_min": min(sample["ambient_c"] for sample in samples),
            "ambient_c_max": max(sample["ambient_c"] for sample in samples),
            "states": {
                name: {**values,
                       "mean_battery_current_ma": values["charge_mah"] * 3600.0 /
                       values["seconds"] if values["seconds"] else 0.0}
                for name, values in sorted(state_data.items())
            },
            "extrapolation": "NONE; charge applies only to captured elapsed interval",
        })
    return {
        "evidence_status": "USER_SUPPLIED_MEASURED_CAPTURE_NOT_INDEPENDENTLY_AUTHENTICATED",
        "source_csv": str(path),
        "integration_method": "trapezoidal_current_time",
        "state_attribution": "interval charge attributed to preceding sample state; transitions are sample-resolution limited",
        "scenarios": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="synchronized raw capture CSV")
    parser.add_argument("--output", type=Path, required=True, help="JSON result path")
    args = parser.parse_args()
    result = integrate(args.csv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(result['scenarios'])} measured capture(s) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
