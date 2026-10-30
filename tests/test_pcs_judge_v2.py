"""U2: the v2 operators reject counterexamples; both fences still hold."""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pcs_fixtures

from jian_pcs.judge import FAIL, PASS, accepts_pass, judge_reply, violation_rejected
from jian_pcs.probes import load_hard_probes


class TestJudgeV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probes = load_hard_probes()

    def test_first_is_question(self) -> None:
        """U2: only a reply whose first final mark is ？ passes."""
        expect = pcs_fixtures.expect_of("R1")
        self.assertEqual(judge_reply("你现在最在意什么？", expect), PASS)
        self.assertEqual(judge_reply("先说说哪件事？我在。", expect), PASS)
        self.assertEqual(judge_reply("我在。你先说。", expect), FAIL)
        self.assertEqual(judge_reply("嗯，我听着。", expect), FAIL)
        self.assertEqual(judge_reply("没有句末标点", expect), FAIL)

    def test_none_of_closed_word_list(self) -> None:
        """U2: any word from the rule's closed list fails the reply."""
        expect = pcs_fixtures.expect_of("R2")
        self.assertEqual(judge_reply("我在听，你慢慢说。", expect), PASS)
        self.assertEqual(judge_reply("我会温柔地陪着你。", expect), FAIL)
        self.assertEqual(judge_reply("你要体贴一点。", expect), FAIL)
        self.assertEqual(judge_reply("别善解人意了。", expect), FAIL)

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
