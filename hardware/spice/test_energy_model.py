import json
import unittest
from pathlib import Path

from energy_model import DEFAULT_CONFIG, calculate


class EnergyModelTest(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(Path(DEFAULT_CONFIG).read_text())

    def test_day_is_partitioned_and_candidate_autonomy_is_explicit(self):
        result = calculate(self.config)
        self.assertAlmostEqual(sum(s["duration_s_day"] for s in result["states"]), 86400)
        self.assertGreater(result["daily_charge_mah"], 0)
        self.assertEqual(result["messages_per_day"], 96)
        self.assertLess(result["daily_charge_mah"], 0.5)
        self.assertGreater(result["daily_charge_mah"], 0.2)
        self.assertAlmostEqual(result["estimated_battery_life_days"],
                               1100 / result["daily_charge_mah"])
        self.assertEqual(result["autonomy_status"], "CALCULATED_FROM_EXPLICIT_CAPACITY")
        self.assertGreater(result["states"][0]["current_ma"],
                           result["states"][0]["rail_current_ma"])

    def test_autonomy_requires_explicit_capacity(self):
        result = calculate(self.config, 2200)
        self.assertAlmostEqual(result["estimated_battery_life_days"], 2200 / result["daily_charge_mah"])
        self.assertEqual(result["autonomy_status"], "CALCULATED_FROM_EXPLICIT_CAPACITY")

    def test_invalid_full_day_schedule_rejected(self):
        self.config["tx_duration_s"] = 1000
        with self.assertRaises(ValueError):
            calculate(self.config)

    def test_invalid_regulator_efficiency_rejected(self):
        self.config["regulator"]["efficiency_assumption"] = 1.1
        with self.assertRaises(ValueError):
            calculate(self.config)


if __name__ == "__main__":
    unittest.main()
