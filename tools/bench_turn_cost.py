"""Per-turn cost of a warm session: where a turn's time goes, at 20k or 200k.

This is the harness behind docs/TASK-25-turn-cost.md section 6. It builds a
synthetic store (100 events per segment), seeds a matching chain.json, then
times one cold turn and three warm turns with the host's own phases
instrumented: evidence read, kernel compile, pins, snapshot write/load, index
update, and the retrieval assembly.

The numbers are machine-dependent; the counters (calls:) are not. If a phase is
called more than once per turn, that is the bug -- the milliseconds only tell
you how much it costs.

Usage:
    python tools/bench_turn_cost.py 20000
    python tools/bench_turn_cost.py 200000
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys
import tempfile
import time
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import rc_fixtures

from aiinvite.canonical import dumps
from aiinvite.capsule import CHAIN_PATH, init_store

import aiinvite.host as host_mod
import aiinvite.kernel.incremental as inc_mod
import aiinvite.recall.index as index_mod
import aiinvite.recall.stream as stream_mod
from aiinvite.host import HostSession

STAMP = "2026-11-12T10:00:00Z"
SEGMENT = 100

T: dict[str, float] = defaultdict(float)
CALLS: dict[str, int] = defaultdict(int)


def wrap(owner, attr: str, label: str) -> None:
    """Time every call to attr on owner and count it."""
    original = getattr(owner, attr)

    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            T[label] += time.perf_counter() - start
            CALLS[label] += 1

    setattr(owner, attr, wrapper)


def seed_chain(target: pathlib.Path, count: int, per_segment: int = SEGMENT) -> None:
    """Write a chain.json matching a raw bulk-written evidence tree.

    rc_fixtures.write_bulk_store writes segments directly, so the chain would
    otherwise be missing and append_event refuses to run. Only the segment
    boundaries matter for indexing and caching; the per-segment hashes are not
    verified by the read paths this benchmark exercises.
    """
    segments = []
    previous = None
    position = 0
    while position < count:
        number = len(segments) + 1
        size = min(per_segment, count - position)
        segments.append(
            {
                "seg": f"seg-{number:04d}",
                "count": size,
                "first": "0" * 64,
                "last": "0" * 64,
                "prev_seg": previous,
            }
        )
        previous = f"seg-{number:04d}"
        position += size
    document = {"v": 1, "sealed_at": None, "segments": segments}
    (target / CHAIN_PATH).write_bytes(dumps(document))


def instrument() -> None:
    for attr, label in (
        ("_events", "events"),
        ("_kernel", "kernel"),
        ("_pinned", "pins"),
        ("_card_and_persona", "card_persona"),
        ("_ensure_index", "ensure_index"),
        ("prompt_for", "prompt_for"),
    ):
        wrap(HostSession, attr, label)
    wrap(stream_mod.StreamSession, "context", "stream_context")
    wrap(host_mod, "build_index", "index_build")
    wrap(host_mod, "update_index", "index_update")
    wrap(inc_mod, "write_snapshot", "snapshot_write")
    wrap(inc_mod, "load_snapshot", "snapshot_load")


def report(label: str) -> None:
    parts = [f"{key}={T[key] * 1000:.0f}ms" for key in sorted(T)]
    total = T["prompt_for"]
    print(f"{label}: prompt_for={total * 1000:.0f}ms | " + " ".join(parts))
    print("  calls: " + " ".join(f"{key}={CALLS[key]}" for key in sorted(CALLS)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("count", nargs="?", type=int, default=20000, help="number of events")
    args = parser.parse_args(argv)
    if args.count < 1:
        parser.error("count must be positive")

    instrument()
    store = pathlib.Path(tempfile.mkdtemp(prefix="bench_turn_")) / "m"
    try:
        init_store(store)
        rc_fixtures.write_bulk_store(store, args.count)
        seed_chain(store, args.count)
        session = HostSession(store, "glm4:9b")

        T.clear()
        CALLS.clear()
        session.on_user("我今天有点累", STAMP)
        session.prompt_for("我今天有点累")
        report("cold")

        for index in range(3):
            T.clear()
            CALLS.clear()
            text = f"再记一条：明天去买牛奶{index}"
            session.on_user(text, STAMP)
            session.prompt_for(text)
            session.on_assistant("好，我记下了。", STAMP)
            report(f"warm{index + 1}")
    finally:
        shutil.rmtree(store.parent, True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
