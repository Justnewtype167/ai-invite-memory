"""C2: timex A/B/C accuracy, malformed tolerance, anchor validation."""

from __future__ import annotations

import json
import pathlib
import unittest

from jian_cn.errors import CnError, E_CN_BAD_ANCHOR, E_CN_PARSE
from jian_cn.timex import parse_time

DATA = pathlib.Path(__file__).resolve().parents[1] / "jian_cn" / "data"


def _labels() -> dict:
    return json.loads((DATA / "timex_labels.json").read_bytes().decode("utf-8"))


class TestTimex(unittest.TestCase):
    def setUp(self) -> None:
        self.data = _labels()

    def test_a_class_exact_rate(self) -> None:
        """C2: A-class start/end/granularity/certainty agreement must reach 0.95."""
        rows = self.data["A"]
        matched = 0
        misses: list[str] = []
        for row in rows:
            span = parse_time(row["expr"], row["anchor"]).to_dict()
            if all(span[key] == row[key]
                   for key in ("start", "end", "granularity", "certainty")):
                matched += 1
            else:
                misses.append(row["expr"])
        self.assertGreaterEqual(matched / len(rows), 0.95, f"misses: {misses}")

    def test_b_class_vague_without_range(self) -> None:
        """C2: B-class matches certainty/granularity and never invents a range."""
        rows = self.data["B"]
        matched = 0
        for row in rows:
            span = parse_time(row["expr"], row["anchor"]).to_dict()
            self.assertIsNone(span["start"])
            self.assertIsNone(span["end"])
            if span["granularity"] == row["granularity"] and span["certainty"] == row["certainty"]:
                matched += 1
        self.assertGreaterEqual(matched / len(rows), 0.90)

    def test_c_class_lunar_is_not_supported(self) -> None:
        """C2: every lunar/solar-term expression raises E_CN_PARSE mentioning 农历."""
        for row in self.data["C"]:
            with self.subTest(expr=row["expr"]):
                with self.assertRaises(CnError) as ctx:
                    parse_time(row["expr"], row["anchor"])
                self.assertEqual(ctx.exception.code, E_CN_PARSE)
                self.assertIn("农历", ctx.exception.message)

    def test_malformed_never_crashes(self) -> None:
        """C2: all 50 malformed inputs raise a coded CnError, never an arbitrary one."""
        for row in self.data["malformed"]:
            with self.subTest(expr=row["expr"], error=row["error"]):
                with self.assertRaises(CnError) as ctx:
                    parse_time(row["expr"], row["anchor"])
                self.assertEqual(ctx.exception.code, row["error"])

    def test_anchor_requires_timezone(self) -> None:
        """Spec 7: missing or naive anchors raise E_CN_BAD_ANCHOR."""
        for anchor in (None, "2026-10-29T10:00:00", "not-a-time"):
            with self.subTest(anchor=anchor):
                with self.assertRaises(CnError) as ctx:
                    parse_time("今天", anchor)
                self.assertEqual(ctx.exception.code, E_CN_BAD_ANCHOR)

    def test_month_third_rule_is_computed_not_hardcoded(self) -> None:
        """A 28-day month splits into 1-9 / 10-18 / 19-28, proving the k rule."""
        span = parse_time("月初", "2026-02-15T00:00:00+08:00").to_dict()
        self.assertEqual((span["start"], span["end"]), ("2026-02-01", "2026-02-09"))
        span = parse_time("月中", "2026-02-15T00:00:00+08:00").to_dict()
        self.assertEqual((span["start"], span["end"]), ("2026-02-10", "2026-02-18"))
        span = parse_time("月底", "2026-02-15T00:00:00+08:00").to_dict()
        self.assertEqual((span["start"], span["end"]), ("2026-02-19", "2026-02-28"))

    def test_leap_day_falls_back_to_28th(self) -> None:
        """Year shifting from Feb 29 clamps instead of crashing."""
        span = parse_time("去年这时候", "2028-02-29T10:00:00+08:00").to_dict()
        self.assertEqual((span["start"], span["end"]), ("2027-02-28", "2027-02-28"))

    def test_unknown_expression_raises_parse_error(self) -> None:
        """Anything outside the rule table raises E_CN_PARSE."""
        with self.assertRaises(CnError) as ctx:
            parse_time("下午", "2026-10-29T10:00:00+08:00")
        self.assertEqual(ctx.exception.code, E_CN_PARSE)


if __name__ == "__main__":
    unittest.main()
