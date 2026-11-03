"""C2: timex A/B/C accuracy, malformed tolerance, anchor validation."""

from __future__ import annotations

import json
import pathlib
import unittest

from aiinvite.cn.errors import CnError, E_CN_BAD_ANCHOR, E_CN_PARSE
from aiinvite.cn.timex import parse_time

DATA = pathlib.Path(__file__).resolve().parents[1] / "aiinvite/cn" / "data"
ANCHOR = "2026-10-29T10:00:00+08:00"

# Spec 4.6 holdout: given by the spec owner, never stored in any data file.
HOLDOUT: tuple[dict[str, str], ...] = (
    {"expr": "大前年", "start": "2023-01-01", "end": "2023-12-31",
     "granularity": "year", "certainty": "range"},
    {"expr": "两年前", "start": "2024-10-29", "end": "2024-10-29",
     "granularity": "day", "certainty": "exact"},
    {"expr": "前年这时候", "start": "2024-10-29", "end": "2024-10-29",
     "granularity": "day", "certainty": "exact"},
    {"expr": "下下周", "start": "2026-11-09", "end": "2026-11-15",
     "granularity": "week", "certainty": "range"},
    {"expr": "下下个月", "start": "2026-12-01", "end": "2026-12-31",
     "granularity": "month", "certainty": "range"},
    {"expr": "一个月后", "start": "2026-11-29", "end": "2026-11-29",
     "granularity": "day", "certainty": "exact"},
    {"expr": "十天后", "start": "2026-11-08", "end": "2026-11-08",
     "granularity": "day", "certainty": "exact"},
    {"expr": "半年后", "start": "2027-04-29", "end": "2027-04-29",
     "granularity": "day", "certainty": "exact"},
    {"expr": "明年初", "start": "2027-01-01", "end": "2027-04-30",
     "granularity": "year", "certainty": "range"},
    {"expr": "明年底", "start": "2027-10-01", "end": "2027-12-31",
     "granularity": "year", "certainty": "range"},
    {"expr": "上季度末", "start": "2026-09-01", "end": "2026-09-30",
     "granularity": "month", "certainty": "range"},
    {"expr": "大后天", "start": "2026-11-01", "end": "2026-11-01",
     "granularity": "day", "certainty": "exact"},
    {"expr": "后年", "start": "2028-01-01", "end": "2028-12-31",
     "granularity": "year", "certainty": "range"},
    {"expr": "这个季度末", "start": "2026-12-01", "end": "2026-12-31",
     "granularity": "month", "certainty": "range"},
)


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
        """C2: all 50 malformed inputs raise the exact code named by their own row."""
        for row in self.data["malformed"]:
            with self.subTest(expr=row["expr"], error=row["error"]):
                self.assertIn(row["error"], {E_CN_PARSE, E_CN_BAD_ANCHOR})
                with self.assertRaises(CnError) as ctx:
                    parse_time(row["expr"], row["anchor"])
                self.assertEqual(ctx.exception.code, row["error"])

    def test_malformed_entries_do_not_overlap_valid_rows(self) -> None:
        """Spec 4.8: conflict check keys on (expr, anchor), not on expr alone."""
        keys = {(row["expr"], row["anchor"]) for row in self.data["malformed"]}
        for row in self.data["A"]:
            with self.subTest(expr=row["expr"], anchor=row["anchor"]):
                self.assertNotIn((row["expr"], row["anchor"]), keys)

    def test_4_6_holdout_composition(self) -> None:
        """C2: the 14 spec holdout expressions must reach 0.90 with one fixed anchor."""
        matched = 0
        misses: list[str] = []
        for row in HOLDOUT:
            span = parse_time(row["expr"], ANCHOR).to_dict()
            if all(span[key] == row[key]
                   for key in ("start", "end", "granularity", "certainty")):
                matched += 1
            else:
                misses.append(f"{row['expr']}={span}")
        self.assertGreaterEqual(matched / len(HOLDOUT), 0.90, f"misses: {misses}")

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
