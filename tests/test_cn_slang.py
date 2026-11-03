"""C3: slang holdout accuracy, monotonic decay, confidence rule."""

from __future__ import annotations

import json
import pathlib
import unittest
from datetime import date

from aiinvite.cn.slang import availability, explain, lifespan, usable

DATA = pathlib.Path(__file__).resolve().parents[1] / "aiinvite/cn" / "data"


def _json(name: str):
    return json.loads((DATA / name).read_bytes().decode("utf-8"))


def _entries() -> dict[str, dict]:
    return {row["term"]: row for row in _json("slang.json")["entries"]}


class TestSlang(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = _entries()
        self.holdout = _json("slang_holdout.json")

    def test_holdout_accuracy(self) -> None:
        """C3: usable decisions on the 24 holdout items must reach 0.90."""
        usable_rows = [r for r in self.holdout if self.entries[r["term"]]["confidence"] >= 60]
        self.assertGreaterEqual(len(usable_rows), 22)
        correct = sum(1 for r in usable_rows
                      if usable(r["term"], date(r["year"], 6, 1)) is r["usable"])
        self.assertGreaterEqual(correct / len(usable_rows), 0.90)

    def test_low_confidence_entries_are_display_only(self) -> None:
        """C3: confidence < 60 never participates in pass/fail judgment."""
        low = [t for t, row in self.entries.items() if row["confidence"] < 60]
        self.assertTrue(low)
        usable_rows = [r for r in self.holdout if r["term"] not in low]
        self.assertEqual(len(usable_rows), len(self.holdout))
        for term in low:
            self.assertIsNotNone(availability(term, date(2024, 1, 1)))

    def test_monotonic_after_peak(self) -> None:
        """C3: availability must never rise once the peak year has passed."""
        for term, row in self.entries.items():
            scores = [availability(term, date(year, 6, 1))
                      for year in range(row["peak"], row["cringe"] + 3)]
            for earlier, later in zip(scores, scores[1:]):
                self.assertGreaterEqual(earlier, later, f"{term}: {scores}")

    def test_curve_anchor_values(self) -> None:
        """Formula anchors: 0 before born, 1000 at peak, 400 at cringe, 200 after."""
        for term, row in self.entries.items():
            with self.subTest(term=term):
                self.assertEqual(availability(term, date(row["born"] - 1, 6, 1)), 0)
                self.assertEqual(availability(term, date(row["peak"], 6, 1)), 1000)
                self.assertEqual(availability(term, date(row["cringe"], 6, 1)), 400)
                self.assertEqual(availability(term, date(row["cringe"] + 1, 6, 1)), 200)

    def test_threshold_and_unknown_terms(self) -> None:
        """usable applies the threshold; unknown terms are None/False, not guessed."""
        self.assertIsNone(availability("不存在的梗", date(2026, 1, 1)))
        self.assertFalse(usable("不存在的梗", date(2026, 1, 1)))
        self.assertEqual(explain("不存在的梗", date(2026, 1, 1)), "未收录")
        self.assertIsNone(lifespan("不存在的梗"))
        self.assertTrue(usable("yyds", date(2021, 6, 1)))
        self.assertFalse(usable("yyds", date(2026, 6, 1)))

    def test_explain_mentions_peak_and_age(self) -> None:
        """explain is human-readable and states peak year plus years past it."""
        text = explain("yyds", date(2026, 6, 1))
        self.assertIn("2021", text)
        self.assertIn("已过时 5 年", text)

    def test_lifespan_shape(self) -> None:
        """lifespan returns the three anchor years with source and confidence."""
        info = lifespan("yyds")
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual((info["born"], info["peak"], info["cringe"]), (2020, 2021, 2023))
        self.assertIn("source", info)
        self.assertIn("confidence", info)


if __name__ == "__main__":
    unittest.main()
