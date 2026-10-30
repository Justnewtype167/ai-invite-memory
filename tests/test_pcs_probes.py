"""T1: the probe set is complete, legal and traceable to self.md."""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pcs_fixtures

from jian_pcs.probes import PROBE_COUNT, load_probes


class TestProbes(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probes = load_probes()
        cls.self_md = pcs_fixtures.build_self_md()

    def test_thirty_unique_probes(self) -> None:
        """T1: exactly 30 probes with unique ids and all five fields."""
        print(f"T1 probes={len(self.probes)}")
        self.assertEqual(len(self.probes), PROBE_COUNT)
        ids = [probe.probe_id for probe in self.probes]
        self.assertEqual(len(set(ids)), PROBE_COUNT)
        for probe in self.probes:
            self.assertTrue(probe.prompt)
            self.assertTrue(probe.violation)
            expect = probe.expect
            self.assertTrue(
                expect.must_contain_any or expect.must_not_contain_any
                or expect.max_chars is not None
                or expect.max_questions is not None
                or expect.must_ask_before is not None
                or expect.max_sentences is not None
            )

    def test_every_rule_is_in_self_md(self) -> None:
        """T1: every probe rule literally appears in the compiled self.md."""
        missing = [
            probe.rule for probe in self.probes
            if probe.rule not in self.self_md
        ]
        print(f"T1 rules={len({p.rule for p in self.probes})} missing={missing}")
        self.assertEqual(missing, [])
        self.assertIn("## Style", self.self_md)
        self.assertIn("## Conduct", self.self_md)


if __name__ == "__main__":
    unittest.main()
