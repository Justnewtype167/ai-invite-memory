"""T3: hash chain links, segment lifecycle and supporting units."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jian.canonical import dumps
from jian.capsule import append_event, init_store, seal_store, verify_path
from jian.chain import chain_document, segment_number, summarize
from jian.errors import E_CHAIN_MISSING, E_SCHEMA, JianError
from jian.event import (
    GENESIS_PREV,
    body_bytes,
    compute_hash,
    format_id,
    new_event,
    normalize_time,
    parse_event,
    parse_line,
)


def _chain(store: Path) -> dict:
    return json.loads((store / "chain.json").read_text(encoding="utf-8"))


def _events(path: Path) -> list:
    return [parse_line(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _stamp(offset: int) -> str:
    base = datetime(2026, 10, 29, 6, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(seconds=offset)).isoformat()


class ChainLinksTest(unittest.TestCase):
    """T3: 250 events form three segments and links stay continuous."""

    def test_chain_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "mem"
            init_store(store)
            for index in range(250):
                role = "user" if index % 2 == 0 else "assistant"
                append_event(store, role, f"mem-{index + 1:04d}", _stamp(index))
            chain = _chain(store)
            self.assertEqual([row["count"] for row in chain["segments"]], [100, 100, 50])
            self.assertEqual(len(chain["segments"]), 3)
            self.assertIsNone(chain["sealed_at"])
            previous = GENESIS_PREV
            sequence = 1
            for name in ("seg-0001", "seg-0002", "seg-0003"):
                events = _events(store / "evidence" / f"{name}.jsonl")
                self.assertEqual(events[0].prev, previous)
                for event in events:
                    self.assertEqual(event.id, format_id(sequence))
                    sequence += 1
                for left, right in zip(events, events[1:]):
                    self.assertEqual(right.prev, left.hash)
                previous = events[-1].hash
            self.assertEqual(sequence, 251)

            seal_store(store)
            sealed = _chain(store)
            self.assertIsNotNone(sealed["sealed_at"])
            hashes = {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (store / "evidence").glob("*.jsonl")
            }
            extra = append_event(store, "user", "mem-0251", _stamp(250))
            self.assertEqual(extra.ep, "seg-0004")
            for name, digest in hashes.items():
                path = store / "evidence" / name
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            after = _chain(store)
            self.assertIsNone(after["sealed_at"])
            self.assertEqual([row["count"] for row in after["segments"]], [100, 100, 50, 1])
            result = verify_path(store)
            self.assertEqual(result.events, 251)
            self.assertEqual(result.segments, 4)
            self.assertEqual(result.state, "unsealed")


class ChainUnitsTest(unittest.TestCase):
    """Unit coverage for public chain and event helpers."""

    def test_segment_number(self) -> None:
        self.assertEqual(segment_number("seg-0007"), 7)

    def test_segment_number_rejects_bad_name(self) -> None:
        with self.assertRaises(JianError) as context:
            segment_number("seg-7")
        self.assertEqual(context.exception.code, E_CHAIN_MISSING)

    def test_summarize_and_chain_document(self) -> None:
        first = new_event(1, "seg-0001", _stamp(0), "user", "a", GENESIS_PREV)
        second = new_event(2, "seg-0001", _stamp(1), "assistant", "b", first.hash)
        segments = summarize([("seg-0001", [first, second])])
        self.assertEqual(segments[0].count, 2)
        self.assertEqual(segments[0].first, first.hash)
        self.assertEqual(segments[0].last, second.hash)
        self.assertIsNone(segments[0].prev_seg)
        document = chain_document(None, segments)
        self.assertEqual(document["v"], 1)
        self.assertIsNone(document["sealed_at"])

    def test_compute_hash_matches_new_event(self) -> None:
        event = new_event(1, "seg-0001", _stamp(0), "user", "hello", GENESIS_PREV)
        self.assertEqual(compute_hash(GENESIS_PREV, event.body()), event.hash)

    def test_body_bytes_matches_canonical_dumps(self) -> None:
        samples = ["plain", "中文字符", 'quote " and backslash \\', "line\nbreak", "\u0001"]
        for text in samples:
            with self.subTest(text=text):
                event = new_event(1, "seg-0001", _stamp(0), "user", text, GENESIS_PREV)
                self.assertEqual(body_bytes(event), dumps(event.body()))

    def test_normalize_time_converts_offsets_to_utc(self) -> None:
        self.assertEqual(
            normalize_time("2026-10-29T14:00:00+08:00"), "2026-10-29T06:00:00Z"
        )

    def test_normalize_time_rejects_naive_input(self) -> None:
        with self.assertRaises(JianError) as context:
            normalize_time("2026-10-29T06:00:00")
        self.assertEqual(context.exception.code, E_SCHEMA)

    def test_parse_event_roundtrip(self) -> None:
        event = new_event(3, "seg-0001", _stamp(2), "assistant", "ok", GENESIS_PREV)
        parsed = parse_event(json.loads(event.to_line()))
        self.assertEqual(parsed, event)

    def test_parse_event_rejects_extra_field(self) -> None:
        event = new_event(1, "seg-0001", _stamp(0), "user", "x", GENESIS_PREV)
        broken = json.loads(event.to_line())
        broken["extra"] = "no"
        with self.assertRaises(JianError) as context:
            parse_event(broken)
        self.assertEqual(context.exception.code, E_SCHEMA)


if __name__ == "__main__":
    unittest.main()
