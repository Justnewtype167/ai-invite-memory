"""X1-X5 and W3-W6: streaming equivalence, delta triggers, chunks (M14.1)."""

from __future__ import annotations

import json
import os
import pathlib
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import rc_fixtures

from jian.capsule import verify_path
from jian_recall import Chunk, StreamSession, StreamStats, join_chunks
from jian_recall.assemble import RECENT_LIMIT, RETRIEVE_K, assemble
from jian_recall.errors import E_RC_BAD_BUDGET, E_RC_NO_INDEX, E_RC_STREAM, RecallError
from jian_recall.index import build_index, index_status
from jian_recall.stream import CHUNK_SLOTS, RECENT_CHUNK_LIMIT
from jian_recall.trigger import PROMISE_LIMIT, SAME_DAY_LIMIT

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOW = "2026-10-29T10:00:00+08:00"
NEXT_DAY = "2026-10-30T10:00:00+08:00"
NEXT_YEAR = "2027-10-29T10:00:00+08:00"
QUERY = "项目进度"
BUDGET = 512
CANDIDATE_CAP = RETRIEVE_K + RECENT_LIMIT + SAME_DAY_LIMIT + PROMISE_LIMIT
BASE_TOTAL = 60 + 3 + 8 + 2


def _base_events(count: int = 60) -> list[tuple[str, str]]:
    """Return a store with query hits, three anniversaries, promises and recent turns."""
    rows: list[tuple[str, str]] = []
    for index in range(count):
        rows.append(
            (f"2024-01-01T00:{index % 60:02d}:00Z", f"项目进度又更新了一次{index}")
        )
    rows.append(("2021-10-29T10:00:00Z", "纪念日回忆"))
    rows.append(("2022-10-29T10:00:00Z", "纪念日回忆二"))
    rows.append(("2023-10-29T10:00:00Z", "纪念日回忆三"))
    for index in range(8):
        rows.append((f"2025-06-01T08:0{index}:00Z", f"最近的日常记录{index + 1}"))
    rows.append(("2025-06-01T08:10:00Z", "答应周末一起去看海"))
    rows.append(("2025-06-01T08:11:00Z", "说好下个月一起吃饭"))
    return rows


