"""T2: every known violation must be rejected before any pass is trusted."""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pcs_fixtures

from jian_pcs.judge import FAIL, PASS, UNKNOWN, judge_reply, violation_rejected
from jian_pcs.probes import load_probes


class TestJudge(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probes = load_probes()

    def test_every_violation_is_rejected(self) -> None:
        """T2: each probe's violation is judged fail; one survivor fails T2."""
        survived = [
            probe.probe_id for probe in self.probes
            if not violation_rejected(probe)
        ]
        print(f"T2 violations={len(self.probes)} survived={survived}")
        self.assertEqual(survived, [])

    def test_legal_replies_pass(self) -> None:
        """T2: the compliant reply for each rule passes its probes."""
        bad = []
        for probe in self.probes:
            verdict = judge_reply(pcs_fixtures.LEGAL[probe.rule], probe.expect)
            if verdict != PASS:
                bad.append((probe.probe_id, verdict))
        print(f"T2 legal bad={bad}")
        self.assertEqual(bad, [])

    def test_empty_reply_is_unknown(self) -> None:
        """T2: empty and whitespace replies are unknown, never a pass."""
        for probe in self.probes[:3]:
            self.assertEqual(judge_reply("", probe.expect), UNKNOWN)
            self.assertEqual(judge_reply("   \n", probe.expect), UNKNOWN)
        self.assertEqual(judge_reply("", self.probes[0].expect), UNKNOWN)
        self.assertEqual(judge_reply("我在。", self.probes[15].expect), FAIL)


if __name__ == "__main__":
    unittest.main()
