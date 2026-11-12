"""P4: update_index reads only newly appended bytes and matches a rebuild."""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import rc_fixtures

from aiinvite.event import new_event
from aiinvite.recall.errors import E_RC_STALE, RecallError
from aiinvite.recall.index import (
    INDEX_DIR,
    build_index,
    connect_index,
    evidence_files,
    index_status,
    load_meta,
    update_index,
)


def _events(count: int, start_day: int = 1) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for index in range(count):
        day = start_day + index // 60
        minute = index % 60
        stamp = f"2023-01-{day:02d}T10:{minute:02d}:00Z"
        result.append((stamp, f"第{index + 1}条日程记录"))
    return result


def _dump(store: pathlib.Path) -> tuple[list, list, list, dict]:
    connection = connect_index(store)
    try:
        fts = connection.execute(
            "SELECT event_id, seg, ts, bg FROM fts_ev ORDER BY rowid"
        ).fetchall()
        data = connection.execute(
            "SELECT event_id, text, tokens, is_promise FROM ev_data ORDER BY event_id"
        ).fetchall()
        times = connection.execute(
            "SELECT event_id, seg, ts, md, year FROM ev_time ORDER BY event_id"
        ).fetchall()
        meta = {
            row["key"]: row["value"]
            for row in connection.execute("SELECT key, value FROM meta")
        }
    finally:
        connection.close()
    return (
        [tuple(row) for row in fts],
        [tuple(row) for row in data],
        [tuple(row) for row in times],
        meta,
    )


def _assert_same_index(test: unittest.TestCase, left: pathlib.Path, right: pathlib.Path) -> None:
    fts_a, data_a, time_a, meta_a = _dump(left)
    fts_b, data_b, time_b, meta_b = _dump(right)
    test.assertEqual(fts_a, fts_b)
    test.assertEqual(data_a, data_b)
    test.assertEqual(time_a, time_b)
    for key in ("head", "count", "version", "last_seg", "last_size"):
        test.assertEqual(meta_a.get(key), meta_b.get(key), key)


class TestIncrementalIndex(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_inc_idx_"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _fresh_copy(self) -> pathlib.Path:
        copy = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_inc_copy_"))
        self.addCleanup(shutil.rmtree, copy, True)
        target = copy / "store"
        shutil.copytree(
            self.root, target, ignore=shutil.ignore_patterns(INDEX_DIR)
        )
        build_index(target)
        return target

    def test_01_same_segment_append_matches_rebuild(self) -> None:
        """P4.1: 12 events appended to the open segment equal a fresh build."""
        rc_fixtures.write_store(self.root, _events(250))
        build_index(self.root)
        rc_fixtures.append_store(
            self.root,
            [("2023-02-01T09:00:00Z", f"新写下的第{index}条") for index in range(12)],
        )
        status = update_index(self.root)
        self.assertFalse(status.stale)
        self.assertEqual(status.events_indexed, 262)
        self.assertFalse(index_status(self.root).stale)
        _assert_same_index(self, self.root, self._fresh_copy())

    def test_02_rollover_segment_matches_rebuild(self) -> None:
        """P4.2: appends that roll into a new segment equal a fresh build."""
        rc_fixtures.write_store(self.root, _events(250))
        build_index(self.root)
        rc_fixtures.append_store(
            self.root,
            [("2023-02-02T09:00:00Z", f"滚动后的第{index}条") for index in range(80)],
        )
        self.assertEqual(len(evidence_files(self.root)), 4)
        status = update_index(self.root)
        self.assertFalse(status.stale)
        self.assertEqual(status.events_indexed, 330)
        self.assertEqual(load_meta(self.root)["last_seg"], "seg-0004")
        _assert_same_index(self, self.root, self._fresh_copy())

    def test_03_no_change_is_a_no_op(self) -> None:
        """P4.3: updating a current index reports it fresh and keeps build_id."""
        rc_fixtures.write_store(self.root, _events(120))
        build_index(self.root)
        before = load_meta(self.root)
        status = update_index(self.root)
        self.assertFalse(status.stale)
        self.assertEqual(status.events_indexed, 120)
        self.assertEqual(status.lsn, before["head"])
        self.assertEqual(load_meta(self.root)["build_id"], before["build_id"])

    def test_04_incremental_update_keeps_build_id(self) -> None:
        """P4.4: an incremental pass is not a rebuild, so build_id survives."""
        rc_fixtures.write_store(self.root, _events(120))
        build_index(self.root)
        before = load_meta(self.root)["build_id"]
        rc_fixtures.append_store(
            self.root, [("2023-03-01T09:00:00Z", "只追加一条")]
        )
        update_index(self.root)
        self.assertEqual(load_meta(self.root)["build_id"], before)

    def test_05_truncated_segment_is_stale(self) -> None:
        """P4.5: cutting bytes off the indexed segment raises E_RC_STALE."""
        rc_fixtures.write_store(self.root, _events(250))
        build_index(self.root)
        last = evidence_files(self.root)[-1]
        size = last.stat().st_size
        with last.open("r+b") as handle:
            handle.truncate(size - 40)
        with self.assertRaises(RecallError) as caught:
            update_index(self.root)
        self.assertEqual(caught.exception.code, E_RC_STALE)

    def test_06_rewritten_boundary_is_stale(self) -> None:
        """P4.6: a rewritten head line is caught by the next append."""
        rc_fixtures.write_store(self.root, _events(250))
        build_index(self.root)
        head = load_meta(self.root)["head"]
        last = evidence_files(self.root)[-1]
        blob = last.read_bytes()
        marker = ('"id":"%s"' % head).encode("utf-8")
        self.assertEqual(blob.count(marker), 1)
        replacement = ('"id":"%s"' % "ev_999250").encode("utf-8")
        self.assertEqual(len(marker), len(replacement))
        last.write_bytes(blob.replace(marker, replacement, 1))
        # Same byte size, so the fast size check alone cannot see the edit;
        # an append re-opens the boundary and must refuse to resume from it.
        rc_fixtures.append_store(
            self.root, [("2023-02-04T09:00:00Z", "改写后追加的一条")]
        )
        with self.assertRaises(RecallError) as caught:
            update_index(self.root)
        self.assertEqual(caught.exception.code, E_RC_STALE)

    def test_07_partial_line_waits_for_its_newline(self) -> None:
        """P4.7: a half-written line is not indexed until it is complete."""
        rc_fixtures.write_store(self.root, _events(250))
        build_index(self.root)
        last = evidence_files(self.root)[-1]
        lines = [line for line in last.read_text(encoding="utf-8").split("\n") if line]
        previous = json.loads(lines[-1])["hash"]
        event = new_event(
            251, "seg-0003", "2023-02-03T09:00:00Z", "user", "半行事件", previous
        )
        blob = event.to_line()
        cut = len(blob) // 2
        with last.open("ab") as handle:
            handle.write(blob[:cut])
        status = update_index(self.root)
        self.assertTrue(status.stale)
        self.assertEqual(status.events_indexed, 250)
        with last.open("ab") as handle:
            handle.write(blob[cut:])
        status = update_index(self.root)
        self.assertFalse(status.stale)
        self.assertEqual(status.events_indexed, 251)
        self.assertEqual(status.lsn, "ev_000251")
        _assert_same_index(self, self.root, self._fresh_copy())


if __name__ == "__main__":
    unittest.main()