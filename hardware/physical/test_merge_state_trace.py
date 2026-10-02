import csv
import tempfile
import unittest
from pathlib import Path

from analyze_capture import integrate
from merge_state_trace import merge


METADATA = {
    "scenario": "ACTIVE_BURST_2M",
    "run_id": "run-001",
    "firmware_sha": "deadbeef",
    "board_revision": "rev-a",
    "instrument_id": "current-analyzer-1",
    "instrument_range": "100mA",
    "burden_voltage_mv": 2,
    "sample_rate_hz": 1000,
    "calibration_date": "2026-01-01",
    "tx_power_dbm": 14,
    "antenna_load": "50-ohm-load",
    "ambient_c": 25,
}


def write_csv(fields, rows):
    path = Path(tempfile.mktemp(suffix=".csv"))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


class TraceMergeTest(unittest.TestCase):
    def test_maps_gpio_states_and_counts_tx_entries(self):
        analog = write_csv(
            ["timestamp_s", "battery_current_ma", "rail_voltage_v", "battery_voltage_v"],
            [
                {"timestamp_s": "0", "battery_current_ma": "0.01", "rail_voltage_v": "3.3", "battery_voltage_v": "3.6"},
                {"timestamp_s": "1", "battery_current_ma": "12", "rail_voltage_v": "3.2", "battery_voltage_v": "3.5"},
                {"timestamp_s": "2", "battery_current_ma": "0.01", "rail_voltage_v": "3.3", "battery_voltage_v": "3.6"},
                {"timestamp_s": "3", "battery_current_ma": "12", "rail_voltage_v": "3.2", "battery_voltage_v": "3.5"},
            ],
        )
        trace = write_csv(
            ["timestamp_s", "a0", "a1", "a2"],
            [
                {"timestamp_s": "0", "a0": "0", "a1": "0", "a2": "0"},  # BOOT
                {"timestamp_s": "0.5", "a0": "0", "a1": "1", "a2": "0"},  # SLEEP
                {"timestamp_s": "1", "a0": "0", "a1": "0", "a2": "1"},  # RF_TX
                {"timestamp_s": "1.5", "a0": "0", "a1": "1", "a2": "0"},  # SLEEP
                {"timestamp_s": "2.5", "a0": "0", "a1": "0", "a2": "1"},  # RF_TX
            ],
        )
        try:
            result = merge(analog, trace, METADATA)
            self.assertEqual([sample["state"] for sample in result],
                             ["BOOT", "RF_TX", "SLEEP", "RF_TX"])
            self.assertEqual([sample["tx_count"] for sample in result], [0, 1, 1, 2])
            self.assertEqual(result[0]["firmware_sha"], "deadbeef")
            merged = Path(tempfile.mktemp(suffix=".csv"))
            try:
                fields = list(result[0])
                with merged.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(result)
                analyzed = integrate(merged)["scenarios"][0]
                self.assertEqual(analyzed["tx_count"], 2)
                self.assertAlmostEqual(analyzed["elapsed_seconds"], 3)
            finally:
                merged.unlink()
        finally:
            analog.unlink()
            trace.unlink()

    def test_requires_trace_to_cover_capture_start(self):
        analog = write_csv(
            ["timestamp_s", "battery_current_ma", "rail_voltage_v", "battery_voltage_v"],
            [{"timestamp_s": "1", "battery_current_ma": "1", "rail_voltage_v": "3.3", "battery_voltage_v": "3.6"},
             {"timestamp_s": "2", "battery_current_ma": "1", "rail_voltage_v": "3.3", "battery_voltage_v": "3.6"}],
        )
        trace = write_csv(
            ["timestamp_s", "a0", "a1", "a2"],
            [{"timestamp_s": "1.1", "a0": "0", "a1": "1", "a2": "0"}],
        )
        try:
            with self.assertRaisesRegex(ValueError, "begin at or before"):
                merge(analog, trace, METADATA)
        finally:
            analog.unlink()
            trace.unlink()


if __name__ == "__main__":
    unittest.main()
