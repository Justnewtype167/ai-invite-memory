"""W2: the echo operator decides by a two-character common substring."""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from aiinvite.pcs.judge import FAIL, PASS, UNKNOWN, judge_reply
from aiinvite.pcs.probes import Expect

SOURCE = "我今天很累。"


def _judge(text: str) -> str:
    return judge_reply(
        text, Expect(op="shares_two_chars_with_source", echo_source=SOURCE)
    )


class TestEchoOp(unittest.TestCase):
    def test_shared_pair_passes(self) -> None:
        """W2: replies sharing a two-character run with the source pass."""
        cases = ["今天累了吗？", "你今天很累，我听到了。", "听起来很累。"]
        got = [_judge(text) for text in cases]
        print(f"W2 pass={got}")
        self.assertEqual(got, [PASS, PASS, PASS])

    def test_no_shared_pair_fails(self) -> None:
        """W2: replies with no shared pair are rejected."""
        cases = ["你还好吗？", "别想太多。", "早点休息。"]
        got = [_judge(text) for text in cases]
        print(f"W2 fail={got}")
        self.assertEqual(got, [FAIL, FAIL, FAIL])

    def test_punctuation_does_not_change_the_verdict(self) -> None:
        """W2: normalization drops punctuation and whitespace before matching."""
        cases = ["今天，很累！", "我 今 天 很 累", "今。天。很。累"]
        got = [_judge(text) for text in cases]
        print(f"W2 punctuation={got}")
        self.assertEqual(got, [PASS, PASS, PASS])

    def test_blank_source_is_unknown(self) -> None:
        """W2: R5 without a source sentence cannot be judged."""
        verdict = judge_reply(
            "我在。", Expect(op="shares_two_chars_with_source", echo_source="")
        )
        print(f"W2 blank-source={verdict}")
        self.assertEqual(verdict, UNKNOWN)


if __name__ == "__main__":
    unittest.main()
