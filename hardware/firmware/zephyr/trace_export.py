"""Validate and export versioned structured firmware traces."""

from __future__ import annotations

import argparse
import binascii
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "riose.firmware.trace/v1"
MARKER = "SIMULATED_TRACE,"
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
STATES = ("BOOT", "SELF_TEST", "SLEEP", "IMU_MONITORING", "RF_TX", "RF_RX", "ALERT", "ERROR_RECOVERY")
SOURCES = ("INVALID", "FIRMWARE", "SX1262", "HAL")
EVENTS = (
    "INVALID", "BOOT", "MCU_INIT", "STATE", "IMU_READ", "PACKET_CREATED",
    "RADIO_STANDBY", "TX_START", "TX_DONE", "RX_START", "RX_DONE",
    "RADIO_SLEEP", "ERROR", "RECOVERY", "MCU_SLEEP", "WAKE", "SPI",
    "IRQ", "TIMEOUT", "WATCHDOG", "REBOOT", "TRACE_END",
)
ALLOWED_TRANSITIONS = {
    0: {1}, 1: {2, 7}, 2: {3, 4, 7}, 3: {2, 4, 6, 7},
    4: {2, 5, 7}, 5: {2, 7}, 6: {2, 4, 7}, 7: {1},
}
REQUIRED_FIELDS = {
    "schema_version", "sequence", "status", "timestamp_us", "state", "state_id",
    "event", "event_id", "source", "source_id", "result", "value0", "value1",
    "value2", "packet_hex",
}
UINT32_MAX = (1 << 32) - 1
UINT64_MAX = (1 << 64) - 1
INT32_MIN, INT32_MAX = -(1 << 31), (1 << 31) - 1
TELEMETRY_SIZE = 24


class TraceFormatError(ValueError):
    """Trace does not satisfy the firmware trace/v1 contract."""


def _uint(record: dict[str, Any], field: str, maximum: int, index: int) -> int:
    value = record[field]
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise TraceFormatError(f"record {index}: {field} must be an unsigned integer in range")
    return value


def _context(record: dict[str, Any], index: int) -> None:
    event, state, source = record["event"], record["state_id"], record["source_id"]
    any_state = set(range(1, len(STATES)))
    contexts = {
        "BOOT": ({0}, {1}), "MCU_INIT": ({0}, {1}), "STATE": (any_state, {1}),
        "IMU_READ": ({1, 3, 6}, {3}), "PACKET_CREATED": ({2, 3, 4, 6}, {1}),
        "RADIO_STANDBY": ({1, 2, 3, 4, 6}, {2}),
        "TX_START": ({4}, {2}), "TX_DONE": ({4}, {2}),
        "RX_START": ({5}, {2}), "RX_DONE": ({5}, {2}),
        "RADIO_SLEEP": ({1, 5}, {2}), "ERROR": (any_state, {1}),
        "RECOVERY": ({7}, {1}), "MCU_SLEEP": ({2, 7}, {3}), "WAKE": ({2}, {3}),
        "SPI": (any_state, {2}), "IRQ": ({4, 5}, {2}),
        "TIMEOUT": ({4}, {1, 2}) if state == 4 else ({5}, {1, 2}),
        # main.c reports the preceding reset immediately after init, while
        # the current FSM state is still BOOT.
        "WATCHDOG": ({0, 1}, {3}), "REBOOT": ({0, 1}, {3}),
        "TRACE_END": (any_state, {3}),
    }
    states, sources = contexts[event]
    if state not in states or source not in sources:
        raise TraceFormatError(
            f"record {index}: {event} is not valid in state {STATES[state]} from {SOURCES[source]}"
        )


