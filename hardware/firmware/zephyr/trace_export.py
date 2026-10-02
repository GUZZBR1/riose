"""Normalize Zephyr SIMULATED_TRACE console records into versioned JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "riose.firmware.trace/v1"
MARKER = "SIMULATED_TRACE,"
STATES = ("BOOT", "SELF_TEST", "SLEEP", "IMU_MONITORING", "RF_TX", "RF_RX", "ALERT", "ERROR_RECOVERY")
SOURCES = ("INVALID", "FIRMWARE", "SX1262", "HAL")


class TraceFormatError(ValueError):
    """Zephyr console output does not contain a valid structured trace."""


def parse_console(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    expected_sequence = 0
    previous_timestamp = -1
    for line_number, line in enumerate(text.splitlines(), start=1):
        if MARKER not in line:
            continue
        fields = line.split(MARKER, 1)[1].strip().split(",")
        if len(fields) != 11 or fields[0] != "v1":
            raise TraceFormatError(f"line {line_number}: expected SIMULATED_TRACE,v1 and 10 fields")
        try:
            sequence, timestamp = int(fields[1]), int(fields[2])
            state_id, event_id, source_id, result = (int(fields[i]) for i in (3, 5, 6, 7))
            value0, value1, value2 = (int(value) for value in fields[8:11])
        except ValueError as exc:
            raise TraceFormatError(f"line {line_number}: numeric field is invalid") from exc
        event = fields[4]
        state_name = STATES[state_id] if 0 <= state_id < len(STATES) else "UNKNOWN"
        source_name = SOURCES[source_id] if 0 <= source_id < len(SOURCES) else "UNKNOWN"
        if sequence != expected_sequence:
            raise TraceFormatError(f"line {line_number}: sequence {sequence} expected {expected_sequence}")
        if timestamp < previous_timestamp:
            raise TraceFormatError(f"line {line_number}: timestamps must be monotonic")
        records.append({
            "schema_version": SCHEMA_VERSION,
            "sequence": sequence,
            "status": "SIMULATED",
            "timestamp_us": timestamp,
            "state": state_name,
            "state_id": state_id,
            "event": event,
            "event_id": event_id,
            "source": source_name,
            "source_id": source_id,
            "result": result,
            "value0": value0,
            "value1": value1,
            "value2": value2,
        })
        expected_sequence += 1
        previous_timestamp = timestamp
    if not records:
        raise TraceFormatError("no SIMULATED_TRACE records found")
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("console", type=Path, help="Zephyr console/log capture")
    parser.add_argument("--output", type=Path, required=True, help="normalized trace JSONL")
    args = parser.parse_args(argv)
    try:
        records = parse_console(args.console.read_text(encoding="utf-8", errors="replace"))
    except (OSError, TraceFormatError) as exc:
        print(f"trace export failed: {exc}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps({"status": "EXPORTED", "schema_version": SCHEMA_VERSION,
                      "records": len(records), "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
