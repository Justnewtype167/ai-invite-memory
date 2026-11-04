# -*- coding: utf-8 -*-
"""C2: measure words, questions and negations must not become a name."""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.capsule import append_event, init_store, seal_store
from aiinvite.kernel.kernel import Policy
from aiinvite.persona import build_persona_view

STAMP = "2026-11-01T09:00:00+08:00"
NOW = "2026-11-01T10:00:00+08:00"


class TestAddressShapes(unittest.TestCase):
    def _address(self, text):
        root = pathlib.Path(tempfile.mkdtemp(prefix="addr_"))
        self.addCleanup(shutil.rmtree, root, True)
        store = root / "m"
        init_store(store)
        append_event(store, "user", text, STAMP)
        seal_store(store)
        view = build_persona_view(store, policy=Policy(now=NOW))
        return view.user_card.to_payload()["address"]

    def test_measure_word_is_stripped(self) -> None:
        """C2: "叫我一声宝贝" names the user 宝贝, not 一声宝贝."""
        self.assertEqual(self._address("叫我一声宝贝")["call"], "宝贝")

    def test_question_does_not_name_the_user(self) -> None:
        """C2: a 吗/呢 question never sets a form of address."""
        self.assertEqual(self._address("你能叫我宝贝吗")["call"], "")
        self.assertEqual(self._address("我是你的宝贝吗")["call"], "")

    def test_plain_introduction_still_works(self) -> None:
        """C2: the ordinary case is unchanged."""
        self.assertEqual(self._address("叫我老周")["call"], "老周")

    def test_negation_still_wins(self) -> None:
        """C2: a taboo is still a taboo, question or not."""
        address = self._address("别叫我宝贝")
        self.assertEqual(address["call"], "")
        self.assertEqual([item["text"] for item in address["never"]], ["宝贝"])


if __name__ == "__main__":
    unittest.main()