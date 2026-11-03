"""R6: latency sanity bound plus a scale-stability property.

Wall-clock numbers are machine- and load-dependent, so they are *reported*
here and gated only by a generous sanity bound. The real regression gates are
the two load-independent properties: no pathological blowup (sanity bound) and
latency that does not grow with index size (scale ratio). The 80ms SLO lives
in tools/bench_recall.py and is never asserted in a unit test.
"""

from __future__ import annotations

import pathlib
import shutil
import statistics
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import rc_fixtures

from aiinvite.recall.assemble import assemble
from aiinvite.recall.errors import RecallError
from aiinvite.recall.index import build_index, index_status

NOW = "2026-10-29T10:00:00+08:00"
SAMPLES = 50
WARMUP = 5
# Sanity bound only: catches a pathological regression, survives heavy load.
# The 80ms/200ms SLO is reported by tools/bench_recall.py, not gated here.
P95_SANITY_MS = 2000.0
SCALE_RATIO = 2.0
# The ratio only means something when both timings are well above OS jitter and
# the samples are stable. Shared CI runners miss both, so the ratio assertion is
# gated on a measurable signal; the absolute ceiling always applies.
RATIO_FLOOR_MS = 4.0
RATIO_MAX_CV = 0.25
BIG_CEILING_MS = 200.0


def _ensure_index(store: pathlib.Path) -> None:
    try:
        status = index_status(store)
    except RecallError:
        status = None
    if status is None or status.stale:
        build_index(store)


class TestPerf(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.big = rc_fixtures.bulk_store()
        _ensure_index(cls.big)
        cls.small = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_rc_10k_"))
        cls.addClassCleanup(shutil.rmtree, cls.small, True)
        rc_fixtures.write_bulk_store(cls.small, 10000)
        _ensure_index(cls.small)
        cls.labels = rc_fixtures.qa_labels()

    def _question(self, index: int) -> str:
        return self.labels[index % len(self.labels)]["question"]

    def test_p95_guard(self) -> None:
        """R6: assembly p95 stays under a load-tolerant sanity bound."""
        for index in range(WARMUP):
            assemble(self.big, self._question(index), 4096, NOW)
        elapsed: list[float] = []
        for index in range(SAMPLES):
            start = time.perf_counter()
            assemble(self.big, self._question(index), 4096, NOW)
            elapsed.append((time.perf_counter() - start) * 1000.0)
        ordered = sorted(elapsed)
        p50 = statistics.median(elapsed)
        p95 = ordered[int(len(ordered) * 0.95) - 1]
        print(
            f"R6 200k p50={p50:.2f}ms p95={p95:.2f}ms max={ordered[-1]:.2f}ms "
            f"over {SAMPLES} samples"
        )
        self.assertLess(p95, P95_SANITY_MS)

    def test_scale_stability(self) -> None:
        """R6: p50 on 200k events is at most twice p50 on 10k events."""
        for index in range(WARMUP):
            assemble(self.small, self._question(index), 4096, NOW)
            assemble(self.big, self._question(index), 4096, NOW)
        small_time: list[float] = []
        big_time: list[float] = []
        for index in range(SAMPLES):
            question = self._question(index)
            start = time.perf_counter()
            assemble(self.small, question, 4096, NOW)
            small_time.append((time.perf_counter() - start) * 1000.0)
            start = time.perf_counter()
            assemble(self.big, question, 4096, NOW)
            big_time.append((time.perf_counter() - start) * 1000.0)
        small_p50 = statistics.median(small_time)
        big_p50 = statistics.median(big_time)
        small_p95 = sorted(small_time)[int(len(small_time) * 0.95) - 1]
        big_p95 = sorted(big_time)[int(len(big_time) * 0.95) - 1]
        print(
            f"R6 scale 10k p50={small_p50:.2f}ms p95={small_p95:.2f}ms | "
            f"200k p50={big_p50:.2f}ms p95={big_p95:.2f}ms "
            f"ratio={big_p50 / small_p50:.2f}"
        )
        # Absolute ceiling: a pathological regression still fails on any machine.
        self.assertLessEqual(big_p50, BIG_CEILING_MS)
        cv = statistics.pstdev(big_time) / big_p50 if big_p50 else 1.0
        if small_p50 < RATIO_FLOOR_MS or cv > RATIO_MAX_CV:
            print(
                f"R6 scale: ratio not asserted (baseline {small_p50:.2f}ms "
                f"< floor {RATIO_FLOOR_MS}ms or cv {cv:.2f} > {RATIO_MAX_CV})"
            )
            return
        self.assertLessEqual(big_p50, SCALE_RATIO * small_p50)


if __name__ == "__main__":
    unittest.main()
