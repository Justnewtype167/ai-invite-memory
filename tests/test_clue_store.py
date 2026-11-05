"""E1-E6: the clue cache is derived, bounded and never touches identity."""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.capsule import append_event, init_store, seal_store
from aiinvite.kernel.compiler import compile_kernel, read_evidence
from aiinvite.kernel.kernel import Policy
from aiinvite.recall.clue_store import ClueStore

STAMP = "2026-09-01T09:00:00+08:00"
NOW = "2026-11-01T12:00:00+08:00"
MEMORY = "我的狗叫阿黄，它去年走了"


class FakeModel:
    def __init__(self, reply="阿黄 狗 去年 悲伤 医院"):
        self.reply = reply
        self.calls = 0

    def __call__(self, prompt):
        self.calls += 1
        return self.reply


class TestClueStore(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="clue_store_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "m"
        init_store(self.store)
        self.fact = append_event(self.store, "user", MEMORY, STAMP)
        self.noise = append_event(self.store, "user", "今天天气还行", STAMP)
        seal_store(self.store)

    def test_e1_generates_once_then_hits_cache(self) -> None:
        """E1: the second call must not pay for the model again."""
        model = FakeModel()
        clues = ClueStore(self.store, caller=model)
        events = read_evidence(self.store)
        self.assertEqual(clues.learn(events, limit=1), 1)
        self.assertEqual(clues.learn(events, limit=5), 1)
        self.assertEqual(model.calls, 2)  # one per event, never repeated

    def test_e2_stale_text_regenerates(self) -> None:
        """E2: a changed memory cannot inherit an old clue."""
        model = FakeModel()
        clues = ClueStore(self.store, caller=model)
        clues.ensure(self.fact.id, MEMORY)
        self.assertTrue(clues.ensure(self.fact.id, MEMORY + "，真的"))
        self.assertFalse(clues.ensure(self.fact.id, MEMORY + "，真的"))

    def test_e3_cache_is_derived(self) -> None:
        """E3: deleting the cache loses nothing but the cached work."""
        model = FakeModel()
        clues = ClueStore(self.store, caller=model)
        clues.ensure(self.fact.id, MEMORY)
        self.assertTrue(clues.pairs())
        clues.clear()
        self.assertEqual(clues.pairs(), [])
        reloaded = ClueStore(self.store, caller=model)
        self.assertEqual(reloaded.pairs(), [])

    def test_e4_identity_is_untouched(self) -> None:
        """E4: clues are not kernel input, so the kid cannot move."""
        before = compile_kernel(self.store, Policy(now=NOW)).kid
        clues = ClueStore(self.store, caller=FakeModel())
        clues.ensure(self.fact.id, MEMORY)
        after = compile_kernel(self.store, Policy(now=NOW)).kid
        self.assertEqual(before, after)

    def test_e5_invented_entities_never_reach_the_cache(self) -> None:
        """E5: a model that invents a scene stores nothing."""
        clues = ClueStore(self.store, caller=FakeModel("雨夜 医院 病历本 父亲 药瓶"))
        clues.ensure(self.fact.id, MEMORY)
        self.assertEqual(clues.pairs(), [])

    def test_e6_no_caller_means_no_work(self) -> None:
        """E6: without a model the cache stays empty instead of raising."""
        clues = ClueStore(self.store, caller=None)
        self.assertFalse(clues.ensure(self.fact.id, MEMORY))
        self.assertEqual(clues.pairs(), [])


if __name__ == "__main__":
    unittest.main()
