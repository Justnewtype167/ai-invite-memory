"""T1: the probe set is complete, legal and bound to rules_v2."""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from jian_pcs.probes import (
    PROBE_COUNT, V2_OPERATORS, load_probes, load_rules_v2,
)


class TestProbes(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probes = load_probes()
        cls.rules = load_rules_v2()

    def test_thirty_unique_probes(self) -> None:
        """T1: exactly 30 probes with unique ids and all six fields."""
        print(f"T1 probes={len(self.probes)}")
        self.assertEqual(len(self.probes), PROBE_COUNT)
        ids = [probe.probe_id for probe in self.probes]
        self.assertEqual(len(set(ids)), PROBE_COUNT)
        for probe in self.probes:
            self.assertTrue(probe.prompt)
            self.assertTrue(probe.violation)
            self.assertGreaterEqual(len(probe.accept), 2)
            self.assertLessEqual(len(probe.accept), 3)
            for text in probe.accept:
                self.assertTrue(text.strip())
            self.assertEqual(len(set(probe.accept)), len(probe.accept))
            self.assertIn(probe.expect.op, V2_OPERATORS)

    def test_every_rule_comes_from_rules_v2(self) -> None:
        """T1: every probe names a rule that the v2 rule file defines."""
        known = {rule.rule_id for rule in self.rules}
        missing = [probe.rule for probe in self.probes if probe.rule not in known]
        print(f"T1 rules={len({p.rule for p in self.probes})} missing={missing}")
        self.assertEqual(missing, [])
        self.assertEqual(len(known), 6)


if __name__ == "__main__":
    unittest.main()
