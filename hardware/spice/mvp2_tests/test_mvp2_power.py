import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


MODULE = Path(__file__).resolve().parents[1] / "mvp2_power.py"
SPEC = importlib.util.spec_from_file_location("mvp2_power", MODULE)
power = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(power)


class TraceDrivenPowerTests(unittest.TestCase):
    def setUp(self):
        self.assumptions = json.loads((MODULE.parent / "mvp2_power_assumptions.json").read_text())
        self.rows = [
            {"timestamp_s": 0.0, "event": "WAKE", "state": "ACTIVE", "component": "mcu",
             "duration_s": 2.0, "load_current_ma": 10.0, "end_s": 2.0},
            {"timestamp_s": 1.0, "event": "TX_START", "state": "TX", "component": "radio",
             "duration_s": 1.0, "load_current_ma": 40.0, "end_s": 2.0},
        ]

    def test_overlapping_event_energy_and_idle_gap_are_integrated(self):
        result = power.analyze_schedule(self.rows, self.assumptions, period_s=10.0)
        # mA*s / 3600: (10*2 + 40*1 + idle*10) / 3600 mAh
        expected = (60 + self.assumptions["idle_current_ma"]["value"] * 10) / 3600
        self.assertAlmostEqual(result["total_charge_mah_window"], expected)
        self.assertAlmostEqual(result["mAh_per_day"], expected * 8640)
        self.assertEqual(result["status"], "SIMULATED")
        tx = next(r for r in result["event_charge"] if r["event"] == "TX_START")
        self.assertAlmostEqual(tx["charge_uah"], 40 / 3600 * 1000)
        self.assertIsNone(result["ideal_capacity_division"])

    def test_daily_projection_requires_declared_repeat_period(self):
        result = power.analyze_schedule(self.rows, self.assumptions)
        self.assertIsNone(result["mAh_per_day"])
        self.assertEqual(result["mAh_per_day_status"], "NOT_REPORTED_NO_REPEAT_PERIOD")

    def test_netlist_uses_trace_load_and_assumption_provenance(self):
        deck = power.generate_netlist(self.rows, self.assumptions, period_s=10)
        self.assertIn("SIMULATED", deck)
        self.assertIn("ASSUMED", deck)
        self.assertIn("PWL(", deck)
        self.assertIn("meas tran rail_min", deck)
        self.assertIn("Ibattery battery 0 PWL(", deck)

    def test_schedule_rejects_negative_or_zero_intervals(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "bad.jsonl"
            source.write_text(json.dumps({**self.rows[0], "timestamp_s": -1}) + "\n")
            with self.assertRaises(ValueError):
                power.load_schedule(source)
        with self.assertRaises(ValueError):
            power.analyze_schedule(self.rows, self.assumptions, period_s=1)

    def test_sweeps_are_one_factor_at_a_time_and_temperature_is_not_fabricated(self):
        cases = power.parameter_sweep(self.rows, self.assumptions, period_s=10)
        self.assertGreaterEqual(len(cases), 16)
        temperature = next(c for c in cases if c["overrides"].get("temperature_c_assumption") == -10.0)
        self.assertEqual(temperature["temperature_status"], "ASSUMED_SCENARIO_ONLY_NO_TEMPERATURE_MODEL")
        self.assertEqual(temperature["status"], "SIMULATED_DECK_GENERATED_NOT_EXECUTED")


if __name__ == "__main__":
    unittest.main()
