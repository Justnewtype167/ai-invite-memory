"""R5: same-day history and unfinished promise triggers."""

from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import rc_fixtures

from aiinvite.recall.index import build_index
from aiinvite.recall.trigger import triggers

NOW = "2026-10-29T10:00:00+08:00"


class TestTrigger(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_rc_trig_"))
        events = [
            ("2021-10-29T09:00:00Z", "四年前的今天搬了一次家"),
            ("2022-10-29T09:00:00Z", "三年前的今天去看了海"),
            ("2023-10-29T09:00:00Z", "两年前的今天换了工作"),
            ("2024-10-29T09:00:00Z", "一年前的今天丢了钥匙"),
            ("2026-10-29T09:00:00Z", "今年同一天还在加班"),
            ("2025-03-01T10:00:00Z", "我答应过你下次一定带你去看海"),
            ("2024-06-01T10:00:00Z", "我保证以后早点回家"),
            ("2023-08-01T10:00:00Z", "说好了周末一起爬山"),
            ("2025-01-01T10:00:00Z", "我答应的事情已完成"),
            ("2024-02-01T10:00:00Z", "说好的事我已经做了"),
            ("2022-05-01T10:00:00Z", "普通的一天在整理书架"),
        ]
        rc_fixtures.write_store(cls.root, events)
        build_index(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root, True)

    def test_same_day_history(self) -> None:
        """R5: at most three same month-day hits, all from earlier years."""
        hits = triggers(self.root, NOW)
        same = [hit for hit in hits if hit.ts[5:10] == "10-29"]
        self.assertEqual(len(same), 3)
        for hit in same:
            self.assertLess(int(hit.ts[:4]), 2026)
            self.assertEqual(hit.ts[5:10], "10-29")
        self.assertEqual(
            [hit.ts[:4] for hit in same], ["2024", "2023", "2022"]
        )

    def test_unfinished_promises(self) -> None:
        """R5: promises hit, finished ones are excluded, at most two."""
        hits = triggers(self.root, NOW)
        promises = [hit for hit in hits if hit.ts[5:10] != "10-29"]
        self.assertEqual(len(promises), 2)
        for hit in promises:
            self.assertTrue(
                any(word in hit.text for word in ("答应", "保证", "说好", "下次一定"))
            )
            self.assertNotIn("已", hit.text)
            self.assertNotIn("完成了", hit.text)

    def test_total_order_and_limit(self) -> None:
        """R5: same-day hits come first and the list stays small."""
        hits = triggers(self.root, NOW)
        self.assertEqual(len(hits), 5)
        self.assertTrue(all(hit.score == 1.0 for hit in hits[:3]))
        self.assertTrue(all(hit.score < 1.0 for hit in hits[3:]))
        self.assertEqual(len({hit.event_id for hit in hits}), 5)


if __name__ == "__main__":
    unittest.main()
