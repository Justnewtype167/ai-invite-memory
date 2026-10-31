"""R2: rebuildable index, incremental update, stale detection, reconciliation."""

from __future__ import annotations

import pathlib
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import rc_fixtures

from jian_recall.assemble import assemble
from jian_recall.errors import E_RC_NO_INDEX, E_RC_STALE, RecallError
from jian_recall.index import (
    INDEX_DIR,
    INDEX_FILE,
    build_index,
    evidence_tail,
    index_status,
    update_index,
)
from jian_recall.retrieve import search


def _events(count: int, start_day: int = 1) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for index in range(count):
        day = start_day + index // 60
        minute = index % 60
        stamp = f"2023-01-{day:02d}T10:{minute:02d}:00Z"
        result.append((stamp, f"第{index + 1}条日程记录"))
    return result


class TestIndex(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_rc_idx_"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_01_build_speed_on_200k(self) -> None:
        """R2.1: indexing 200000 events stays under a load-tolerant bound."""
        store = rc_fixtures.bulk_store()
        start = time.perf_counter()
        status = build_index(store)
        elapsed = time.perf_counter() - start
        print(f"R2.1 build 200000 events: {elapsed:.2f}s")
        # Sanity bound, not an SLO: 200k build is ~12s idle, and the point of
        # the gate is to catch a quadratic regression under any machine load.
        self.assertLess(elapsed, 600.0)
        self.assertEqual(status.events_indexed, 200000)
        self.assertEqual(status.lsn, evidence_tail(store))
        self.assertFalse(status.stale)

    def test_02_rebuild_matches_head_count(self) -> None:
        """R2.2: deleting .index/ and rebuilding gives the same head and count."""
        events = _events(250)
        rc_fixtures.write_store(self.root, events)
        first = build_index(self.root)
        shutil.rmtree(self.root / INDEX_DIR)
        second = build_index(self.root)
        self.assertEqual(first.lsn, second.lsn)
        self.assertEqual(first.events_indexed, second.events_indexed)
        self.assertEqual(second.lsn, evidence_tail(self.root))
        self.assertFalse(index_status(self.root).stale)

    def test_03_incremental_update(self) -> None:
        """R2.3: update_index indexes only events after the head."""
        rc_fixtures.write_store(self.root, _events(30))
        build_index(self.root)
        rc_fixtures.append_store(
            self.root,
            [("2023-02-01T09:00:00Z", "新写下的一条事件") for _ in range(12)],
        )
        status = update_index(self.root)
        self.assertEqual(status.lsn, evidence_tail(self.root))
        self.assertEqual(status.events_indexed, 42)
        self.assertFalse(status.stale)
        self.assertFalse(index_status(self.root).stale)

    def test_04_stale_is_loud(self) -> None:
        """R2.4: consumers must raise E_RC_STALE when the head lags evidence."""
        rc_fixtures.write_store(self.root, _events(20))
        build_index(self.root)
        rc_fixtures.append_store(
            self.root, [("2023-02-02T09:00:00Z", "索引之后又追加的事件")]
        )
        self.assertTrue(index_status(self.root).stale)
        with self.assertRaises(RecallError) as search_error:
            search(self.root, "日程记录")
        self.assertEqual(search_error.exception.code, E_RC_STALE)
        with self.assertRaises(RecallError) as assemble_error:
            assemble(self.root, "日程记录", 4096, "2026-10-29T10:00:00+08:00")
        self.assertEqual(assemble_error.exception.code, E_RC_STALE)

    def test_05_missing_index(self) -> None:
        """R2: searching without an index raises E_RC_NO_INDEX."""
        rc_fixtures.write_store(self.root, _events(5))
        with self.assertRaises(RecallError) as error:
            search(self.root, "日程记录")
        self.assertEqual(error.exception.code, E_RC_NO_INDEX)

    def test_06_verify_sample_is_clean(self) -> None:
        """R2.5: a fresh index reconciles 100% of sampled texts."""
        rc_fixtures.write_store(self.root, _events(200))
        build_index(self.root)
        status = index_status(self.root, verify_sample=50)
        self.assertEqual(status.verified, 50)
        self.assertFalse(status.stale)

    def test_07_verify_sample_detects_tampered_cache(self) -> None:
        """R2.6: a hand-edited cached text is caught as E_RC_STALE."""
        rc_fixtures.write_store(self.root, _events(200))
        build_index(self.root)
        database = self.root / INDEX_DIR / INDEX_FILE
        connection = sqlite3.connect(str(database))
        try:
            connection.execute(
                "UPDATE ev_data SET text = ? WHERE event_id = 'ev_000100'",
                ("被手改过的缓存",),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(RecallError) as error:
            index_status(self.root, verify_sample=200)
        self.assertEqual(error.exception.code, E_RC_STALE)
        build_index(self.root)
        index_status(self.root, verify_sample=200)


if __name__ == "__main__":
    unittest.main()