def _validate_packet(record: dict[str, Any], tag_id: int, index: int) -> None:
    packet_hex = record["packet_hex"]
    if record["value0"] != TELEMETRY_SIZE or len(packet_hex) != TELEMETRY_SIZE * 2:
        raise TraceFormatError(f"record {index}: packet must contain exactly {TELEMETRY_SIZE} bytes")
    if any(c not in "0123456789abcdef" for c in packet_hex):
        raise TraceFormatError(f"record {index}: packet bytes must be lowercase hexadecimal")
    packet = bytes.fromhex(packet_hex)
    if packet[0] != 1:
        raise TraceFormatError(f"record {index}: unsupported telemetry packet version")
    if packet[1] != record["value2"] or packet[1] > 3:
        raise TraceFormatError(f"record {index}: packet behavior metadata does not match its bytes")
    if int.from_bytes(packet[2:6], "little") != tag_id:
        raise TraceFormatError(f"record {index}: packet tag identity does not match BOOT")
    if int.from_bytes(packet[6:10], "little") != record["value1"]:
        raise TraceFormatError(f"record {index}: packet sequence metadata does not match its bytes")
    packet_ms = int.from_bytes(packet[10:14], "little")
    trace_ms = record["timestamp_us"] // 1000
    if packet_ms > trace_ms or trace_ms - packet_ms > 1:
        raise TraceFormatError(f"record {index}: packet timestamp metadata is inconsistent")
    if binascii.crc_hqx(packet[:22], 0xFFFF) != int.from_bytes(packet[22:24], "little"):
        raise TraceFormatError(f"record {index}: packet CRC is invalid")


