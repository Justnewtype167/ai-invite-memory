"""Report recall assembly latency percentiles.

This is a benchmark, not a gate: the 80ms milestone target is printed for
information only, and the script exits 0 whatever the measured numbers are.
The stable properties live in the unit tests (p95 guard and a scale-ratio
check), because a single absolute bound is dominated by fixed per-call
overhead and machine noise.

Usage:
    python tools/bench_recall.py [STORE] [--scale N] [--samples N]
                                 [--budget N] [--now ISO]

Without STORE a temporary evidence store is generated with --scale events
(default 200000) and indexed, then removed.
"""

from __future__ import annotations

import argparse
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import rc_fixtures

from aiinvite.recall.assemble import assemble
from aiinvite.recall.errors import RecallError
from aiinvite.recall.index import build_index, index_status

NOW = "2026-10-29T10:00:00+08:00"
TARGET_MS = 80.0
WARMUP = 5


def percentile(samples: list[float], ratio: float) -> float:
    """Return the nearest-rank percentile of ``samples``."""
    ordered = sorted(samples)
    rank = max(1, min(len(ordered), int(len(ordered) * ratio) + 1))
    return ordered[rank - 1]


def ensure_index(store: Path) -> int:
    """Build the index when missing or stale, returning the event count."""
    try:
        status = index_status(store)
    except RecallError:
        status = build_index(store)
    if status.stale:
        status = build_index(store)
    return status.events_indexed


def measure(store: Path, samples: int, budget: int, now: str) -> list[float]:
    """Time ``samples`` assembly calls and return milliseconds."""
    labels = rc_fixtures.qa_labels()
    for index in range(WARMUP):
        assemble(store, labels[index % len(labels)]["question"], budget, now)
    timings: list[float] = []
    for index in range(samples):
        question = labels[index % len(labels)]["question"]
        start = time.perf_counter()
        assemble(store, question, budget, now)
        timings.append((time.perf_counter() - start) * 1000.0)
    return timings


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark and print p50/p95/max; always return 0."""
    parser = argparse.ArgumentParser(prog="bench_recall")
    parser.add_argument("store", nargs="?", default=None)
    parser.add_argument("--scale", type=int, default=200000)
    parser.add_argument("--samples", type=int, default=50)
    parser.add_argument("--budget", type=int, default=4096)
    parser.add_argument("--now", default=NOW)
    args = parser.parse_args(argv)

    temporary = args.store is None
    if temporary:
        store = Path(tempfile.mkdtemp(prefix="aiinvite_bench_"))
        rc_fixtures.write_bulk_store(store, args.scale)
    else:
        store = Path(args.store)
    label = str(store)
    try:
        events = ensure_index(store)
        timings = measure(store, args.samples, args.budget, args.now)
    except RecallError as error:
        print(f"{error.code}: {error.message}")
        return 1
    finally:
        if temporary:
            shutil.rmtree(store, True)

    print(f"store={label} events={events} samples={args.samples} budget={args.budget}")
    print(
        f"p50={statistics.median(timings):.2f}ms "
        f"p95={percentile(timings, 0.95):.2f}ms max={max(timings):.2f}ms"
    )
    print(f"target<{TARGET_MS:.0f}ms (reported, not enforced)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
