"""M16 / P3: the user card trim must equal the entry-by-entry reference."""
from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.persona.user_card import CARD_BUDGET, UserCard, _render


def _drop_one(data: dict) -> bool:
    """The reference trim: one entry per render, lowest priority first."""
    for key in ("dislike", "like"):
        items = data["prefs"][key]
        if items:
            items.pop()
            return True
    for key in ("ongoing", "promises", "people", "taboos"):
        items = data[key]
        if items:
            items.pop()
            return True
    address = data["address"]
    never = address.get("never")
    if never:
        never.pop()
        return True
    if address.get("self"):
        del address["self"]
        address.pop("self_evidence", None)
        return True
    if address.get("call"):
        del address["call"]
        address.pop("call_evidence", None)
        return True
    return False


def reference_text(card: UserCard) -> str:
    """The trim this module shipped with, kept here as the oracle."""
    data = card.to_payload()
    rendered = _render(data)
    while len(rendered) > CARD_BUDGET:
        assert _drop_one(data)
        rendered = _render(data)
    return rendered


def pref(text: str, index: int) -> dict:
    return {"text": text, "evidence": "ev_%06d" % index}


def card_with(dislikes: int = 0, likes: int = 0, people: int = 0,
              promises: int = 0, ongoing: int = 0, taboos: int = 0,
              never: int = 0) -> UserCard:
    return UserCard(
        address={
            "call": "老周",
            "call_evidence": "ev_1",
            "self": "老王",
            "self_evidence": "ev_2",
            "never": [{"text": "宝贝%d" % i, "evidence": "ev_n%d" % i} for i in range(never)],
        },
        people=tuple({"relation": "朋友", "name": "小%d" % i, "evidence": "ev_p%d" % i} for i in range(people)),
        taboos=tuple({"text": "忌%d" % i, "evidence": "ev_t%d" % i} for i in range(taboos)),
        promises=tuple({"text": "答应%d" % i, "since": "ev_s%d" % i, "evidence": "ev_s%d" % i} for i in range(promises)),
        ongoing=tuple({"text": "近况%d" % i, "evidence": "ev_o%d" % i} for i in range(ongoing)),
        prefs={
            "like": tuple(pref("爱%d" % i, i) for i in range(likes)),
            "dislike": tuple(pref("厌%d" % i, i) for i in range(dislikes)),
        },
    )


class TestCardBudget(unittest.TestCase):
    def test_small_card_is_untouched(self) -> None:
        card = card_with(likes=2, dislikes=1)
        self.assertEqual(card.text(), reference_text(card))
        self.assertLessEqual(len(card.text()), CARD_BUDGET)

    def test_trim_matches_the_reference(self) -> None:
        for sizes in (
            dict(dislikes=40, likes=30, people=20, promises=5, ongoing=3, taboos=2, never=4),
            dict(likes=200),
            dict(dislikes=150, likes=150),
            dict(people=40, taboos=10, never=20, likes=5),
            dict(dislikes=500, likes=500, people=100, ongoing=3),
        ):
            card = card_with(**sizes)
            with self.subTest(sizes=sizes):
                self.assertEqual(card.text(), reference_text(card))
                self.assertLessEqual(len(card.text()), CARD_BUDGET)

    def test_the_name_is_dropped_last(self) -> None:
        card = card_with(dislikes=400, likes=400)
        self.assertIn("称呼：老周", card.text())

    def test_a_card_that_is_all_name_trims_to_empty(self) -> None:
        card = UserCard(
            address={"call": "老" * (CARD_BUDGET + 50), "never": []},
            people=(), taboos=(), promises=(), ongoing=(),
            prefs={"like": (), "dislike": ()},
        )
        self.assertEqual(card.text(), reference_text(card))
        self.assertEqual(card.text(), "")


if __name__ == "__main__":
    unittest.main()
