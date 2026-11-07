"""P3: the incremental card fold must equal the reference derivation.

The fold is an optimisation, so the test does not check "the card looks
right" -- it checks the folded card against derive_user_card at every step,
on fixed edge cases, on the persona corpus, and on a seeded random stream.
"""
from __future__ import annotations

import json
import pathlib
import random
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.kernel.kernel import EvidenceEvent
from aiinvite.persona.card_fold import CardState, fold_user_card
from aiinvite.persona.user_card import derive_user_card

STAMP = "2026-11-01T09:00:00+08:00"
CORPUS = ROOT / "corpus" / "personas.jsonl"


def event(index, text, type="turn", kind=None, role="user", stamp=STAMP):
    """Build one evidence event with a zero-padded, sortable id."""
    return EvidenceEvent("%06d" % index, stamp, type, kind, text, role=role)


def payload(card):
    return card.to_payload()


class TestCardFold(unittest.TestCase):
    def assertMatches(self, events, rules=None):
        """Fold every prefix and compare with the reference at each step."""
        state = CardState()
        for stop in range(len(events) + 1):
            folded, state = fold_user_card(events[:stop], state, rules=rules)
            fresh = derive_user_card(events[:stop], rules=rules)
            self.assertEqual(
                payload(folded), payload(fresh),
                "prefix %d diverged: %s" % (stop, events[stop - 1].text if stop else "empty"),
            )

    def test_empty(self):
        folded, state = fold_user_card([])
        self.assertEqual(payload(folded), payload(derive_user_card([])))
        self.assertEqual(state.count, 0)

    def test_address_edge_cases(self):
        lines = [
            "我叫老周",
            "别叫我宝贝",
            "你能叫我宝贝吗",
            "叫我一声宝贝",
            "我妈叫我回家吃饭",
            "自称老王",
            "我叫小张就好",
            "不要叫我小张",
            "名字是阿May",
            "叫我老周吧",
        ]
        events = [event(index, text) for index, text in enumerate(lines, 1)]
        self.assertMatches(events)
        card = fold_user_card(events)[0]
        self.assertEqual(card.address.get("call"), "老周")
        self.assertEqual([item["text"] for item in card.address["never"]], ["宝贝", "小张"])

    def test_assistant_words_never_shape_the_card(self):
        events = [
            event(1, "我叫老周"),
            event(2, "叫我一声宝贝", role="assistant"),
            event(3, "别叫我老周", role="assistant"),
            event(4, "我喜欢喝茶", role="assistant"),
        ]
        self.assertMatches(events)
        card = fold_user_card(events)[0]
        self.assertEqual(card.address.get("call"), "老周")
        self.assertEqual(card.address["never"], [])
        self.assertEqual(card.prefs["like"], ())

    def test_persona_events_never_shape_the_card(self):
        events = [
            event(1, "别叫我老周", type="directive", kind="lock"),
            event(2, "叫我宝贝", type="directive", kind="trait"),
            event(3, "叫我宝贝", type="proposal"),
            event(4, "我喜欢茶", type="directive", kind="lock"),
        ]
        events[2] = EvidenceEvent("000003", STAMP, "proposal", None, "叫我宝贝", target="self.trait")
        self.assertMatches(events)

    def test_promise_closed_by_a_later_event(self):
        events = [
            event(1, "我答应你明天早睡"),
            event(2, "我答应你多喝水"),
            event(3, "我做到了"),
        ]
        self.assertMatches(events)
        card = fold_user_card(events)[0]
        self.assertEqual(card.promises, ())

    def test_promise_left_open(self):
        events = [event(1, "我答应你明天早睡"), event(2, "今天有点累")]
        self.assertMatches(events)
        card = fold_user_card(events)[0]
        self.assertEqual(len(card.promises), 1)

    def test_people_and_milestones(self):
        events = [
            event(1, "我妈叫我回家"),
            event(2, "我妹妹叫小满"),
            event(3, "搬家了", type="milestone"),
            event(4, "换工作了", type="milestone"),
            event(5, "开始健身", type="milestone"),
            event(6, "养了只猫", type="milestone"),
        ]
        self.assertMatches(events)
        card = fold_user_card(events)[0]
        self.assertEqual(len(card.ongoing), 3)
        self.assertEqual(card.ongoing[-1]["text"], "养了只猫")

    def test_prefs_first_seen_order_and_evidence(self):
        events = [
            event(1, "我喜欢喝茶"),
            event(2, "我喜欢喝咖啡"),
            event(3, "我喜欢喝茶"),
            event(4, "我不喜欢烟味"),
            event(5, "我不喜欢吵闹"),
        ]
        self.assertMatches(events)
        card = fold_user_card(events)[0]
        self.assertEqual([item["text"] for item in card.prefs["like"]], ["喝茶", "喝咖啡"])
        self.assertEqual([item["evidence"] for item in card.prefs["like"]], ["000001", "000002"])

    def test_rules_change_rebuilds(self):
        events = [event(1, "叫我一声宝贝"), event(2, "别叫我老周")]
        folded, state = fold_user_card(events)
        rules = {
            "address": {
                "call": "叫(我)?([^，。！？,.!?]{1,10})",
                "self": "自称([^，。！？,.!?]{1,10})",
                "aliases": [],
                "negations": [],
                "suffixes": ["吧"],
            },
            "prefs": {"like": [], "dislike": []},
        }
        changed, _ = fold_user_card(events, state, rules=rules)
        self.assertEqual(payload(changed), payload(derive_user_card(events, rules=rules)))
        self.assertEqual(payload(folded), payload(derive_user_card(events)))

    def test_shrunk_evidence_rebuilds(self):
        events = [event(index, text) for index, text in enumerate(
            ["我叫老周", "别叫我宝贝", "我喜欢茶"], 1)]
        _, state = fold_user_card(events)
        shorter, _ = fold_user_card(events[:2], state)
        self.assertEqual(payload(shorter), payload(derive_user_card(events[:2])))

    def test_rewritten_evidence_rebuilds(self):
        events = [event(1, "我叫老周"), event(2, "我叫小张")]
        _, state = fold_user_card(events)
        rewritten = [event(1, "我叫老周"), event(2, "别叫我老周")]
        folded, _ = fold_user_card(rewritten, state)
        self.assertEqual(payload(folded), payload(derive_user_card(rewritten)))

    def test_cache_does_not_change_the_result(self):
        events = [event(index, text) for index, text in enumerate(
            ["我叫老周", "别叫我宝贝", "我喜欢茶", "我妈叫我回家"], 1)]
        cache = {}
        state = CardState()
        for stop in range(len(events) + 1):
            folded, state = fold_user_card(events[:stop], state, cache=cache)
            self.assertEqual(payload(folded), payload(derive_user_card(events[:stop])))

    def test_corpus_personas_match_at_every_step(self):
        for lines in corpus_lines(40):
            events = [event(index, text) for index, text in enumerate(lines, 1)]
            self.assertMatches(events)

    def test_random_stream_matches_at_every_step(self):
        rng = random.Random(20261107)
        for _ in range(20):
            events = random_events(rng)
            self.assertMatches(events)