def validate_records(records: list[dict[str, Any]], *, require_complete: bool = True) -> None:
    """Validate v1 records from console or host JSONL without silent normalization."""
    if not records:
        raise TraceFormatError("trace contains no records")
    expected_sequence = 0
    previous_timestamp = -1
    current_state = 0
    tag_id = None
    initialized = False
    radio_phase = None
    completed_cycles = 0
    errors = recoveries = 0
    tx_start = rx_start = tx_length = None
    rx_timeout = False
    previous = None
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise TraceFormatError(f"record {index}: expected a JSON object")
        missing = REQUIRED_FIELDS - record.keys()
        if missing:
            raise TraceFormatError(f"record {index}: missing fields: {', '.join(sorted(missing))}")
        if record["schema_version"] != SCHEMA_VERSION or record["status"] != "SIMULATED":
            raise TraceFormatError(f"record {index}: unsupported schema or status")
        sequence = _uint(record, "sequence", UINT32_MAX, index)
        timestamp = _uint(record, "timestamp_us", UINT64_MAX, index)
        state = _uint(record, "state_id", len(STATES) - 1, index)
        event_id = _uint(record, "event_id", len(EVENTS) - 1, index)
        source = _uint(record, "source_id", len(SOURCES) - 1, index)
        result = record["result"]
        if isinstance(result, bool) or not isinstance(result, int) or not INT32_MIN <= result <= INT32_MAX:
            raise TraceFormatError(f"record {index}: result must be signed 32-bit")
        value0 = _uint(record, "value0", UINT32_MAX, index)
        value1 = _uint(record, "value1", UINT32_MAX, index)
        _uint(record, "value2", UINT32_MAX, index)
        if sequence != expected_sequence:
            raise TraceFormatError(f"record {index}: sequence {sequence} expected {expected_sequence}")
        if timestamp < previous_timestamp:
            raise TraceFormatError(f"record {index}: timestamps must be monotonic")
        if record["state"] != STATES[state]:
            raise TraceFormatError(f"record {index}: state name/id mismatch")
        if not 1 <= event_id < len(EVENTS) or record["event"] != EVENTS[event_id]:
            raise TraceFormatError(f"record {index}: event name/id mismatch")
        if not 1 <= source < len(SOURCES) or record["source"] != SOURCES[source]:
            raise TraceFormatError(f"record {index}: source name/id mismatch")
        if not isinstance(record["packet_hex"], str):
            raise TraceFormatError(f"record {index}: packet_hex must be a string")
        event = record["event"]
        if previous is not None and previous["event"] == "TRACE_END":
            raise TraceFormatError(f"record {index}: TRACE_END must be the final record")
        if event != "PACKET_CREATED" and record["packet_hex"]:
            raise TraceFormatError(f"record {index}: packet bytes occur outside PACKET_CREATED")
        _context(record, index)
        if index == 0:
            if event != "BOOT" or state != 0:
                raise TraceFormatError("trace must start with BOOT in BOOT state")
            tag_id = value0
        elif event == "BOOT":
            raise TraceFormatError(f"record {index}: duplicate BOOT event")
        if index == 1 and event != "MCU_INIT":
            raise TraceFormatError("MCU_INIT must follow BOOT")
        if event == "MCU_INIT":
            if initialized:
                raise TraceFormatError(f"record {index}: duplicate MCU_INIT")
            initialized = True
        if event == "STATE":
            if value0 != state:
                raise TraceFormatError(f"record {index}: STATE payload does not match state id")
            if state == current_state or state not in ALLOWED_TRANSITIONS[current_state]:
                raise TraceFormatError(f"record {index}: impossible firmware state transition {current_state}->{state}")
            current_state = state
        elif state != current_state:
            raise TraceFormatError(f"record {index}: event state does not match current state")

        if event == "PACKET_CREATED":
            if tag_id is None or radio_phase not in (None, "standby"):
                raise TraceFormatError(f"record {index}: packet overlaps or precedes a valid radio cycle")
            _validate_packet(record, tag_id, index)
            radio_phase, tx_length = "packet", value0
            tx_start = rx_start = None
            rx_timeout = False
        elif event == "RADIO_STANDBY":
            if radio_phase not in (None, "standby"):
                raise TraceFormatError(f"record {index}: radio standby overlaps an unfinished cycle")
            radio_phase = "standby"
        elif event == "TX_START":
            if radio_phase != "packet" or value0 != tx_length:
                raise TraceFormatError(f"record {index}: TX_START does not match one pending packet")
            radio_phase, tx_start = "tx", timestamp
        elif event == "TX_DONE":
            if radio_phase != "tx" or previous is None or previous["event"] != "IRQ":
                raise TraceFormatError(f"record {index}: TX_DONE has no matching active TX/IRQ")
            if value1 != tx_length or previous["value0"] != value0 or previous["timestamp_us"] != timestamp:
                raise TraceFormatError(f"record {index}: TX_DONE metadata does not match TX/IRQ")
            if tx_start is None or timestamp < tx_start:
                raise TraceFormatError(f"record {index}: TX interval is temporally invalid")
            radio_phase = "tx_done"
        elif event == "RX_START":
            if radio_phase != "tx_done":
                raise TraceFormatError(f"record {index}: RX_START must follow TX_DONE exactly once")
            if value0 == 0:
                raise TraceFormatError(f"record {index}: RX timeout duration must be positive")
            radio_phase, rx_start = "rx", timestamp
        elif event == "TIMEOUT":
            if result >= 0:
                raise TraceFormatError(f"record {index}: TIMEOUT must report a failure result")
            if state == 4:
                if radio_phase != "tx" or value1 != tx_length:
                    raise TraceFormatError(f"record {index}: TX timeout has no active TX")
                radio_phase = "tx_timeout"
            else:
                if radio_phase != "rx":
                    raise TraceFormatError(f"record {index}: RX timeout has no active RX")
                if source == 2:
                    if previous is None or previous["event"] != "IRQ":
                        raise TraceFormatError(f"record {index}: radio RX timeout has no IRQ")
                    if previous["value0"] != value0 or previous["timestamp_us"] != timestamp:
                        raise TraceFormatError(f"record {index}: RX timeout metadata does not match IRQ")
                    rx_timeout = True
                else:
                    radio_phase = "rx_timeout"
        elif event == "RX_DONE":
            if radio_phase != "rx" or previous is None or previous["event"] not in ("IRQ", "TIMEOUT"):
                raise TraceFormatError(f"record {index}: RX_DONE has no matching RX/IRQ")
            if previous["value0"] != value0 or previous["timestamp_us"] != timestamp:
                raise TraceFormatError(f"record {index}: RX_DONE metadata does not match IRQ/timeout")
            if rx_timeout != bool(value0 & 0x0200):
                raise TraceFormatError(f"record {index}: RX timeout event and IRQ bits disagree")
            if rx_start is None or timestamp < rx_start:
                raise TraceFormatError(f"record {index}: RX interval is temporally invalid")
            radio_phase = "rx_done"
        elif event == "RADIO_SLEEP":
            if radio_phase != "rx_done":
                if radio_phase is None and state == 1:
                    pass  # Self-test can put the radio to sleep before a packet cycle.
                else:
                    raise TraceFormatError(f"record {index}: radio sleep has no completed RX cycle")
            else:
                radio_phase = None
                completed_cycles += 1
        elif event == "ERROR":
            if result >= 0:
                raise TraceFormatError(f"record {index}: ERROR must report a failure result")
            errors += 1
            radio_phase = None  # A failure aborts its active interval.
        elif event == "RECOVERY":
            if recoveries >= errors:
                raise TraceFormatError(f"record {index}: RECOVERY has no preceding ERROR")
            recoveries += 1
        if event == "STATE" and state == 7 and (previous is None or previous["event"] != "ERROR"):
            raise TraceFormatError(f"record {index}: ERROR_RECOVERY must follow ERROR")
        if previous is not None and previous["event"] == "ERROR" and (event != "STATE" or state != 7):
            raise TraceFormatError(f"record {index}: ERROR must immediately enter ERROR_RECOVERY")
        if previous is not None and previous["event"] == "RECOVERY" and (event != "STATE" or state != 1):
            raise TraceFormatError(f"record {index}: RECOVERY must immediately re-enter SELF_TEST")
        if previous is not None and previous["event"] == "TIMEOUT":
            if previous["state_id"] == 4 or previous["source_id"] == 1:
                if event != "ERROR":
                    raise TraceFormatError(f"record {index}: firmware timeout must abort into ERROR")
            elif event != "RX_DONE":
                raise TraceFormatError(f"record {index}: radio RX timeout must complete RX_DONE")
        expected_sequence += 1
        previous_timestamp, previous = timestamp, record
    if not initialized:
        raise TraceFormatError("trace is missing MCU_INIT")
    if radio_phase not in (None, "standby"):
        raise TraceFormatError("trace ends with an incomplete packet/TX/RX interval")
    if errors != recoveries:
        raise TraceFormatError("trace ends before all failures recover")
    if require_complete and records[-1]["event"] != "TRACE_END":
        raise TraceFormatError("complete trace is missing TRACE_END")
    if require_complete and completed_cycles == 0:
        raise TraceFormatError("complete trace must contain one complete TX/RX radio cycle")


