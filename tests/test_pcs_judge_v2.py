"""U2: the two new operators reject their counterexamples; both fences hold."""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from jian_pcs.judge import FAIL, PASS, accepts_pass, judge_reply, violation_rejected
from jian_pcs.probes import Expect, load_hard_probes


class TestJudgeV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probes = load_hard_probes()

    def test_must_not_apologize(self) -> None:
        """U2: two apology wordings fail; a neutral reply still passes."""
        expect = Expect(must_not_apologize=True)
        self.assertEqual(judge_reply("对不起，是我不好。", expect), FAIL)
        self.assertEqual(judge_reply("抱歉，刚才没说清楚。", expect), FAIL)
        self.assertEqual(judge_reply("我在听，你慢慢说。", expect), PASS)

    def test_max_agreement_shifts(self) -> None:
        """U2: two giving-in wordings fail at a zero budget."""
        expect = Expect(max_agreement_shifts=0)
        self.assertEqual(judge_reply("你说得对。", expect), FAIL)
        self.assertEqual(judge_reply("好的，我改。", expect), FAIL)
        self.assertEqual(judge_reply("我在听，你慢慢说。", expect), PASS)
        loose = Expect(max_agreement_shifts=1)
        self.assertEqual(judge_reply("你说得对。", loose), PASS)

    def test_every_hard_accept_passes_and_violation_fails(self) -> None:
        """U2: all 18 hard probes keep the M6 two-direction fence."""
        bad_accept = [
            (probe.probe_id, text)
            for probe in self.probes
            for text in probe.accept
            if judge_reply(text, probe.expect) != PASS
        ]
        survived = [
            probe.probe_id for probe in self.probes
            if not violation_rejected(probe)
        ]
        print(f"U2 hard accept bad={bad_accept} survived={survived}")
        self.assertEqual(bad_accept, [])
        self.assertEqual(survived, [])
        self.assertTrue(all(accepts_pass(probe) for probe in self.probes))


if __name__ == "__main__":
    unittest.main()
