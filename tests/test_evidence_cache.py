"""P2: the evidence cache must be invisible in the result and visible in the cost."""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.capsule import append_event, init_store, seal_store
from aiinvite.kernel.cache import EvidenceCache
from aiinvite.kernel.compiler import compile_kernel, read_evidence
from aiinvite.kernel.incremental import compile_kernel_incremental
from aiinvite.kernel.kernel import Policy
from aiinvite.persona import build_persona_view

STAMP = "2026-11-01T09:00:00+08:00"
NOW = "2026-11-01T12:00:00+08:00"
ROLES = ("user", "assistant", "user", "assistant", "directive")


class TestEvidenceCache(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="cache_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "m"
        init_store(self.store)
        for index in range(250):
            role = "user" if index % 2 == 0 else "assistant"
            append_event(self.store, role, "第" + str(index) + "条", STAMP)
        seal_store(self.store)
        self.policy = Policy(now=NOW)

    def test_second_read_parses_nothing(self) -> None:
        """P2: an unchanged store is served from memory."""
        cache = EvidenceCache()
        cache.read(self.store)
        first = cache.parsed_segments
        cache.read(self.store)
        self.assertEqual(cache.parsed_segments, first)

    def test_append_parses_only_the_tail(self) -> None:
        """P2: one appended event parses one segment, not the whole store."""
        cache = EvidenceCache()
        cache.read(self.store)
        before = cache.parsed_segments
        append_event(self.store, "user", "新的一条", STAMP)
        cache.read(self.store)
        self.assertEqual(cache.parsed_segments - before, 1)

    def test_cache_matches_a_fresh_read(self) -> None:
        """P2: cached events are byte-identical in content to a cold read."""
        cache = EvidenceCache()
        cached = cache.read(self.store)
        fresh = read_evidence(self.store)
        self.assertEqual(
            [(event.event_id, event.text, event.role) for event in cached],
            [(event.event_id, event.text, event.role) for event in fresh],
        )

    def test_kid_is_identical_with_and_without_events(self) -> None:
        """P2: passing events must not change identity."""
        events = read_evidence(self.store)
        self.assertEqual(
            compile_kernel(self.store, self.policy).kid,
            compile_kernel(self.store, self.policy, events=events).kid,
        )

    def test_incremental_kid_is_identical_with_events(self) -> None:
        """P2: the incremental path agrees with the plain path either way."""
        compile_kernel_incremental(self.store, self.policy)
        events = read_evidence(self.store)
        self.assertEqual(
            compile_kernel_incremental(self.store, self.policy).kid,
            compile_kernel_incremental(self.store, self.policy, events=events).kid,
        )

    def test_persona_view_matches_with_and_without_events(self) -> None:
        """P2: the card and traits are the same whether events are passed in."""
        events = read_evidence(self.store)
        one = build_persona_view(self.store, policy=self.policy)
        two = build_persona_view(self.store, events=events, policy=self.policy)
        self.assertEqual(one.kid, two.kid)
        self.assertEqual(one.user_card.to_payload(), two.user_card.to_payload())
        self.assertEqual([t.name for t in one.traits], [t.name for t in two.traits])

    def test_append_parses_one_event_not_the_segment(self) -> None:
        """P4: one appended event costs one parsed event, not one segment."""
        cache = EvidenceCache()
        cache.read(self.store)
        before = cache.parsed_events
        append_event(self.store, "user", "只追加这一条", STAMP)
        events = cache.read(self.store)
        self.assertEqual(cache.parsed_events - before, 1)
        self.assertEqual(len(events), 251)
        self.assertEqual(events[-1].text, "只追加这一条")

    def test_many_appends_stay_incremental(self) -> None:
        """P4: a stream of appends never re-parses the parsed prefix."""
        cache = EvidenceCache()
        cache.read(self.store)
        before = cache.parsed_events
        for index in range(5):
            append_event(self.store, "user", "追加" + str(index), STAMP)
            events = cache.read(self.store)
        self.assertEqual(cache.parsed_events - before, 5)
        self.assertEqual(len(events), 255)
        sequences = [int(event.event_id.split("_")[1]) for event in events]
        self.assertEqual(sequences, sorted(sequences))
        self.assertEqual(sequences, list(range(1, 256)))

    def test_partial_line_is_not_parsed_until_complete(self) -> None:
        """P4: a half-written trailing line waits instead of raising."""
        cache = EvidenceCache()
        cache.read(self.store)
        folder = self.store / "evidence"
        event = append_event(self.store, "user", "半行事件", STAMP)
        line = event.to_line()
        last = sorted(folder.glob("seg-*.jsonl"))[-1]
        start = last.stat().st_size - len(line)
        cut = len(line) // 2
        with last.open("r+b") as handle:
            handle.truncate(start + cut)
        events = cache.read(self.store)
        self.assertEqual(len(events), 250)
        with last.open("ab") as handle:
            handle.write(line[cut:])
        events = cache.read(self.store)
        self.assertEqual(len(events), 251)
        self.assertEqual(events[-1].text, "半行事件")

    def test_same_size_rewrite_is_reparsed(self) -> None:
        """P4: editing a sealed line in place invalidates that segment."""
        cache = EvidenceCache()
        cache.read(self.store)
        folder = self.store / "evidence"
        first = sorted(folder.glob("seg-*.jsonl"))[0]
        blob = first.read_bytes()
        marker = "第7条".encode("utf-8")
        self.assertEqual(blob.count(marker), 1)
        first.write_bytes(blob.replace(marker, "第9条".encode("utf-8"), 1))
        before = cache.parsed_events
        events = cache.read(self.store)
        self.assertEqual(cache.parsed_events - before, 100)
        self.assertEqual(len(events), 250)
        self.assertEqual(events[7].text, "第9条")


if __name__ == "__main__":
    unittest.main()