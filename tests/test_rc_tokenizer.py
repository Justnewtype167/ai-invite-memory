"""R1: token estimation and Han bigram vectors."""

from __future__ import annotations

import unittest

from jian_recall.tokenizer import bigrams, estimate_tokens

VECTORS = (
    ("", 8),
    ("手术很顺利", 13),
    ("你好", 10),
    ("a", 9),
    ("hello", 10),
    ("hello world", 11),
    ("abcde", 10),
    ("a b c", 11),
    ("12345", 11),
    ("12", 9),
    ("，", 9),
    ("。", 9),
    ("你好，", 11),
    ("hello，", 11),
    ("我叫Tom", 11),
    ("2026年", 11),
    ("a-b", 11),
    ("  ", 8),
    ("今天天气不错", 14),
    ("好", 9),
)


class TestTokenizer(unittest.TestCase):
    def test_fixed_vectors(self) -> None:
        """R1: twenty fixed estimator vectors."""
        for text, expected in VECTORS:
            with self.subTest(text=text):
                self.assertEqual(estimate_tokens(text), expected)

    def test_bigrams_overlap(self) -> None:
        """R1: Han runs become overlapping bigrams."""
        self.assertEqual(bigrams("手术很顺利"), "手术 术很 很顺 顺利")

    def test_bigrams_edges(self) -> None:
        """R1: empty, single Han, ASCII and mixed runs."""
        self.assertEqual(bigrams(""), "")
        self.assertEqual(bigrams("好"), "好")
        self.assertEqual(bigrams("abc"), "")
        self.assertEqual(bigrams("你好abc世界"), "你好 世界")
        self.assertEqual(bigrams("手术后abc恢复"), "手术 术后 恢复")

    def test_estimate_grows_with_length(self) -> None:
        """R1: a longer message never costs less than a shorter prefix."""
        shorter = estimate_tokens("今天")
        longer = estimate_tokens("今天天气不错")
        self.assertLess(shorter, longer)


if __name__ == "__main__":
    unittest.main()
