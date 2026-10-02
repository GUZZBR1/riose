import json

import pytest

from hardware.firmware.zephyr.trace_export import TraceFormatError, parse_console


def test_zephyr_console_trace_normalizes_to_versioned_jsonl_records():
    lines = """I: booted\nI: SIMULATED_TRACE,v1,0,1000,2,STATE,3,1,0,0,0,0\nI: SIMULATED_TRACE,v1,1,2000,4,TX_START,7,2,0,24,915000000,0\n"""
    records = parse_console(lines)
    assert [row["sequence"] for row in records] == [0, 1]
    assert records[0]["schema_version"] == "riose.firmware.trace/v1"
    assert records[0]["state"] == "SLEEP"
    assert records[1]["source"] == "SX1262"
    assert records[1]["event_id"] == 7
    assert all(row["status"] == "SIMULATED" for row in records)
    assert json.loads(json.dumps(records[1]))["event"] == "TX_START"


@pytest.mark.parametrize("capture, message", [
    ("SIMULATED_TRACE,v1,1,1000,2,STATE,3,1,0,0,0,0", "sequence"),
    ("SIMULATED_TRACE,v1,0,1000,2,STATE,3,1,0,0,0", "expected"),
    ("SIMULATED_TRACE,v1,0,1000,2,STATE,3,1,0,0,0,0\nSIMULATED_TRACE,v1,1,900,2,STATE,3,1,0,0,0,0", "monotonic"),
])
def test_zephyr_trace_rejects_malformed_or_nonmonotonic_capture(capture, message):
    with pytest.raises(TraceFormatError, match=message):
        parse_console(capture)
