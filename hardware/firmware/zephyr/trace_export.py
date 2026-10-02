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
EVENTS = (
    "INVALID", "BOOT", "MCU_INIT", "STATE", "IMU_READ", "PACKET_CREATED",
    "RADIO_STANDBY", "TX_START", "TX_DONE", "RX_START", "RX_DONE",
    "RADIO_SLEEP", "ERROR", "RECOVERY", "MCU_SLEEP", "WAKE", "SPI",
    "IRQ", "TIMEOUT", "WATCHDOG", "REBOOT",
)
ALLOWED_TRANSITIONS = {
    0: {1}, 1: {2, 7}, 2: {3, 4, 7}, 3: {2, 4, 6, 7},
    4: {2, 5, 7}, 5: {2, 7}, 6: {2, 4, 7}, 7: {1},
}


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
        if len(fields) != 12 or fields[0] != "v1":
            raise TraceFormatError(f"line {line_number}: expected SIMULATED_TRACE,v1 and 11 fields")
        try:
            sequence, timestamp = int(fields[1]), int(fields[2])
            state_id, event_id, source_id, result = (int(fields[i]) for i in (3, 5, 6, 7))
            value0, value1, value2 = (int(value) for value in fields[8:11])
        except ValueError as exc:
            raise TraceFormatError(f"line {line_number}: numeric field is invalid") from exc
        event = fields[4]
        packet_hex = fields[11]
        if not 0 <= state_id < len(STATES):
            raise TraceFormatError(f"line {line_number}: unknown state id {state_id}")
        if not 1 <= event_id < len(EVENTS) or event != EVENTS[event_id]:
            raise TraceFormatError(f"line {line_number}: event name/id mismatch")
        if not 1 <= source_id < len(SOURCES):
            raise TraceFormatError(f"line {line_number}: unknown source id {source_id}")
        if sequence != expected_sequence:
            raise TraceFormatError(f"line {line_number}: sequence {sequence} expected {expected_sequence}")
        if timestamp < 0:
            raise TraceFormatError(f"line {line_number}: timestamp must be non-negative")
        if timestamp < previous_timestamp:
            raise TraceFormatError(f"line {line_number}: timestamps must be monotonic")
        records.append({
            "schema_version": SCHEMA_VERSION,
            "sequence": sequence,
            "status": "SIMULATED",
            "timestamp_us": timestamp,
            "state": STATES[state_id],
            "state_id": state_id,
            "event": event,
            "event_id": event_id,
            "source": SOURCES[source_id],
            "source_id": source_id,
            "result": result,
            "value0": value0,
            "value1": value1,
            "value2": value2,
            "packet_hex": packet_hex,
        })
        expected_sequence += 1
        previous_timestamp = timestamp
    if not records:
        raise TraceFormatError("no SIMULATED_TRACE records found")
    _validate_state_transitions(records)
    _validate_radio_lifecycle(records)
    return records


def _validate_state_transitions(records: list[dict[str, Any]]) -> None:
    if records[0]["event"] != "BOOT" or records[0]["state_id"] != 0:
        raise TraceFormatError("trace must start with the BOOT event in BOOT state")
    current_state = 0
    for record in records[1:]:
        state = record["state_id"]
        if record["event"] == "STATE":
            if record["value0"] != state:
                raise TraceFormatError("STATE payload does not match the recorded state id")
            if state == current_state or state not in ALLOWED_TRANSITIONS[current_state]:
                raise TraceFormatError(
                    f"impossible firmware state transition {current_state}->{state}"
                )
            current_state = state
        elif state != current_state:
            raise TraceFormatError("event state does not match current firmware state")


def _validate_radio_lifecycle(records: list[dict[str, Any]]) -> None:
    """Reject duplicate or out-of-order packet/TX/RX intervals."""
    packet_length: int | None = None
    tx_started = False
    tx_done = False
    rx_started = False
    for record in records:
        event = record["event"]
        if event == "PACKET_CREATED":
            if packet_length is not None:
                raise TraceFormatError("packet created before previous radio cycle completed")
            packet_length = record["value0"]
            if packet_length <= 0:
                raise TraceFormatError("packet length must be positive")
            packet_hex = record["packet_hex"]
            if (len(packet_hex) != packet_length * 2 or
                    any(char not in "0123456789abcdef" for char in packet_hex)):
                raise TraceFormatError("packet bytes do not match the declared packet length")
        elif record["packet_hex"]:
            raise TraceFormatError("packet bytes are only valid on PACKET_CREATED")
        elif event == "TX_START":
            if packet_length is None or tx_started or record["value0"] != packet_length:
                raise TraceFormatError("TX_START does not match one pending packet")
            tx_started = True
        elif event == "TX_DONE":
            if not tx_started or tx_done or record["value1"] != packet_length:
                raise TraceFormatError("TX_DONE does not match one active packet")
            tx_done = True
        elif event == "RX_START":
            if not tx_done or rx_started:
                raise TraceFormatError("RX_START must follow TX_DONE exactly once")
            rx_started = True
        elif event == "RX_DONE":
            if not rx_started:
                raise TraceFormatError("RX_DONE has no matching RX_START")
            packet_length = None
            tx_started = tx_done = rx_started = False
        elif event == "ERROR":
            # A failed radio command may legitimately leave an interval open.
            packet_length = None
            tx_started = tx_done = rx_started = False
    if packet_length is not None:
        raise TraceFormatError("trace ends with an incomplete packet/TX/RX interval")


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
