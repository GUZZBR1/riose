import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


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
        self.assertEqual(temperature["status"], "NOT_MODELED_NO_TEMPERATURE_DEPENDENCY")
        self.assertIsNone(temperature["netlist"])
        self.assertEqual(temperature["override_provenance"]["temperature_c_assumption"]["status"], "ASSUMED")

    def test_energy_metrics_use_assumed_rail_voltage_and_cover_event_components(self):
        result = power.analyze_schedule(self.rows, self.assumptions, period_s=10.0)
        self.assertAlmostEqual(result["energy_tx_mj"], 40 / 3600 * 1000 * 3.3 * 3.6)
        self.assertEqual(result["energy_status"], "SIMULATED_AT_ASSUMED_REGULATOR_OUTPUT_VOLTAGE")
        self.assertGreater(result["energy_wake_mj"], 0)
        self.assertEqual(result["model_provenance"]["regulator_output_v"]["status"], "ASSUMED")

    def test_trace_metadata_extends_integrated_window_and_daily_projection(self):
        rows = [dict(self.rows[0], trace_window_start_s=0.0, trace_window_end_s=10.0),
                dict(self.rows[1], trace_window_start_s=0.0, trace_window_end_s=10.0)]
        result = power.analyze_schedule(rows, self.assumptions, period_s=20.0)
        self.assertEqual(result["modeled_window_s"], 20.0)
        self.assertIsNotNone(result["mAh_per_day"])
        self.assertEqual(result["mAh_per_day_status"], "SIMULATED_EXTRAPOLATION_FROM_DECLARED_REPEAT_PERIOD")
        with self.assertRaisesRegex(ValueError, "disagree on trace window"):
            power.analyze_schedule([rows[0], dict(rows[1], trace_window_end_s=11.0)], self.assumptions)

    def test_invalid_electrical_overrides_are_rejected(self):
        for override in ({"regulator_efficiency": 0}, {"battery_voltage_v": float("nan")},
                         {"output_capacitance_f": -1}):
            with self.subTest(override=override):
                with self.assertRaises(ValueError):
                    power.generate_netlist(self.rows, self.assumptions, overrides=override)

    def test_ngspice_success_requires_measurements_and_valid_waveform(self):
        with tempfile.TemporaryDirectory() as tmp:
            deck = Path(tmp) / "power_trace.cir"
            deck.write_text(".param VREG=3.3\n")
            completed = __import__("subprocess").CompletedProcess([], 0, "rail_min = 3.1\nrail_max = 3.3\nbattery_min = 3.5\nbattery_current_peak = -0.02\n", "")
            def run(*args, **kwargs):
                (Path(tmp) / "power_waveform.dat").write_text("0 3.3 -0.01\n1 3.1 -0.02\n2 3.3 -0.01\n")
                return completed
            with patch.object(power.shutil, "which", return_value="ngspice"), patch.object(power.subprocess, "run", side_effect=run):
                result = power._run_ngspice(deck, None, self.rows)
        self.assertEqual(result["status"], "EXECUTED")
        self.assertAlmostEqual(result["voltage_droop_v"], 0.2)
        self.assertAlmostEqual(result["battery_current_peak_a"], 0.02)

    def test_ngspice_missing_convergence_results_is_failed_not_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            deck = Path(tmp) / "power_trace.cir"
            deck.write_text(".param VREG=3.3\n")
            completed = __import__("subprocess").CompletedProcess([], 0, "tran analysis failed: timestep too small\n", "")
            with patch.object(power.shutil, "which", return_value="ngspice"), patch.object(power.subprocess, "run", return_value=completed):
                result = power._run_ngspice(deck, None, self.rows)
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("waveform output is missing", result["detail"])


if __name__ == "__main__":
    unittest.main()
