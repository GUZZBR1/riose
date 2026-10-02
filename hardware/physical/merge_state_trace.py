#!/usr/bin/env python3
"""Join analog current samples with the tag's 3-bit GPIO state trace.

The trace CSV must contain transition samples with timestamp_s,a0,a1,a2. The
analog CSV must contain timestamp_s,battery_current_ma,rail_voltage_v and
battery_voltage_v. Capture both clocks together or document their offset in
metadata; this tool does not synchronize independent clocks.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from bisect import bisect_right
from pathlib import Path


STATES = (
    "BOOT", "SELF_TEST", "SLEEP", "IMU_MONITORING", "RF_TX", "RF_RX",
    "ALERT", "ERROR_RECOVERY",
)
OUTPUT_FIELDS = (
    "scenario", "run_id", "timestamp_s", "state", "battery_current_ma",
    "rail_voltage_v", "battery_voltage_v", "tx_count", "firmware_sha",
    "board_revision", "instrument_id", "instrument_range", "burden_voltage_mv",
    "sample_rate_hz", "calibration_date", "tx_power_dbm", "antenna_load", "ambient_c",
)
ANALOG_FIELDS = ("timestamp_s", "battery_current_ma", "rail_voltage_v", "battery_voltage_v")
TRACE_FIELDS = ("timestamp_s", "a0", "a1", "a2")
METADATA_FIELDS = tuple(field for field in OUTPUT_FIELDS if field not in {
    "timestamp_s", "state", "battery_current_ma", "rail_voltage_v",
    "battery_voltage_v", "tx_count",
})


def _read_csv(path: Path, required: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        missing = sorted(set(required) - set(reader.fieldnames or []))
        if missing:
            raise ValueError(f"{path}: missing columns: {', '.join(missing)}")
        return list(reader)


def _number(row: dict[str, str], field: str, row_number: int) -> float:
    try:
        value = float(row[field])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"row {row_number}: invalid {field}") from exc
    if not math.isfinite(value):
        raise ValueError(f"row {row_number}: {field} must be finite")
    return value


def merge(analog_path: Path, trace_path: Path, metadata: dict) -> list[dict[str, str | int | float]]:
    missing_metadata = [field for field in METADATA_FIELDS
                        if field not in metadata or str(metadata[field]).strip() == ""]
    if missing_metadata:
        raise ValueError(f"metadata missing: {', '.join(missing_metadata)}")

    analog = _read_csv(analog_path, ANALOG_FIELDS)
    trace = _read_csv(trace_path, TRACE_FIELDS)
    if not analog or not trace:
        raise ValueError("analog capture and state trace must both contain samples")

    analog_times: list[float] = []
    for index, row in enumerate(analog, start=2):
        timestamp = _number(row, "timestamp_s", index)
        for field in ANALOG_FIELDS[1:]:
            _number(row, field, index)
        if analog_times and timestamp <= analog_times[-1]:
            raise ValueError("analog timestamps must strictly increase")
        analog_times.append(timestamp)

    trace_events: list[tuple[float, int]] = []
    for index, row in enumerate(trace, start=2):
        timestamp = _number(row, "timestamp_s", index)
        try:
            bits = tuple(int(row[field]) for field in ("a0", "a1", "a2"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"row {index}: GPIO state bits must be 0 or 1") from exc
        if any(bit not in (0, 1) for bit in bits):
            raise ValueError(f"row {index}: GPIO state bits must be 0 or 1")
        if trace_events and timestamp <= trace_events[-1][0]:
            raise ValueError("trace timestamps must strictly increase")
        state_code = bits[0] | (bits[1] << 1) | (bits[2] << 2)
        if not trace_events or state_code != trace_events[-1][1]:
            trace_events.append((timestamp, state_code))

    if trace_events[0][0] > analog_times[0]:
        raise ValueError("state trace must begin at or before the first analog sample")
    if trace_events[0][1] == STATES.index("RF_TX"):
        raise ValueError("trace must show a non-TX state before the first TX to count complete transmissions")

    event_times = [event[0] for event in trace_events]
    tx_entry_counts: list[int] = []
    tx_count = 0
    previous_code: int | None = None
    for _, code in trace_events:
        if code == STATES.index("RF_TX") and previous_code != code:
            tx_count += 1
        tx_entry_counts.append(tx_count)
        previous_code = code

    output: list[dict[str, str | int | float]] = []
    for row, timestamp in zip(analog, analog_times, strict=True):
        event_index = bisect_right(event_times, timestamp) - 1
        state_code = trace_events[event_index][1]
        output.append({
            "scenario": metadata["scenario"],
            "run_id": metadata["run_id"],
            "timestamp_s": timestamp,
            "state": STATES[state_code],
            "battery_current_ma": float(row["battery_current_ma"]),
            "rail_voltage_v": float(row["rail_voltage_v"]),
            "battery_voltage_v": float(row["battery_voltage_v"]),
            "tx_count": tx_entry_counts[event_index],
            **{field: metadata[field] for field in METADATA_FIELDS},
        })
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analog_csv", type=Path, help="instrument export with current/voltage samples")
    parser.add_argument("state_trace_csv", type=Path, help="GPIO transition CSV: timestamp_s,a0,a1,a2")
    parser.add_argument("--metadata", type=Path, required=True,
                        help="JSON with capture identity and instrument/firmware provenance")
    parser.add_argument("--output", type=Path, required=True, help="merged capture CSV")
    args = parser.parse_args()
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    rows = merge(args.analog_csv, args.state_trace_csv, metadata)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} synchronized sample(s) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
