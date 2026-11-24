# -*- coding: utf-8 -*-
"""Identity follows the evidence, not the wall clock.

The service default is a clock-free policy: the kernel clock falls back to the
newest evidence stamp, so the same memory answered on different days reports
the same kid. Before this change the host pinned the policy clock to the
process start, which made known_days (and therefore kid) drift at every
midnight and differ between two processes on the same data.
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.capsule import append_event, init_store, seal_store
from aiinvite.kernel.compiler import compile_kernel
from aiinvite.kernel.kernel import Policy
from aiinvite.serve import MemoryService

LAST = "2026-11-24T22:00:00+08:00"


class TestKidClock(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="kid_clock_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        store = self.root / "k1"
        init_store(store)
        append_event(store, "user", "我叫老周，别叫我宝贝", "2026-11-17T09:00:00+08:00")
        append_event(store, "assistant", "好的老周", "2026-11-17T09:00:05+08:00")
        append_event(store, "user", "今天有点累", LAST)
        seal_store(store)

    def test_default_service_uses_the_evidence_clock(self) -> None:
        """No pinned clock means the newest evidence stamp, not now()."""
        default = MemoryService(self.root, "deepseek-chat")
        pinned = MemoryService(self.root, "deepseek-chat", now=LAST)
        self.assertEqual(default.view("k1")["kid"], pinned.view("k1")["kid"])

    def test_pinning_a_clock_still_moves_the_identity(self) -> None:
        """A caller that pins a clock on purpose still gets its own kid."""
        default = MemoryService(self.root, "deepseek-chat")
        future = MemoryService(self.root, "deepseek-chat", now="2027-06-01T08:00:00+08:00")
        self.assertNotEqual(default.view("k1")["kid"], future.view("k1")["kid"])

    def test_compiler_default_is_clock_free(self) -> None:
        store = self.root / "k1"
        evidence_clock = compile_kernel(store, Policy(now=LAST))
        self.assertEqual(compile_kernel(store, Policy()).kid, evidence_clock.kid)

    def test_known_days_measures_evidence_span(self) -> None:
        store = self.root / "k1"
        kernel = compile_kernel(store, Policy())
        span = [line for line in kernel.self_md.splitlines() if "known_days" in line]
        self.assertEqual(span, ["- known_days: 7"])


if __name__ == "__main__":
    unittest.main()