class TestStreamSession(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_rc_stream_"))
        rc_fixtures.write_store(cls.root, _base_events())
        build_index(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root, True)

    def _new_store(self, events: list[tuple[str, str]]) -> pathlib.Path:
        root = pathlib.Path(tempfile.mkdtemp(prefix="jian_rc_stream_t_"))
        self.addCleanup(shutil.rmtree, root, True)
        rc_fixtures.write_store(root, events)
        build_index(root)
        return root

    def test_still_equivalent(self) -> None:
        """X1: 30 appends, every context is byte-identical to assemble."""
        store = self._new_store(_base_events(75))
        session = StreamSession(store, BUDGET, NOW)
        session.context(QUERY)
        rng = random.Random(20261101)
        rows: list[tuple[int, int, int, int]] = []
        for step in range(30):
            text = rc_fixtures.POOL[rng.randrange(len(rc_fixtures.POOL))]
            rc_fixtures.append_store(
                store, [(f"2026-10-28T{step // 60:02d}:{step % 60:02d}:00Z", text)]
            )
            live = session.context(QUERY)
            batch = assemble(store, QUERY, BUDGET, NOW)
            self.assertEqual(live.to_json(), batch.to_json())
            stats = session.stats()
            self.assertEqual(stats.trigger_scanned, 1)
            self.assertEqual(stats.trigger_loaded, 0)
            self.assertEqual(stats.trigger_reused, 2)
            self.assertEqual(stats.retrieve_scored, batch.candidates)
            rows.append((stats.trigger_scanned, stats.trigger_loaded,
                          stats.trigger_reused, stats.retrieve_scored))
        print(f"X1 steps={len(rows)} identical={len(rows)} last={rows[-1]}")

    def test_trigger_is_delta_sized(self) -> None:
        """X2: scanned follows appended events and never the store size."""
        results = []
        for count in (60, 400):
            store = self._new_store(_base_events(count))
            session = StreamSession(store, BUDGET, NOW)
            session.context(QUERY)
            rc_fixtures.append_store(
                store, [("2026-10-28T10:00:00Z", "今天天气不错")]
            )
            session.context(QUERY)
            one = session.stats().trigger_scanned
            rc_fixtures.append_store(
                store,
                [(f"2026-10-28T1{index}:00:00Z", f"普通追加{index}") for index in range(10)],
            )
            session.context(QUERY)
            ten = session.stats().trigger_scanned
            results.append((count, one, ten))
        print(f"X2 store_size/one/ten={results}")
        self.assertEqual(results[0][1], 1)
        self.assertEqual(results[0][2], 10)
        self.assertEqual(results[1][1], 1)
        self.assertEqual(results[1][2], 10)
        self.assertEqual((results[0][1], results[0][2]),
                         (results[1][1], results[1][2]))

    def test_trigger_reused_per_subquery(self) -> None:
        """X3: reused counts cached sub-queries, and each invalidation costs one."""
        store = self._new_store(_base_events())
        session = StreamSession(store, BUDGET, NOW)
        session.context(QUERY)
        cold = session.stats()
        self.assertEqual(cold.trigger_scanned, 0)
        self.assertEqual(cold.trigger_reused, 0)
        self.assertLessEqual(cold.trigger_loaded, SAME_DAY_LIMIT + PROMISE_LIMIT)

        session.context(QUERY)
        warm = session.stats()
        self.assertEqual((warm.trigger_scanned, warm.trigger_loaded,
                          warm.trigger_reused), (0, 0, 2))

        rc_fixtures.append_store(
            store, [("2026-10-28T10:00:00Z", "今天天气不错")]
        )
        session.context(QUERY)
        unrelated = session.stats()
        self.assertEqual((unrelated.trigger_scanned, unrelated.trigger_loaded,
                          unrelated.trigger_reused), (1, 0, 2))

        rc_fixtures.append_store(
            store, [("2020-10-29T10:00:00Z", "很久以前的纪念日")]
        )
        session.context(QUERY)
        same_day = session.stats()
        self.assertEqual((same_day.trigger_scanned, same_day.trigger_reused),
                         (1, 1))
        self.assertLessEqual(same_day.trigger_loaded, SAME_DAY_LIMIT)

        rc_fixtures.append_store(
            store, [("2026-10-28T12:00:00Z", "答应明天早点回来")]
        )
        session.context(QUERY)
        promise = session.stats()
        self.assertEqual((promise.trigger_scanned, promise.trigger_reused),
                         (1, 1))
        self.assertLessEqual(promise.trigger_loaded, PROMISE_LIMIT)
        print(
            "X3 cold={} warm={} unrelated={} same_day={} promise={}".format(
                cold.to_dict(), warm.to_dict(), unrelated.to_dict(),
                same_day.to_dict(), promise.to_dict(),
            )
        )

    def test_reused_is_not_days(self) -> None:
        """X3b: over 30 days without an md hit, reused stays 2 (not days)."""
        store = self._new_store(_base_events())
        session = StreamSession(store, BUDGET, NOW)
        session.context(QUERY)
        seen: list[int] = []
        for day in range(1, 31):
            rc_fixtures.append_store(
                store,
                [(f"2025-11-{day:02d}T10:00:00Z", f"十一月的第{day}天")],
            )
            session.context(QUERY)
            stats = session.stats()
            self.assertIn(stats.trigger_reused, (0, 1, 2))
            seen.append(stats.trigger_reused)
        self.assertEqual(seen, [2] * 30)
        print(f"X3b days=30 reused_set={sorted(set(seen))}")

    def test_cache_invalidation(self) -> None:
        """X4: now change, rollback and rebuild invalidate; bytes stay equal."""
        store = self._new_store(_base_events())
        session = StreamSession(store, BUDGET, NOW)
        session.context(QUERY)

        session.now = NEXT_DAY
        live = session.context(QUERY)
        self.assertEqual(live.to_json(), assemble(store, QUERY, BUDGET, NEXT_DAY).to_json())
        self.assertEqual(session.stats().trigger_reused, 1)

        session.now = NEXT_YEAR
        live = session.context(QUERY)
        self.assertEqual(live.to_json(), assemble(store, QUERY, BUDGET, NEXT_YEAR).to_json())
        self.assertEqual(session.stats().trigger_reused, 1)

        session.now = NOW
        session.context(QUERY)
        _truncate_last(store)
        build_index(store)
        live = session.context(QUERY)
        self.assertEqual(live.to_json(), assemble(store, QUERY, BUDGET, NOW).to_json())
        self.assertEqual(session.stats().trigger_reused, 0)
        self.assertGreater(session.stats().trigger_loaded, 0)

        build_index(store)
        live = session.context(QUERY)
        self.assertEqual(live.to_json(), assemble(store, QUERY, BUDGET, NOW).to_json())
        self.assertEqual(session.stats().trigger_reused, 0)
        self.assertGreater(session.stats().trigger_loaded, 0)
        print(
            "X4 now_day/reused={} now_year/reused={} rollback/reused={} rebuild/reused={}"
            .format(1, 1, 0, 0)
        )

    def test_retrieve_not_claimed_incremental(self) -> None:
        """X5: retrieve_scored equals candidates; this round does not reduce it."""
        store = self._new_store(_base_events())
        session = StreamSession(store, BUDGET, NOW)
        values: list[int] = []
        for step in range(4):
            if step:
                rc_fixtures.append_store(
                    store,
                    [(f"2026-10-28T0{step}:00:00Z", f"明写不减少的检索{step}")],
                )
            context = session.context(QUERY)
            stats = session.stats()
            self.assertEqual(stats.retrieve_scored, context.candidates)
            self.assertGreater(stats.retrieve_scored, 0)
            self.assertLessEqual(stats.retrieve_scored, CANDIDATE_CAP + step)
            values.append(stats.retrieve_scored)
        print(f"X5 retrieve_scored/candidates={values}")

    def test_determinism(self) -> None:
        """W3: same store, same bytes, in and across processes."""
        first = StreamSession(self.root, BUDGET, NOW).context(QUERY).to_json()
        second = StreamSession(self.root, BUDGET, NOW).context(QUERY).to_json()
        self.assertEqual(first, second)
        outputs = [self._child_payload(seed) for seed in ("0", "12345")]
        self.assertEqual(outputs[0], outputs[1])
        child = json.loads(outputs[0])
        self.assertEqual(child["context"], first)
        self.assertEqual(child["chunks"], [chunk.to_json() for chunk in self._chunks()])
        print(f"W3 bytes={len(first)} seeds=0,12345 identical=True")

    def test_chunks_concatenate(self) -> None:
        """W4: at least two stable chunks that join back to the context."""
        context = StreamSession(self.root, BUDGET, NOW).context(QUERY)
        chunks = self._chunks()
        self.assertGreaterEqual(len(chunks), 2)
        positions = [chunk.index for chunk in chunks]
        self.assertEqual(positions, list(range(len(chunks))))
        slots = [chunk.slot for chunk in chunks]
        self.assertEqual(slots, [slot for slot in CHUNK_SLOTS if slot in slots])
        self.assertEqual(join_chunks(chunks), context.items)
        again = self._chunks()
        self.assertEqual([chunk.to_json() for chunk in chunks],
                         [chunk.to_json() for chunk in again])
        spans = [chunk.start for chunk in chunks]
        self.assertEqual(len(spans), len(set(spans)))
        recent = [chunk for chunk in chunks if chunk.slot == "recent"]
        self.assertEqual(len(recent[0].items), RECENT_CHUNK_LIMIT)
        print(f"W4 chunks={len(chunks)} slots={slots} items={len(context.items)}")

    def test_chunk_gap_is_rejected(self) -> None:
        """W4: a chunk gap raises E_RC_STREAM instead of silently joining."""
        context = StreamSession(self.root, BUDGET, NOW).context(QUERY)
        self.assertGreaterEqual(len(context.items), 4)
        broken = [
            Chunk(0, "recent", 0, context.items[:2]),
            Chunk(1, "recall", 3, context.items[3:]),
        ]
        with self.assertRaises(RecallError) as error:
            join_chunks(broken)
        self.assertEqual(error.exception.code, E_RC_STREAM)

    def test_unsealed_stream(self) -> None:
        """W5: turn-by-turn appends stay usable and the hash chain still verifies."""
        store = self._new_store(_base_events(30))
        session = StreamSession(store, BUDGET, NOW)
        previous = None
        for step in range(5):
            rc_fixtures.append_store(
                store, [(f"2026-10-28T0{step}:30:00Z", f"边聊边装第{step + 1}条")]
            )
            live = session.context(QUERY)
            batch = assemble(store, QUERY, BUDGET, NOW)
            self.assertEqual(live.to_json(), batch.to_json())
            self.assertFalse(index_status(store).stale)
            result = verify_path(store)
            self.assertEqual(result.state, "unsealed")
            if previous is not None:
                self.assertEqual(result.events, previous + 1)
            previous = result.events
        print(f"W5 events={previous} state=unsealed")

    def test_budget_never_exceeded(self) -> None:
        """W6: tokens stay within budget and boundary behaviour is explicit."""
        for budget in (256, 512, 1024, 4096):
            live = StreamSession(self.root, budget, NOW)
            context = live.context(QUERY)
            self.assertLessEqual(context.total_tokens, budget)
            stats = live.stats()
            self.assertEqual(stats.retrieve_scored, context.candidates)
        with self.assertRaises(RecallError) as error:
            StreamSession(self.root, 100)
        self.assertEqual(error.exception.code, E_RC_BAD_BUDGET)
        missing = pathlib.Path(tempfile.mkdtemp(prefix="jian_rc_stream_noidx_"))
        self.addCleanup(shutil.rmtree, missing, True)
        (missing / "evidence").mkdir()
        with self.assertRaises(RecallError) as error:
            StreamSession(missing, BUDGET, NOW).context(QUERY)
        self.assertEqual(error.exception.code, E_RC_NO_INDEX)
        scarce = self._new_store([("2024-01-01T10:00:00Z", "只有一条记忆")])
        context = StreamSession(scarce, 4096, NOW).context(QUERY)
        self.assertLess(context.total_tokens, 4096)
        self.assertEqual(len(context.items), 1)
        print(f"W6 budgets=256,512,1024,4096 scarce_items=1")

    def test_stats_shape(self) -> None:
        """X5: stats is four entry counts, not timings."""
        session = StreamSession(self.root, BUDGET, NOW)
        session.context(QUERY)
        stats = session.stats()
        self.assertIsInstance(stats, StreamStats)
        self.assertEqual(
            set(stats.to_dict()),
            {"trigger_scanned", "trigger_loaded", "trigger_reused",
             "retrieve_scored"},
        )
        for value in stats.to_dict().values():
            self.assertIsInstance(value, int)
            self.assertFalse(isinstance(value, bool))

    def _chunks(self) -> list[Chunk]:
        session = StreamSession(self.root, BUDGET, NOW)
        return list(session.iter_context(QUERY))

    def _child_payload(self, seed: str) -> str:
        """Run the session in a fresh interpreter and return its JSON payload."""
        code = (
            "import json, sys\n"
            "from pathlib import Path\n"
            "from jian_recall import StreamSession, join_chunks\n"
            "session = StreamSession(Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3])\n"
            "context = session.context(sys.argv[4])\n"
            "chunks = list(session.iter_context(sys.argv[4]))\n"
            "payload = {'context': context.to_json(),\n"
            "           'chunks': [chunk.to_json() for chunk in chunks],\n"
            "           'joined': [item.event_id for item in join_chunks(chunks)]}\n"
            "sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))\n"
        )
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = str(ROOT)
        completed = subprocess.run(
            [sys.executable, "-c", code, str(self.root), str(BUDGET), NOW, QUERY],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout.strip()


def _truncate_last(store: pathlib.Path) -> None:
    """Drop the last evidence line, simulating a head rollback."""
    files = sorted((store / "evidence").glob("seg-*.jsonl"))
    last = files[-1]
    lines = [line for line in last.read_text(encoding="utf-8").split("\n") if line]
    self_check = len(lines) - 1
    last.write_text("\n".join(lines[:self_check]) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
