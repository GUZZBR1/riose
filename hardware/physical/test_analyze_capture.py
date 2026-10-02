import csv
import tempfile
import unittest
from pathlib import Path

from analyze_capture import integrate


FIELDS = (
    "scenario", "run_id", "timestamp_s", "state", "battery_current_ma",
    "rail_voltage_v", "battery_voltage_v", "tx_count", "firmware_sha",
    "board_revision", "instrument_id", "instrument_range", "burden_voltage_mv",
    "sample_rate_hz", "calibration_date", "tx_power_dbm", "antenna_load", "ambient_c",
)


def sample(run_id: str, timestamp: str, current: str, tx_count: str = "0") -> dict:
    return dict(zip(FIELDS, (
        "NORMAL_24H", run_id, timestamp, "SLEEP", current, "3.3", "3.6", tx_count,
        "deadbeef", "rev-a", "test-meter", "10mA", "2", "1000", "2026-01-01",
        "14", "50-ohm-load", "25",
    )))


def write_capture(rows: list[dict]) -> Path:
    temporary = tempfile.NamedTemporaryFile(mode="w", newline="", suffix=".csv", delete=False)
    with temporary:
        writer = csv.DictWriter(temporary, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return Path(temporary.name)


class CaptureAnalysisTest(unittest.TestCase):
    def test_integrates_and_keeps_repeats_separate(self):
        path = write_capture([
            sample("run-1", "0", "1"), sample("run-1", "1", "1"),
            sample("run-2", "0", "2"), sample("run-2", "1", "2"),
        ])
        try:
            result = integrate(path)
            runs = result["scenarios"]
            self.assertEqual([item["run_id"] for item in runs], ["run-1", "run-2"])
            self.assertAlmostEqual(runs[0]["charge_mah"], 1 / 3600)
            self.assertAlmostEqual(runs[1]["charge_mah"], 2 / 3600)
        finally:
            path.unlink()

    def test_rejects_out_of_order_samples(self):
        path = write_capture([sample("run", "1", "1"), sample("run", "0", "1")])
        try:
            with self.assertRaisesRegex(ValueError, "timestamps must strictly increase"):
                integrate(path)
        finally:
            path.unlink()

    def test_rejects_reset_tx_counter(self):
        path = write_capture([sample("run", "0", "1", "2"),
                              sample("run", "1", "1", "0")])
        try:
            with self.assertRaisesRegex(ValueError, "cumulative and monotonic"):
                integrate(path)
        finally:
            path.unlink()

    def test_marks_user_supplied_capture_unverified(self):
        path = write_capture([sample("run", "0", "1"), sample("run", "1", "1")])
        try:
            result = integrate(path)
            self.assertIn("NOT_INDEPENDENTLY_AUTHENTICATED", result["evidence_status"])
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
