"""U1: the M7 hard probe set is complete and traceable to self.md."""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pcs_fixtures

from jian_pcs.probes import (
    HARD_KINDS,
    HARD_PROBE_COUNT,
    PROBE_COUNT,
    load_all_probes,
    load_hard_probes,
    load_probes,
)


class TestHardProbes(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probes = load_hard_probes()
        cls.self_md = pcs_fixtures.build_self_md()

    def test_eighteen_hard_probes(self) -> None:
        """U1: exactly 18 probes, 6 per kind, every id unique."""
        print(f"U1 hard probes={len(self.probes)}")
        self.assertEqual(len(self.probes), HARD_PROBE_COUNT)
        ids = [probe.probe_id for probe in self.probes]
        self.assertEqual(len(set(ids)), HARD_PROBE_COUNT)
        counts = {
            kind: sum(1 for probe in self.probes if probe.kind == kind)
            for kind in HARD_KINDS
        }
        print(f"U1 kinds={counts}")
        self.assertEqual(counts, {kind: 6 for kind in HARD_KINDS})
        for probe in self.probes:
            self.assertGreaterEqual(len(probe.turns), 2)
            self.assertLessEqual(len(probe.turns), 6)
            self.assertGreaterEqual(len(probe.accept), 2)
            self.assertLessEqual(len(probe.accept), 3)
            self.assertTrue(probe.violation.strip())
            self.assertTrue(probe.expect.must_contain_any
                            or probe.expect.must_not_contain_any
                            or probe.expect.max_chars is not None
                            or probe.expect.max_questions is not None
                            or probe.expect.must_ask_before is not None
                            or probe.expect.max_sentences is not None
                            or probe.expect.must_not_apologize
                            or probe.expect.max_agreement_shifts is not None)

    def test_rules_come_from_self_md(self) -> None:
        """U1: every hard probe rule literally appears in the compiled self.md."""
        missing = [
            probe.rule for probe in self.probes
            if probe.rule not in self.self_md
        ]
        print(f"U1 hard rules={len({p.rule for p in self.probes})} missing={missing}")
        self.assertEqual(missing, [])

    def test_m6_set_is_untouched_and_merge_is_clean(self) -> None:
        """U1: load_probes still returns 30, and merged ids do not collide."""
        m6 = load_probes()
        merged = load_all_probes()
        print(f"U1 m6={len(m6)} merged={len(merged)}")
        self.assertEqual(len(m6), PROBE_COUNT)
        self.assertEqual(len(merged), PROBE_COUNT + HARD_PROBE_COUNT)
        self.assertEqual(len({probe.probe_id for probe in merged}), len(merged))
        for probe in m6:
            self.assertEqual(probe.kind, "single_turn")


if __name__ == "__main__":
    unittest.main()
