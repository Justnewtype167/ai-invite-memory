"""R1-R5: the model is consulted only when lexical recall fails."""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.capsule import append_event, init_store, seal_store
from aiinvite.recall.index import build_index
from aiinvite.recall.retrieve import search
from aiinvite.recall.rewrite import build_prompt, sanitize

STAMP = "2026-09-01T09:00:00+08:00"
NOW = "2026-11-01T12:00:00+08:00"


class Counter:
    """A rewriter that records how often it was asked."""

    def __init__(self, reply="狗 去世 阿黄"):
        self.reply = reply
        self.calls = 0

    def __call__(self, prompt):
        self.calls += 1
        return self.reply


class TestRewriteOnFailure(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="rewrite_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "m"
        init_store(self.store)
        append_event(self.store, "user", "我的狗叫阿黄，它去年走了", STAMP)
        for index in range(40):
            append_event(self.store, "user", "第" + str(index) + "条闲聊，天气还行", STAMP)
        seal_store(self.store)
        build_index(self.store)

    def _ids(self, query, rewriter=None):
        return [hit.event_id for hit in search(self.store, query, k=5, now=NOW, rewriter=rewriter)]

    def test_r1_hit_path_never_calls_the_model(self) -> None:
        """R1: a question that already matches must not pay for inference."""
        counter = Counter()
        self._ids("我的狗叫什么名字", rewriter=counter)
        self.assertEqual(counter.calls, 0)

    def test_r2_failure_path_calls_once(self) -> None:
        """R2: a question with no lexical hit triggers exactly one rewrite."""
        counter = Counter()
        self._ids("那件让我很难过的事你还记得吗", rewriter=counter)
        self.assertEqual(counter.calls, 1)

    def test_r3_rewrite_finds_the_memory(self) -> None:
        """R3: the rewritten terms reach the memory the question was about."""
        counter = Counter("阿黄 狗 去世")
        ids = self._ids("那件让我很难过的事你还记得吗", rewriter=counter)
        self.assertEqual(len(ids), 1)

    def test_r4_dead_model_degrades_quietly(self) -> None:
        """R4: a raising rewriter leaves the original result intact."""
        def dead(prompt):
            raise RuntimeError("model down")

        original = self._ids("我的狗叫什么名字")
        with_dead = self._ids("我的狗叫什么名字", rewriter=dead)
        self.assertEqual(original, with_dead)

    def test_r5_no_rewriter_keeps_old_behaviour(self) -> None:
        """R5: default search is unchanged when no rewriter is configured."""
        self.assertEqual(self._ids("我的狗叫什么名字"), self._ids("我的狗叫什么名字", rewriter=None))

    def test_prompt_asks_for_keywords_only(self) -> None:
        """R6: the instruction asks for keywords, not prose."""
        prompt = build_prompt("那件难过的事")
        self.assertIn("关键词", prompt)
        self.assertIn("那件难过的事", prompt)

    def test_sanitize_strips_prose(self) -> None:
        """R6: prose from the model becomes clean terms, capped."""
        self.assertEqual(sanitize("狗 去世 阿黄，难过。the dog"), ("狗", "去世", "阿黄", "难过"))
        self.assertLessEqual(len(sanitize("一 二 三 四 五 六 七 八")), 6)


if __name__ == "__main__":
    unittest.main()
