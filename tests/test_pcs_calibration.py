"""U4: the hard probe set carries its calibration record as data."""

from __future__ import annotations

import json
import unittest

from aiinvite.pcs.probes import (
    CALIBRATION_HIGH,
    CALIBRATION_LOW,
    CALIBRATION_PATH,
    HARD_PROBE_COUNT,
    load_hard_probes,
)

REQUIRED = (
    "model", "temp_milli", "seed", "probes", "c_final", "r", "d", "first_rule",
)


class TestCalibration(unittest.TestCase):
    def test_metadata_exists_and_is_well_formed(self) -> None:
        """U4: calibration.json exists, has every field and a legal band."""
        self.assertTrue(CALIBRATION_PATH.exists())
        data = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
        missing = [name for name in REQUIRED if name not in data]
        print(
            f"U4 missing={missing} c_final={data.get('c_final')} "
            f"r={data.get('r')} d={data.get('d')}"
        )
        self.assertEqual(missing, [])
        self.assertIsInstance(data["model"], str)
        self.assertTrue(data["model"])
        self.assertEqual(data["temp_milli"], 0, "calibration must be at temp 0")
        self.assertIsInstance(data["seed"], int)
        self.assertEqual(data["probes"], HARD_PROBE_COUNT)
        self.assertIsInstance(data["c_final"], float)
        self.assertGreaterEqual(data["c_final"], CALIBRATION_LOW)
        self.assertLessEqual(data["c_final"], CALIBRATION_HIGH)
        self.assertIsInstance(data["r"], float)
        self.assertGreaterEqual(data["r"], 0.0)
        self.assertLessEqual(data["r"], 1.0)
        self.assertIsInstance(data["d"], float)
        self.assertGreater(data["d"], 0.0)
        self.assertLessEqual(data["d"], 1.0)
        rules = {probe.rule for probe in load_hard_probes()}
        self.assertIn(data["first_rule"], rules)
        self.assertEqual(
            sorted(data), sorted(REQUIRED), "unexpected calibration fields"
        )


if __name__ == "__main__":
    unittest.main()
