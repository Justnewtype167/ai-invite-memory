"""C1-C7: clues are grounded, gated, and never outrank a literal hit."""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.capsule import append_event, init_store, seal_store
from aiinvite.recall.clues import build_prompt, generate_clues, split_clues
from aiinvite.recall.index import build_index
from aiinvite.recall.retrieve import search

MEMORY = "我的狗叫阿黄，它去年走了"
STAMP = "2026-09-01T09:00:00+08:00"
NOW = "2026-11-01T12:00:00+08:00"
HARD = "你还记得我跟你提过的那件难过的事吗"


class TestClueGate(unittest.TestCase):
    def test_c1_real_output_survives(self) -> None:
        """C1: grounded entities and a vocabulary bridge both survive."""
        entities, bridges = split_clues(MEMORY, "狗 阿黄 去年 走了 悲伤")
        self.assertIn("阿黄", entities)
        self.assertIn("悲伤", bridges)

    def test_c2_invented_scene_is_dropped(self) -> None:
        """C2: a fabricated scene contributes nothing at all."""
        entities, bridges = split_clues(MEMORY, "雨夜，医院，病历本，父亲，药瓶")
        self.assertEqual(entities, ())
        self.assertEqual(bridges, ())

    def test_c3_bridge_outside_the_vocabulary_is_dropped(self) -> None:
        """C3: only closed-vocabulary words may act as a bridge."""
        entities, bridges = split_clues(MEMORY, "阿黄 病历本")
        self.assertIn("阿黄", entities)
        self.assertEqual(bridges, ())

    def test_c4_entity_must_appear_in_the_source(self) -> None:
        """C4: a plausible but absent entity is invention."""
        entities, _ = split_clues(MEMORY, "小明 公园")
        self.assertEqual(entities, ())

    def test_c5_prompt_carries_the_memory(self) -> None:
        """C5: the model always sees the text it is making clues for."""
        prompt = build_prompt(MEMORY)
        self.assertIn(MEMORY, prompt)
        self.assertIn("线索", prompt)

    def test_c6_dead_caller_yields_no_clues(self) -> None:
        """C6: a dead model must not break the caller."""
        def dead(prompt):
            raise RuntimeError("down")

        self.assertEqual(generate_clues(MEMORY, dead), ((), ()))
        self.assertEqual(generate_clues(MEMORY, None), ((), ()))


class TestClueRetrieval(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="clue_rc_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "m"
        init_store(self.store)
        self.fact = append_event(self.store, "user", MEMORY, STAMP)
        for index in range(30):
            append_event(self.store, "user", "第" + str(index) + "条闲聊", STAMP)
        seal_store(self.store)
        build_index(self.store)

    def _ids(self, query, clues=None):
        return [hit.event_id for hit in search(self.store, query, k=5, now=NOW, clues=clues)]

    def test_c7_clues_recover_the_hard_question(self) -> None:
        """C7: without clues the hard question finds nothing; with them it does."""
        self.assertEqual(self._ids(HARD), [])
        clues = [(self.fact.id, "阿黄 狗 去年 悲伤")]
        self.assertEqual(self._ids(HARD, clues=clues), [self.fact.id])

    def test_c8_literal_hit_still_ranks_first(self) -> None:
        """C8: a clue is a fallback source, never a ranking shortcut."""
        clues = [(self.fact.id, "阿黄 狗 悲伤")]
        hits = search(self.store, "我的狗叫什么名字", k=5, now=NOW, clues=clues)
        self.assertTrue(hits)
        self.assertEqual(hits[0].event_id, self.fact.id)
        self.assertGreater(hits[0].score, 0.2)

    def test_c9_no_clues_keeps_old_behaviour(self) -> None:
        """C9: an empty clue set changes nothing."""
        self.assertEqual(self._ids("我的狗叫什么名字"), self._ids("我的狗叫什么名字", clues=[]))

    def test_c10_a_common_bridge_is_dropped(self) -> None:
        """C10: a label half the store carries says nothing, so it is ignored."""
        shared = [(event_id, "", "悲伤") for event_id in self._all_ids()[:3]]
        self.assertEqual(self._ids(HARD, clues=shared), [])

    def test_c11_a_rare_bridge_still_counts(self) -> None:
        """C11: one or two memories sharing a bridge is information, not noise."""
        rare = [(self.fact.id, "", "悲伤")]
        self.assertEqual(self._ids(HARD, clues=rare), [self.fact.id])

    def test_c12_a_grounded_entity_always_counts(self) -> None:
        """C12: an entity match is verified against the text, so no cap applies."""
        many = [(self.fact.id, "阿黄", "")]
        many += [(event_id, "阿黄", "") for event_id in self._all_ids()[:3]]
        ids = [hit.event_id for hit in search(self.store, "阿黄是谁", k=5, now=NOW, clues=many)]
        self.assertIn(self.fact.id, ids)

    def test_c13_wrong_bridge_pollution_is_bounded(self) -> None:
        """C13: wrong labels for many memories cannot flood the result."""
        wrong = [(event_id, "", "悲伤") for event_id in self._all_ids()[:4]]
        self.assertEqual(self._ids(HARD, clues=wrong), [])

    def _all_ids(self):
        """Return every event id in append order."""
        from aiinvite.kernel.compiler import read_evidence
        return [event.event_id for event in read_evidence(self.store)]


if __name__ == "__main__":
    unittest.main()
