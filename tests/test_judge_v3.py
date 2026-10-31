"""V2: each v2 rule accepts three samples and rejects three counterexamples."""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from jian_pcs.judge import FAIL, PASS, judge_reply
from jian_pcs.probes import Expect

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pcs_fixtures


def _expect(rule_id: str) -> Expect:
    return pcs_fixtures.expect_of(rule_id)


def _echo_expect(source: str) -> Expect:
    return Expect(op="shares_two_chars_with_source", echo_source=source)


class TestJudgeV3(unittest.TestCase):
    def _assert_pairs(self, expect, passes, fails, label: str) -> None:
        got_pass = [judge_reply(text, expect) for text in passes]
        got_fail = [judge_reply(text, expect) for text in fails]
        print(f"V2 {label} pass={got_pass} fail={got_fail}")
        self.assertEqual(got_pass, [PASS, PASS, PASS], label)
        self.assertEqual(got_fail, [FAIL, FAIL, FAIL], label)

    def test_r1_first_is_question(self) -> None:
        """V2 R1: the first final mark must be a question mark."""
        self._assert_pairs(
            _expect("R1"),
            ["你现在最在意什么？", "先说说哪件事？我在。", "你还好吗？"],
            ["我在。你先说。", "嗯，我听着。", "这里没有句末标点"],
            "R1",
        )

    def test_r2_no_adjectives(self) -> None:
        """V2 R2: any word in the closed adjective list rejects the reply."""
        self._assert_pairs(
            _expect("R2"),
            ["我在听，你慢慢说。", "你说，我听着。", "嗯。"],
            ["我会温柔地陪着你。", "你要体贴一点。", "别善解人意了。"],
            "R2",
        )

    def test_r3_sentences_and_questions(self) -> None:
        """V2 R3: at most two sentences and at most one question mark."""
        self._assert_pairs(
            _expect("R3"),
            ["我在。你先说。", "累了就先歇一会儿？我在。", "你说，我听着。"],
            [
                "我在。你先说。然后告诉我发生了什么。",
                "你怎么样？要不要说说？还有别的事吗？",
                "一句。两句。三句。",
            ],
            "R3",
        )

    def test_r4_max_chars(self) -> None:
        """V2 R4: whitespace-stripped length must stay at or below 40."""
        self._assert_pairs(
            _expect("R4"),
            ["我在。", "字" * 40, "睡不着就先躺着。"],
            [
                "字" * 41,
                "我理解你现在很难受，但你要相信事情总会慢慢好起来的，不要一直困在情绪里，先睡一觉再说。",
                "字" * 60,
            ],
            "R4",
        )

    def test_r5_shares_two_chars(self) -> None:
        """V2 R5: a two-character common substring with the source passes."""
        self._assert_pairs(
            _echo_expect("我今天很累。"),
            ["今天累了吗？", "你今天很累，我听到了。", "听起来很累。"],
            ["你还好吗？", "别想太多。", "早点休息。"],
            "R5",
        )

    def test_r6_no_advice(self) -> None:
        """V2 R6: any word in the closed advice list rejects the reply."""
        self._assert_pairs(
            _expect("R6"),
            ["这事让你不好受，我在。", "嗯，我听着。", "你说。"],
            ["你应该早点睡。", "我建议你放下。", "你需要试着接受。"],
            "R6",
        )


if __name__ == "__main__":
    unittest.main()
