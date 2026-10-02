import binascii
import json

import pytest

from hardware.firmware.zephyr.trace_export import (
    EVENTS, SCHEMA_VERSION, SOURCES, STATES, TraceFormatError, load_jsonl, parse_console,
    validate_records,
)

TAG_ID = 0x54524143


def _packet(tag_id=TAG_ID, sequence=0, timestamp_ms=1, behavior=0):
    payload = bytearray((1, behavior))
    payload.extend(tag_id.to_bytes(4, "little"))
    payload.extend(sequence.to_bytes(4, "little"))
    payload.extend(timestamp_ms.to_bytes(4, "little"))
    payload.extend(bytes(6))
    payload.extend((3000).to_bytes(2, "little"))
    payload.extend(binascii.crc_hqx(payload, 0xFFFF).to_bytes(2, "little"))
    return payload.hex()


def _event(event, state, source=None, *, result=0, value0=0, value1=0, value2=0,
           packet_hex="", timestamp_us=0):
    if source is None:
        source = "FIRMWARE" if event in {
            "BOOT", "MCU_INIT", "STATE", "PACKET_CREATED", "ERROR", "RECOVERY"
        } else "HAL" if event in {"IMU_READ", "MCU_SLEEP", "WAKE", "WATCHDOG", "REBOOT"} else "SX1262"
    return {
        "schema_version": SCHEMA_VERSION, "sequence": 0, "status": "SIMULATED",
        "timestamp_us": timestamp_us, "state": state, "state_id": STATES.index(state),
        "event": event, "event_id": EVENTS.index(event),
        "source": source, "source_id": SOURCES.index(source), "result": result,
        "value0": value0, "value1": value1, "value2": value2, "packet_hex": packet_hex,
    }


def _full_trace(failure=False):
    rows = [
        _event("BOOT", "BOOT", value0=TAG_ID, value1=915000000),
        _event("MCU_INIT", "BOOT"),
        _event("STATE", "SELF_TEST", value0=1),
        _event("STATE", "SLEEP", value0=2),
    ]
    if failure:
        rows.extend([
            _event("WAKE", "SLEEP", "HAL", timestamp_us=1000, value0=1),
            _event("STATE", "IMU_MONITORING", timestamp_us=1000, value0=3),
            _event("IMU_READ", "IMU_MONITORING", "HAL", timestamp_us=1000, result=-1),
            _event("ERROR", "IMU_MONITORING", result=-1, value0=1, timestamp_us=1000),
            _event("STATE", "ERROR_RECOVERY", value0=7, timestamp_us=1000),
            _event("RECOVERY", "ERROR_RECOVERY", timestamp_us=2000, value0=1, value1=1),
            _event("STATE", "SELF_TEST", timestamp_us=2000, value0=1),
            _event("STATE", "SLEEP", timestamp_us=2000, value0=2),
        ])
        start_ms = 3
    else:
        start_ms = 1
    t = start_ms * 1000
    rows.extend([
        _event("WAKE", "SLEEP", "HAL", timestamp_us=t),
        _event("STATE", "IMU_MONITORING", timestamp_us=t, value0=3),
        _event("IMU_READ", "IMU_MONITORING", "HAL", timestamp_us=t),
        _event("STATE", "SLEEP", timestamp_us=t, value0=2),
        _event("RADIO_STANDBY", "SLEEP", "SX1262", timestamp_us=t),
        _event("PACKET_CREATED", "SLEEP", timestamp_us=t, value0=24,
               packet_hex=_packet(timestamp_ms=start_ms)),
        _event("STATE", "RF_TX", timestamp_us=t, value0=4),
        _event("TX_START", "RF_TX", "SX1262", timestamp_us=t, value0=24),
        _event("IRQ", "RF_TX", "SX1262", timestamp_us=t + 1000, value0=1),
        _event("TX_DONE", "RF_TX", "SX1262", timestamp_us=t + 1000, value0=1, value1=24),
        _event("STATE", "RF_RX", timestamp_us=t + 1000, value0=5),
        _event("RX_START", "RF_RX", "SX1262", timestamp_us=t + 1000, value0=100),
        _event("IRQ", "RF_RX", "SX1262", timestamp_us=t + 2000, value0=0x0200),
        _event("TIMEOUT", "RF_RX", "SX1262", timestamp_us=t + 2000, result=-1, value0=0x0200),
        _event("RX_DONE", "RF_RX", "SX1262", timestamp_us=t + 2000, value0=0x0200),
        _event("RADIO_SLEEP", "RF_RX", "SX1262", timestamp_us=t + 2000),
        _event("STATE", "SLEEP", timestamp_us=t + 2000, value0=2),
        _event("TRACE_END", "SLEEP", "HAL", timestamp_us=t + 2000),
    ])
    for sequence, row in enumerate(rows):
        row["sequence"] = sequence
    return rows


def _console(records):
    return "\n".join(
        "SIMULATED_TRACE,v1,{sequence},{timestamp_us},{state_id},{event},{event_id},"
        "{source_id},{result},{value0},{value1},{value2},{packet_hex}".format(**r)
        for r in records
    )


def test_console_export_preserves_real_packet_metadata_and_radio_timeline():
    records = parse_console(_console(_full_trace()))
    assert len(records) == 22
    assert records[9]["packet_hex"] == _packet()
    assert records[-1]["state"] == "SLEEP"
    assert parse_console(_console(_full_trace())) == records


def test_console_export_ignores_zephyr_ansi_color_sequences():
    colored = _console(_full_trace()).replace("\n", "\x1b[0m\n") + "\x1b[0m"
    assert parse_console(colored) == _full_trace()


def test_host_jsonl_uses_the_same_schema_and_lifecycle_validation(tmp_path):
    records = _full_trace()
    path = tmp_path / "trace.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
    assert load_jsonl(path) == records