def corpus_lines(limit):
    """Turn the persona corpus into user turns, as the memo test does."""
    if not CORPUS.is_file():
        return [["我叫老周", "别叫我宝贝", "我喜欢喝茶"]]
    batches = []
    with CORPUS.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            lines = []
            name = str(row.get("name", "")).strip()
            if name:
                lines.append("我叫" + name)
            lines.extend(str(item) for item in row.get("sample_utterances", [])[:2])
            lines.extend(str(item) for item in row.get("seed_facts", [])[:2])
            if lines:
                batches.append(lines)
            if len(batches) >= limit:
                break
    return batches


NAMES = ["老周", "小张", "阿May", "小明"]
TEXTS = [
    "我叫{n}",
    "叫我{n}就好",
    "叫我一声{n}",
    "别叫我{n}",
    "不要叫我{n}",
    "你能叫我{n}吗",
    "名字是{n}",
    "我喜欢{n}味的茶",
    "我不喜欢{n}的噪音",
    "我妈叫我回家吃饭",
    "我答应你明天早点睡",
    "我做到了",
    "搬家了",
    "开始健身",
]


def random_events(rng):
    """Return a seeded stream mixing roles, event types and card triggers."""
    events = []
    for index in range(1, rng.randint(5, 30) + 1):
        text = rng.choice(TEXTS).format(n=rng.choice(NAMES))
        roll = rng.random()
        if roll < 0.08:
            events.append(event(index, text, role="assistant"))
        elif roll < 0.14:
            events.append(event(index, text, type="milestone"))
        elif roll < 0.20:
            events.append(event(index, text, type="directive", kind="lock"))
        else:
            events.append(event(index, text))
    return events


if __name__ == "__main__":
    unittest.main()
