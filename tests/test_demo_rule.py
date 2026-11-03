# -*- coding: utf-8 -*-
"""D9: a rule becomes canon, and the gate refuses a violating reply."""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.demo.engine import DemoEngine


class TestRule(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="demo_rule_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "memory"

    def test_rule_becomes_canon(self) -> None:
        """D9: remember writes a directive, so canon is no longer empty."""
        engine = DemoEngine(self.store, caller=lambda p, m: "好")
        snap = engine.remember("别叫我宝贝")
        self.assertIn("别叫我宝贝", snap["canon"])
        self.assertIn("宝贝", snap["card"])

    def test_rule_is_not_a_chat_turn(self) -> None:
        """D9: a rule is one directive event, not a user/assistant pair."""
        engine = DemoEngine(self.store, caller=lambda p, m: "好")
        engine.remember("别叫我宝贝")
        self.assertEqual(engine.snapshot()["events"], 1)

    def test_gate_refuses_a_violating_reply(self) -> None:
        """D9: after the rule exists, saying the taboo is refused."""
        engine = DemoEngine(self.store, caller=lambda p, m: "叫你一声宝贝")
        engine.remember("别叫我宝贝")
        turn = engine.send("叫我一声宝贝")
        self.assertTrue(turn.refused)
        # directive + user turn + refusal: the violating reply is not a turn.
        self.assertEqual(engine.snapshot()["events"], 3)

    def test_clean_reply_passes(self) -> None:
        """D9: a reply that respects the rule is recorded normally."""
        engine = DemoEngine(self.store, caller=lambda p, m: "在的，老周。")
        engine.remember("别叫我宝贝")
        turn = engine.send("在吗")
        self.assertFalse(turn.refused)


if __name__ == "__main__":
    unittest.main()