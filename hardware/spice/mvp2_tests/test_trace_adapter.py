import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

adapter = load_module("trace_adapter", BASE / "trace_adapter.py")
power = load_module("mvp2_power", BASE / "mvp2_power.py")


def record(timestamp_ms, event, state, value0=0, sequence=None):
    return {
        "schema_version": "riose.firmware.trace/v1",
        "status": "SIMULATED", "timestamp_us": timestamp_ms * 1000,
        "state": state, "state_id": 0, "event": event, "event_id": 0,
        "source": "FIRMWARE", "source_id": 1, "result": 0,
        "value0": value0, "value1": 0, "value2": 0,
    } | ({"sequence": sequence} if sequence is not None else {})


class FirmwareTraceAdapterTests(unittest.TestCase):
    def test_orchestrator_profile_envelope_is_accepted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "loads.json"
            path.write_text(json.dumps({
                "schema_version": "riose.power.loads/v1", "status": "ASSUMED",
                "loads": {"pair:TX_START:TX_DONE": {"current_status": "ASSUMED"}},
            }))
            loaded = adapter.read_load_profile(path)
        self.assertIn("pair:TX_START:TX_DONE", loaded)

    def test_schedule_is_accepted_by_power_analyzer(self):
        trace = [
            record(0, "STATE", "SLEEP"),
            record(1, "STATE", "IMU_MONITORING"),
            record(2, "IMU_READ", "IMU_MONITORING"),
            record(3, "STATE", "RF_TX"),
            record(3, "TX_START", "RF_TX"),
            record(7, "TX_DONE", "RF_TX"),
            record(7, "STATE", "RF_RX"),
            record(7, "RX_START", "RF_RX"),
            record(9, "RX_DONE", "RF_RX"),
            record(9, "STATE", "SLEEP"),
            record(9, "MCU_SLEEP", "SLEEP", value0=100),
        ]
        loads = {
            "state:SLEEP": {"component": "mcu_sleep", "load_current_ma": 0.01,
                             "current_status": "ASSUMED", "source": "test fixture"},
            "pair:TX_START:TX_DONE": {"component": "sx1262_tx", "load_current_ma": 20,
                                      "current_status": "ASSUMED", "source": "test fixture"},
            "pair:RX_START:RX_DONE": {"component": "sx1262_rx", "load_current_ma": 5,
                                      "current_status": "ASSUMED", "source": "test fixture"},
            "event:IMU_READ": {"component": "lis2dw12", "load_current_ma": 0.1,
                               "current_status": "ASSUMED", "source": "test fixture",
                               "fallback_duration_s": 0.001, "duration_status": "ASSUMED",
                               "duration_source": "test fixture"},
        }
        rows = adapter.trace_to_schedule(trace, loads)
        tx = next(row for row in rows if row["event"] == "TX")
        self.assertAlmostEqual(tx["duration_s"], 0.004)
        self.assertEqual(tx["duration_source"], "TRACE_TIMESTAMP")
        imu = next(row for row in rows if row["event"] == "IMU_READ")
        self.assertEqual(imu["duration_source"], "ASSUMED_FALLBACK")
        self.assertTrue(all(row["status"] == "SIMULATED" and
                            row["current_status"] == "ASSUMED" for row in rows))

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "schedule.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            accepted = power.load_schedule(path)
        result = power.analyze_schedule(accepted, {"idle_current_ma": {"value": 0.01}})
        self.assertEqual(result["status"], "SIMULATED")
        self.assertGreater(result["total_charge_mah_window"], 0)

    def test_zero_resolution_requires_explicit_assumed_fallback(self):
        trace = [record(10, "TX_START", "RF_TX"), record(10, "TX_DONE", "RF_TX")]
        loads = {"pair:TX_START:TX_DONE": {
            "component": "radio", "load_current_ma": 10, "current_status": "ASSUMED",
            "source": "test fixture"
        }}
        with self.assertRaisesRegex(adapter.TraceConversionError, "zero timestamp resolution"):
            adapter.trace_to_schedule(trace, loads)

    def test_unpaired_radio_event_is_not_fabricated(self):
        trace = [record(10, "TX_START", "RF_TX")]
        loads = {"pair:TX_START:TX_DONE": {
            "component": "radio", "load_current_ma": 10, "current_status": "ASSUMED",
            "fallback_duration_s": 0.1, "duration_status": "ASSUMED",
            "source": "test fixture", "duration_source": "test fixture"
        }}
        with self.assertRaisesRegex(adapter.TraceConversionError, "cannot infer interval"):
            adapter.trace_to_schedule(trace, loads)

    def test_measured_current_is_rejected(self):
        trace = [record(0, "STATE", "SLEEP"),
                 record(1, "MCU_SLEEP", "SLEEP", value0=10)]
        loads = {"state:SLEEP": {
            "component": "mcu", "load_current_ma": 0.01,
            "current_status": "MEASURED", "source": "should not be accepted"
        }}
        with self.assertRaisesRegex(adapter.TraceConversionError, "must be ASSUMED"):
            adapter.trace_to_schedule(trace, loads)

    def test_versioned_trace_requires_contiguous_sequence(self):
        records = [record(0, "STATE", "SLEEP", sequence=0),
                   record(1, "STATE", "RF_TX", sequence=3)]
        with self.assertRaisesRegex(adapter.TraceConversionError, "contiguous"):
            adapter.trace_to_schedule(records, {})


if __name__ == "__main__":
    unittest.main()
