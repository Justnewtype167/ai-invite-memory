# -*- coding: utf-8 -*-
"""Report real wall-clock time for verifying a 10,000-event store.

This is a benchmark, not a gate: whatever the machine load is, it prints the
measured milliseconds and exits 0. The reference target is <200ms; the unit
test only guards against quadratic regressions with a 2s bound.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jian.capsule import init_store, seal_store, verify_path
from jian.event import GENESIS_PREV, new_event

EVENTS = 10000
SEGMENT_SIZE = 100


def build_store(store: Path) -> None:
    """Write a canonical 10,000-event store (100 segments of 100 events)."""
    init_store(store)
    previous = GENESIS_PREV
    for segment in range(1, EVENTS // SEGMENT_SIZE + 1):
        episode = f"seg-{segment:04d}"
        lines = []
        for slot in range(SEGMENT_SIZE):
            sequence = (segment - 1) * SEGMENT_SIZE + slot + 1
            stamp = f"2026-10-29T06:{sequence // 60 % 60:02d}:{sequence % 60:02d}Z"
            event = new_event(sequence, episode, stamp, "user", f"msg-{sequence:05d}", previous)
            previous = event.hash
            lines.append(event.to_line())
        (store / "evidence" / f"{episode}.jsonl").write_bytes(b"".join(lines))


def main() -> int:
    """Build, seal, and time one verification; always return 0."""
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp) / "bench"
        build_store(store)
        start = time.perf_counter()
        seal_store(store)
        seal_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        result = verify_path(store)
        verify_ms = (time.perf_counter() - start) * 1000

    print(f"events={result.events} segments={result.segments} state={result.state}")
    print(f"seal_ms={seal_ms:.1f}")
    print(f"verify_ms={verify_ms:.1f}  target<200ms (reported, not enforced)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
