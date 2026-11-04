"""P3: the card memo must never change what the card says."""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.capsule import append_event, init_store, seal_store
from aiinvite.kernel.compiler import read_evidence
from aiinvite.kernel.kernel import Policy
from aiinvite.persona import build_persona_view
from aiinvite.persona.user_card import derive_user_card

CORPUS = ROOT / "corpus" / "personas.jsonl"
STAMP = "2026-11-01T09:00:00+08:00"


def persona_lines(limit=40):
    """Return synthetic conversation lines drawn from the persona corpus."""
    if not CORPUS.is_file():
        return [["我叫老周", "别叫我宝贝", "我喜欢喝茶"]]
    rows = []
    with CORPUS.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
            if len(rows) >= limit:
                break
    batches = []
    for row in rows:
        lines = []
        name = str(row.get("name", "")).strip()
        if name:
            lines.append("我叫" + name)
        lines.extend(str(item) for item in row.get("sample_utterances", [])[:2])
        lines.extend(str(item) for item in row.get("seed_facts", [])[:2])
        if lines:
            batches.append(lines)
    return batches


class TestCardMemo(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="card_memo_"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _store(self, lines):
        store = self.root / ("m" + str(abs(hash(tuple(lines)))))
        init_store(store)
        for index, text in enumerate(lines):
            append_event(store, "user", text, STAMP)
            append_event(store, "assistant", "收到。", STAMP)
        seal_store(store)
        return store

    def test_memo_matches_a_cold_derive(self) -> None:
        """P3: a warmed cache produces exactly the cold payload, over the corpus."""
        batches = persona_lines()
        cache = {}
        checked = 0
        for lines in batches:
            store = self._store(lines)
            events = read_evidence(store)
            cold = derive_user_card(events).to_payload()
            derive_user_card(events, cache=cache)          # warm the memo
            warm = derive_user_card(events, cache=cache).to_payload()
            self.assertEqual(cold, warm, "cold and warm differ for " + str(lines[:2]))
            checked += 1
        self.assertGreaterEqual(checked, 10)

    def test_memo_survives_an_append(self) -> None:
        """P3: after a new event the memoised card equals a fresh derivation."""
        store = self._store(["我叫老周", "别叫我宝贝"])
        cache = {}
        derive_user_card(read_evidence(store), cache=cache)
        append_event(store, "user", "我喜欢喝茶，讨厌香菜", STAMP)
        events = read_evidence(store)
        memoised = derive_user_card(events, cache=cache).to_payload()
        fresh = derive_user_card(events).to_payload()
        self.assertEqual(memoised, fresh)
        self.assertIn("茶", memoised["prefs"]["like"][0]["text"])

    def test_identity_is_unaffected(self) -> None:
        """P3: caching the card cannot move the kid."""
        store = self._store(["我叫老周"])
        cache = {}
        one = build_persona_view(store, policy=Policy(now=STAMP))
        two = build_persona_view(store, policy=Policy(now=STAMP), card_cache=cache)
        three = build_persona_view(store, policy=Policy(now=STAMP), card_cache=cache)
        self.assertEqual(one.kid, two.kid)
        self.assertEqual(two.kid, three.kid)
        self.assertEqual(one.user_card.to_payload(), three.user_card.to_payload())


if __name__ == "__main__":
    unittest.main()
