"""W1-W6: streaming assembly equivalence, delta work, chunks and boundaries (M14)."""

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
QUERY = "项目进度"
BUDGET = 512
CANDIDATE_CAP = RETRIEVE_K + RECENT_LIMIT + SAME_DAY_LIMIT + PROMISE_LIMIT


def _base_events(count: int = 60) -> list[tuple[str, str]]:
    """Return a store with query hits, three anniversaries and eight recent turns."""
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

    def test_session_equals_batch(self) -> None:
        """W1: 30 appends, every context is byte-identical to assemble."""
        store = self._new_store(_base_events(75))
        session = StreamSession(store, BUDGET, NOW)
        session.context(QUERY)
        rng = random.Random(20261101)
        scored: list[int] = []
        for step in range(30):
            text = rc_fixtures.POOL[rng.randrange(len(rc_fixtures.POOL))]
            rc_fixtures.append_store(
                store, [(f"2026-10-28T{step // 60:02d}:{step % 60:02d}:00Z", text)]
            )
            live = session.context(QUERY)
            batch = assemble(store, QUERY, BUDGET, NOW)
            self.assertEqual(live.to_json(), batch.to_json())
            self.assertEqual(session.stats().scored, 1)
            self.assertEqual(
                session.stats().scored + session.stats().reused, batch.candidates
            )
            scored.append(session.stats().scored)
        print(f"W1 steps={len(scored)} identical={len(scored)} scored={scored}")

    def test_delta_work(self) -> None:
        """W2: scored equals the affected entries, never the whole store."""
        store = self._new_store(_base_events(400))
        total = 400 + 3 + 8
        session = StreamSession(store, BUDGET, NOW)
        first = session.context(QUERY)
        stats = session.stats()
        self.assertEqual(stats.reused, 0)
        self.assertEqual(stats.scored, first.candidates)
        self.assertLessEqual(stats.scored, CANDIDATE_CAP)
        self.assertLess(stats.scored, total)
        rows: list[tuple[int, int, int, int]] = []
        for step, count in enumerate((1, 3, 5)):
            batch = [
                (f"2026-10-28T0{step}:{index:02d}:00Z", f"流式追加第{step}批{index}")
                for index in range(count)
            ]
            rc_fixtures.append_store(store, batch)
            context = session.context(QUERY)
            stats = session.stats()
            self.assertEqual(stats.scored, count)
            self.assertEqual(stats.scored + stats.reused, context.candidates)
            self.assertLessEqual(stats.scored, CANDIDATE_CAP)
            self.assertLess(stats.scored, total)
            rows.append((count, stats.scored, stats.reused, stats.evicted))
        print(f"W2 total={total} cap={CANDIDATE_CAP} rows={rows}")

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
            self.assertEqual(stats.scored + stats.reused, context.candidates)
            self.assertGreaterEqual(stats.evicted, 0)
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
        """W2: stats is three entry counts, not timings."""
        session = StreamSession(self.root, BUDGET, NOW)
        session.context(QUERY)
        stats = session.stats()
        self.assertIsInstance(stats, StreamStats)
        self.assertEqual(set(stats.to_dict()), {"scored", "reused", "evicted"})
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


if __name__ == "__main__":
    unittest.main()
