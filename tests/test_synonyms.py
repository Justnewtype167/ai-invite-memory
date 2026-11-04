"""S1-S4: synonym expansion helps recall without hurting determinism or budget."""
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
from aiinvite.recall.synonyms import MAX_EXPANSION_TERMS, expand, load_groups

STAMP = "2026-09-01T09:00:00+08:00"
NOW = "2026-11-01T12:00:00+08:00"


class TestSynonyms(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="syn_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "m"
        init_store(self.store)
        append_event(self.store, "user", "我的狗叫阿黄，它去年走了", STAMP)
        for index in range(40):
            append_event(self.store, "user", "第" + str(index) + "条闲聊，天气还行", STAMP)
        seal_store(self.store)
        build_index(self.store)

    def _texts(self, query):
        return [hit.text for hit in search(self.store, query, k=10, now=NOW)]

    def test_s1_paraphrase_reaches_the_memory(self) -> None:
        """S1: "my little animal" now reaches "my dog is Ahuang"."""
        texts = " ".join(self._texts("我养的那只小动物现在怎样了"))
        self.assertIn("阿黄", texts)

    def test_s1b_literal_query_still_works(self) -> None:
        """S1: the direct question is unaffected."""
        texts = " ".join(self._texts("我的狗叫什么名字"))
        self.assertIn("阿黄", texts)

    def test_s2_expansion_is_bounded(self) -> None:
        """S2: expansion can never flood the FTS query."""
        extra = expand("我养的那只小动物现在怎样了")
        self.assertLessEqual(len(extra), MAX_EXPANSION_TERMS)
        self.assertNotIn("小动", [term for term in extra if term == ""])

    def test_s3_expansion_is_deterministic(self) -> None:
        """S3: the same query always yields the same expansion and ranking."""
        first = expand("我养的小动物")
        second = expand("我养的小动物")
        self.assertEqual(first, second)
        self.assertEqual(
            [hit.event_id for hit in search(self.store, "我养的小动物", k=10, now=NOW)],
            [hit.event_id for hit in search(self.store, "我养的小动物", k=10, now=NOW)],
        )

    def test_s4_no_synonym_hit_without_a_group(self) -> None:
        """S4: a query with no group leaves the candidate set unchanged."""
        self.assertEqual(expand("今天星期三"), ())

    def test_s5_groups_are_well_formed(self) -> None:
        """S5: every group has at least two non-empty terms."""
        for group in load_groups():
            self.assertGreaterEqual(len(group), 2)
            self.assertTrue(all(term.strip() for term in group))


if __name__ == "__main__":
    unittest.main()
