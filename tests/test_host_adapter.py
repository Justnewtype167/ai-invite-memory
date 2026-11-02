"""M17: the reference host adapter keeps three calls and a fixed order."""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from jian.capsule import append_event, init_store, seal_store, verify_path
from jian_kernel.compiler import compile_kernel
from jian_kernel.kernel import Policy
from jian_recall.tokenizer import estimate_tokens
from host_adapter import HostSession

NOW = "2026-11-01T10:00:00+08:00"
STAMP = "2026-11-01T09:00:00+08:00"


class TestHostAdapter(unittest.TestCase):
    """H1-H5: the adapter is a thin, ordered, read-mostly wrapper."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_host_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "mem"
        init_store(self.store)

    def _session(self) -> HostSession:
        session = HostSession(self.store, "qwen3.5:9b", now=NOW)
        session.on_user("我叫老周，别叫我宝贝", STAMP)
        return session

    def test_round_trip_records_two_turns(self) -> None:
        """H1: the adapter adds nothing beyond the two turns it writes.

        Turns are core evidence: they move ``events`` and ``known_days``, so the
        kid does move. The right assertion is that it moves exactly as far as a
        store written by ``append_event`` alone.
        """
        session = self._session()
        verdict = session.reply("在的。", "2026-11-01T09:01:00+08:00")
        self.assertTrue(verdict.allowed)
        self.assertEqual(verify_path(self.store).events, 2)
        self.assertEqual(session.stats()["turns"], 2)
        twin = self.root / "twin"
        init_store(twin)
        append_event(twin, "user", "我叫老周，别叫我宝贝", STAMP)
        append_event(twin, "assistant", "在的。", "2026-11-01T09:01:00+08:00")
        self.assertEqual(
            compile_kernel(self.store, Policy(now=NOW)).kid,
            compile_kernel(twin, Policy(now=NOW)).kid,
        )

    def test_prompt_order_is_fixed(self) -> None:
        """H2: rules, then the user card, then memory, then the input."""
        prompt = self._session().prompt_for("你好")
        marks = [prompt.index(m) for m in (
            "## behavior rules", "## who you both are",
            "## recent and recalled memory", "## persona", "## this turn")]
        self.assertEqual(marks, sorted(marks))
        self.assertTrue(prompt.endswith("你好"))

    def test_prompt_is_pure(self) -> None:
        """H3: asking twice writes nothing and returns identical bytes."""
        session = self._session()
        first = session.prompt_for("你好")
        events = verify_path(self.store).events
        second = session.prompt_for("你好")
        self.assertEqual(first, second)
        self.assertEqual(events, verify_path(self.store).events)

    def test_refusal_is_recorded(self) -> None:
        """H4: a forbidden reply is recorded as a refusal, not as a turn."""
        append_event(self.store, text="别叫我宝贝", t=STAMP,
                     type="directive", kind="lock")
        seal_store(self.store)
        session = HostSession(self.store, "qwen3.5:9b", now=NOW)
        verdict = session.reply("宝贝我来了", "2026-11-01T09:05:00+08:00")
        self.assertFalse(verdict.allowed)
        self.assertEqual(session.stats()["turns"], 0)
        self.assertEqual(verify_path(self.store).events, 2)

    def test_prompt_respects_budget(self) -> None:
        """H5: the assembled prompt stays inside the token budget."""
        session = self._session()
        prompt = session.prompt_for("你好")
        self.assertLessEqual(estimate_tokens(prompt), 4096)


if __name__ == "__main__":
    unittest.main()
