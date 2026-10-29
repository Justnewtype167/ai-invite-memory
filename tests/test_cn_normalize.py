"""C4: normalization coverage, idempotence, no reverse conversion."""

from __future__ import annotations

import json
import pathlib
import unittest

from jian_cn.normalize import normalize

DATA = pathlib.Path(__file__).resolve().parents[1] / "jian_cn" / "data"


def _pairs() -> list[list[str]]:
    payload = json.loads((DATA / "variants.json").read_bytes().decode("utf-8"))
    return payload["pairs"]


class TestNormalize(unittest.TestCase):
    def test_coverage_on_200_characters(self) -> None:
        """C4: at least 0.99 of a 200-character traditional sample converts."""
        pairs = _pairs()
        sample = [pair for pair in pairs if pair[0] != pair[1]][:200]
        self.assertGreaterEqual(len(sample), 200)
        converted = 0
        for trad, simp in sample:
            out = normalize(trad)
            if out == simp:
                converted += 1
        self.assertGreaterEqual(converted / 200, 0.99)

    def test_idempotent(self) -> None:
        """C4: normalize(normalize(x)) equals normalize(x)."""
        for text in ("臺灣裏面", "ＡＢＣ　１２３", "  a \u200b b ", "e\u0301", "爸爸 的 哥哥"):
            once = normalize(text)
            self.assertEqual(normalize(once), once)

    def test_simplified_and_ascii_are_unchanged(self) -> None:
        """C4: simplified Chinese and pure ASCII pass through untouched."""
        for text in ("我们明天去看电影", "Hello World 123", ""):
            self.assertEqual(normalize(text), text)

    def test_reverse_conversion_does_not_exist(self) -> None:
        """C4: every simplified key stays simplified; no simplified to traditional path."""
        for trad, simp in _pairs():
            self.assertEqual(normalize(simp), simp, f"{simp} must not change")
        self.assertEqual(normalize("台湾里面"), "台湾里面")

    def test_fullwidth_zero_width_and_whitespace(self) -> None:
        """Full-width ASCII becomes half-width; zero-width is dropped; spaces collapse."""
        self.assertEqual(normalize("ＡＢＣ１２３"), "ABC123")
        self.assertEqual(normalize("ａ\u200bｂ"), "ab")
        self.assertEqual(normalize("a \n\t b"), "a b")

    def test_traditional_sample(self) -> None:
        """The demo string from the spec converts character by character."""
        self.assertEqual(normalize("臺灣裏面"), "台湾里面")


if __name__ == "__main__":
    unittest.main()
