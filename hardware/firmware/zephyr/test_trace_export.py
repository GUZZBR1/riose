import json

import pytest

from hardware.firmware.zephyr.trace_export import TraceFormatError, parse_console


def _record(sequence, timestamp, state, event_id, event, source=1, value0=0, value1=0,
            packet_hex=""):
    return (
        f"SIMULATED_TRACE,v1,{sequence},{timestamp},{state},{event},{event_id},"
        f"{source},0,{value0},{value1},0,{packet_hex}"
    )


def _boot_to_sleep():
    return [
        _record(0, 0, 0, 1, "BOOT"),
        _record(1, 0, 0, 2, "MCU_INIT"),
        _record(2, 0, 1, 3, "STATE", value0=1),
        _record(3, 0, 2, 3, "STATE", value0=2),
    ]


def test_zephyr_console_trace_normalizes_packet_bytes_and_radio_lifecycle():
    rows = _boot_to_sleep() + [
        _record(4, 1000, 2, 15, "WAKE", value0=0),
        _record(5, 1000, 3, 3, "STATE", value0=3),
        _record(6, 1000, 3, 4, "IMU_READ"),
        _record(7, 1000, 4, 3, "STATE", value0=4),
        _record(8, 1000, 4, 5, "PACKET_CREATED", value0=24,
                packet_hex="000102030405060708090a0b0c0d0e0f1011121314151617"),
        _record(9, 1000, 4, 7, "TX_START", source=2, value0=24),
        _record(10, 2000, 4, 17, "IRQ", source=2, value0=1),
        _record(11, 2000, 4, 8, "TX_DONE", source=2, value0=1, value1=24),
        _record(12, 2000, 5, 3, "STATE", value0=5),
        _record(13, 2000, 5, 9, "RX_START", source=2, value0=100),
        _record(14, 3000, 5, 17, "IRQ", source=2, value0=2),
        _record(15, 3000, 5, 18, "TIMEOUT", source=2, value0=2),
        _record(16, 3000, 5, 10, "RX_DONE", source=2, value0=2),
        _record(17, 3000, 5, 11, "RADIO_SLEEP", source=2),
        _record(18, 3000, 2, 3, "STATE", value0=2),
    ]
    capture = "\n".join(["I: booted", *(f"I: {row}" for row in rows)])
    records = parse_console(capture)

    assert [row["sequence"] for row in records] == list(range(19))
    assert records[0]["schema_version"] == "riose.firmware.trace/v1"
    packet = records[8]
    assert packet["event"] == "PACKET_CREATED"
    assert len(bytes.fromhex(packet["packet_hex"])) == packet["value0"] == 24
    assert [row["event"] for row in records[8:17]] == [
        "PACKET_CREATED", "TX_START", "IRQ", "TX_DONE", "STATE", "RX_START",
        "IRQ", "TIMEOUT", "RX_DONE"
    ]
    assert parse_console(capture) == records
    assert json.loads(json.dumps(packet))["packet_hex"] == packet["packet_hex"]


def test_zephyr_console_trace_preserves_failure_and_recovery_events():
    rows = [
        _record(0, 0, 0, 1, "BOOT"),
        _record(1, 0, 1, 3, "STATE", value0=1),
        _record(2, 1000, 1, 12, "ERROR", value0=1),
        _record(3, 1000, 7, 3, "STATE", value0=7),
        _record(4, 2000, 7, 13, "RECOVERY", value0=1),
    ]
    records = parse_console("\n".join(rows))
    assert [record["event"] for record in records[-3:]] == ["ERROR", "STATE", "RECOVERY"]
    assert records[-1]["state"] == "ERROR_RECOVERY"


def test_exporter_accepts_existing_transient_fsm_paths():
    rows = _boot_to_sleep() + [
        _record(4, 1000, 3, 3, "STATE", value0=3),
        _record(5, 1000, 3, 4, "IMU_READ"),
        _record(6, 1000, 4, 3, "STATE", value0=4),
        _record(7, 1000, 2, 3, "STATE", value0=2),
        _record(8, 1000, 3, 3, "STATE", value0=3),
        _record(9, 1000, 3, 4, "IMU_READ"),
        _record(10, 1000, 2, 3, "STATE", value0=2),
        _record(11, 1000, 4, 3, "STATE", value0=4),
    ]
    # The first sample takes the normal transient RF_TX->SLEEP path. The
    # second stays still, then transmits because its beacon deadline is due.
    assert parse_console("\n".join(rows))[-1]["state"] == "RF_TX"


@pytest.mark.parametrize("capture, message", [
    ("SIMULATED_TRACE,v1,1,1000,2,STATE,3,1,0,0,0", "expected"),
    ("\n".join([
        _record(0, 0, 0, 1, "BOOT"),
        _record(1, 1000, 1, 3, "STATE", value0=1),
        _record(2, 2000, 2, 3, "STATE", value0=2),
        _record(3, 1500, 3, 3, "STATE", value0=3),
    ]), "monotonic"),
    ("\n".join([_record(0, 0, 0, 1, "BOOT"),
                _record(1, 0, 0, 7, "TX_START", source=2, value0=24)]), "pending packet"),
    ("\n".join([_record(0, 0, 0, 1, "BOOT"),
                _record(1, 0, 0, 3, "TX_START", source=2, value0=24)]), "event name/id"),
    ("\n".join([_record(0, 0, 0, 1, "BOOT"),
                _record(1, 0, 99, 3, "STATE", value0=99)]), "unknown state"),
    ("\n".join(_boot_to_sleep() + [
        _record(4, 0, 5, 3, "STATE", value0=5),
    ]), "impossible firmware state transition"),
    ("\n".join(_boot_to_sleep() + [
        _record(4, 1000, 2, 5, "PACKET_CREATED", value0=24, packet_hex="abcd"),
    ]), "packet bytes"),
    ("\n".join(_boot_to_sleep() + [
        _record(4, 1000, 3, 3, "STATE", value0=3),
        _record(5, 1000, 4, 3, "STATE", value0=4),
        _record(6, 1000, 4, 5, "PACKET_CREATED", value0=24, packet_hex="00" * 24),
        _record(7, 1000, 4, 7, "TX_START", source=2, value0=24),
    ]), "incomplete packet"),
    ("\n".join(_boot_to_sleep() + [
        _record(4, 1000, 3, 3, "STATE", value0=3),
        _record(5, 1000, 4, 3, "STATE", value0=4),
        _record(6, 1000, 4, 5, "PACKET_CREATED", value0=24, packet_hex="00" * 24),
        _record(7, 1000, 4, 7, "TX_START", source=2, value0=24),
        _record(8, 2000, 4, 8, "TX_DONE", source=2, value0=1, value1=23),
    ]), "active packet"),
])
def test_zephyr_trace_rejects_malformed_or_inconsistent_capture(capture, message):
    with pytest.raises(TraceFormatError, match=message):
        parse_console(capture)