def test_failed_imu_read_must_recover_before_a_later_complete_cycle():
    rows = _full_trace(failure=True)
    records = parse_console(_console(rows))
    assert [r["event"] for r in records if r["event"] in {"ERROR", "RECOVERY"}] == [
        "ERROR", "RECOVERY"
    ]


@pytest.mark.parametrize("mutator, message", [
    (lambda r: r.__setitem__("sequence", 3), "sequence"),
    (lambda r: r.__setitem__("timestamp_us", 0), "monotonic"),
    (lambda r: r.__setitem__("timestamp_us", -1), "timestamp_us"),
    (lambda r: r.__setitem__("state", "GHOST"), "state name/id"),
    (lambda r: r.__setitem__("event", "UNKNOWN"), "event name/id"),
    (lambda r: r.pop("source_id"), "missing fields"),
    (lambda r: r.__setitem__("value0", -1), "value0"),
    (lambda r: (r.__setitem__("source", "HAL"), r.__setitem__("source_id", 3)), "not valid"),
])
def test_schema_rejects_invalid_identity_and_context(mutator, message):
    records = _full_trace()
    mutator(records[11])
    with pytest.raises(TraceFormatError, match=message):
        validate_records(records)


@pytest.mark.parametrize("change, message", [
    ({"value0": 0, "packet_hex": ""}, "exactly 24 bytes"),
    ({"value0": 23, "packet_hex": "00" * 23}, "exactly 24 bytes"),
    ({"value0": 25, "packet_hex": "00" * 25}, "exactly 24 bytes"),
    ({"packet_hex": "zz" * 24}, "lowercase hexadecimal"),
    ({"packet_hex": "00" * 24}, "version"),
    ({"value1": 999}, "sequence metadata"),
    ({"value2": 3}, "behavior metadata"),
    ({"packet_hex": _packet(tag_id=123)}, "tag identity"),
    ({"packet_hex": _packet(timestamp_ms=99)}, "timestamp metadata"),
    ({"packet_hex": _packet()[:-4] + "0000"}, "CRC"),
])
def test_packet_length_bytes_crc_and_metadata_are_checked(change, message):
    records = _full_trace()
    records[9].update(change)
    with pytest.raises(TraceFormatError, match=message):
        validate_records(records)


@pytest.mark.parametrize("change, message", [
    ({"value1": 23}, "TX_DONE metadata"),
    ({"state": "BOOT", "state_id": 0, "source": "HAL", "source_id": 3}, "not valid"),
    ({"value0": 0}, "RX timeout duration"),
    ({"source": "HAL", "source_id": 3}, "not valid"),
    ({"value0": 0}, "RX_DONE metadata"),
])
def test_radio_intervals_reject_orphaned_or_inconsistent_events(change, message):
    records = _full_trace()
    event = "TX_DONE" if message.startswith("TX_DONE") else (
        "TX_START" if "not valid" in message else "RX_START" if "duration" in message else "RX_DONE"
    )
    index = next(i for i, record in enumerate(records) if record["event"] == event)
    records[index].update(change)
    with pytest.raises(TraceFormatError, match=message):
        validate_records(records)


@pytest.mark.parametrize("sequence", [11, 1])
def test_console_validator_rejects_duplicate_and_regressing_sequences(sequence):
    records = _full_trace()
    records[12]["sequence"] = sequence
    with pytest.raises(TraceFormatError, match="sequence"):
        validate_records(records)


def test_radio_completion_without_rx_start_is_rejected():
    records = _full_trace()
    records[:] = [row for row in records if not (
        row["state_id"] == 5 and row["event"] in {"RX_START", "IRQ", "TIMEOUT"}
    )]
    for sequence, record in enumerate(records):
        record["sequence"] = sequence
    with pytest.raises(TraceFormatError, match="RX_DONE has no matching"):
        validate_records(records)


def test_records_after_capture_end_are_rejected():
    records = _full_trace()
    extra = _event("WAKE", "SLEEP", "HAL", timestamp_us=records[-1]["timestamp_us"])
    extra["sequence"] = len(records)
    records.append(extra)
    with pytest.raises(TraceFormatError, match="TRACE_END must be the final"):
        validate_records(records)


@pytest.mark.parametrize("records, message", [
    (_full_trace()[:1], "MCU_INIT"),
    (_full_trace()[:-1], "missing TRACE_END"),
    (lambda: _without_tx_done(), "RX_START"),
])
def test_truncated_or_incomplete_capture_is_not_exported(records, message):
    if callable(records):
        records = records()
    with pytest.raises(TraceFormatError, match=message):
        validate_records(records)


def _without_tx_done():
    records = _full_trace()
    del records[13]
    for sequence, record in enumerate(records):
        record["sequence"] = sequence
    return records


def test_jsonl_rejects_malformed_and_blank_lines(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text("{invalid}\n", encoding="utf-8")
    with pytest.raises(TraceFormatError, match="invalid JSON"):
        load_jsonl(path)
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(TraceFormatError, match="blank lines"):
        load_jsonl(path)


def test_watchdog_and_reboot_are_schema_supported_but_not_fabricated():
    records = parse_console(_console(_full_trace()))
    assert not any(record["event"] in {"WATCHDOG", "REBOOT"} for record in records)


@pytest.mark.parametrize("event", ["WATCHDOG", "REBOOT"])
def test_reported_reset_cause_is_valid_while_firmware_remains_in_boot(event):
    records = _full_trace()
    records.insert(2, _event(event, "BOOT", "HAL", value0=0x10, value1=2))
    for sequence, row in enumerate(records):
        row["sequence"] = sequence
    assert validate_records(records) is None