def parse_console(text: str, *, require_complete: bool = True) -> list[dict[str, Any]]:
    records = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if MARKER not in line:
            continue
        # Zephyr's colored log backend can append its reset sequence after the
        # final empty packet field. Strip terminal decoration before decoding.
        fields = ANSI_ESCAPE.sub("", line.split(MARKER, 1)[1]).strip().split(",")
        if len(fields) != 12 or fields[0] != "v1":
            raise TraceFormatError(f"line {line_number}: expected SIMULATED_TRACE,v1 and 11 fields")
        try:
            sequence, timestamp = int(fields[1]), int(fields[2])
            state, event_id, source, result = (int(fields[i]) for i in (3, 5, 6, 7))
            value0, value1, value2 = (int(value) for value in fields[8:11])
        except ValueError as exc:
            raise TraceFormatError(f"line {line_number}: numeric field is invalid") from exc
        if not 0 <= state < len(STATES):
            raise TraceFormatError(f"line {line_number}: unknown state id {state}")
        if not 1 <= event_id < len(EVENTS) or fields[4] != EVENTS[event_id]:
            raise TraceFormatError(f"line {line_number}: event name/id mismatch")
        if not 1 <= source < len(SOURCES):
            raise TraceFormatError(f"line {line_number}: unknown source id {source}")
        records.append({
            "schema_version": SCHEMA_VERSION, "sequence": sequence, "status": "SIMULATED",
            "timestamp_us": timestamp, "state": STATES[state], "state_id": state,
            "event": fields[4], "event_id": event_id, "source": SOURCES[source],
            "source_id": source, "result": result, "value0": value0, "value1": value1,
            "value2": value2, "packet_hex": fields[11],
        })
    validate_records(records, require_complete=require_complete)
    return records


def load_jsonl(path: Path, *, require_complete: bool = True) -> list[dict[str, Any]]:
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line:
            raise TraceFormatError(f"line {line_number}: blank lines are not allowed")
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise TraceFormatError(f"line {line_number}: invalid JSON") from exc
    validate_records(records, require_complete=require_complete)
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
