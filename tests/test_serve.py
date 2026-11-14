"""M37: the server-side service keeps many stores warm, one lock per key."""
from __future__ import annotations

import pathlib
import re
import shutil
import sys
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.capsule import verify_path
from aiinvite.errors import AiInviteError
from aiinvite.serve import MemoryService, check_key

NOW = "2026-11-14T10:00:00+08:00"
EVENT_ID = re.compile(r"^ev_[0-9]{6}$")


class TestMemoryService(unittest.TestCase):
    """S1-S10: isolation, locks, persistence and console views."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_serve_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.service = self._service()

    def _service(self, **kwargs) -> MemoryService:
        service = MemoryService(self.root, "qwen3.5:9b", now=NOW, **kwargs)
        self.addCleanup(service.close)
        return service

    def test_turn_returns_prompt_and_event_id(self) -> None:
        """S1: a turn records the line and returns the prompt for it."""
        out = self.service.turn("u1", "  我叫老周  ")
        self.assertIn("## this turn", out["prompt"])
        self.assertIn("我叫老周", out["prompt"])
        self.assertRegex(out["event_id"], EVENT_ID)
        self.assertIsInstance(out["recalled"], list)
        self.assertEqual(out["model"], "qwen3.5:9b")
        self.assertEqual(verify_path(self.service.store_for("u1")).events, 1)

    def test_two_users_do_not_share_a_card(self) -> None:
        """S2: one key is one memory; cards never leak across keys."""
        self.service.turn("u1", "我叫老周")
        self.service.turn("u2", "我叫小林")
        first = self.service.view("u1")["card"]
        second = self.service.view("u2")["card"]
        self.assertEqual(first["address"]["call"], "老周")
        self.assertEqual(second["address"]["call"], "小林")
        self.assertNotEqual(self.service.view("u1")["store"], self.service.view("u2")["store"])
        # The kid identifies a persona, not a transcript: two fresh users with
        # identical persona state share it, and that is by design.
        self.assertEqual(self.service.view("u1")["kid"], self.service.view("u2")["kid"])

    def test_view_reports_identity_card_and_rules(self) -> None:
        """S3: the console view is JSON-ready and stable across instances."""
        self.service.turn("u1", "我叫老周，别叫我宝贝")
        view = self.service.view("u1")
        self.assertEqual(view["events"], 1)
        self.assertEqual(view["card"]["address"]["call"], "老周")
        self.assertTrue(view["rules"])
        self.assertEqual(view["key"], "u1")
        self.assertTrue(view["store"].endswith("u1"))
        # A second process (a second instance) derives the same identity.
        other = self._service()
        self.assertEqual(other.view("u1")["kid"], view["kid"])

    def test_remember_is_evidence_and_moves_identity(self) -> None:
        """S4: a console edit is a directive, not a card write."""
        self.service.turn("u1", "我叫老周")
        before = self.service.view("u1")
        after = self.service.remember("u1", "回复控制在两句以内")
        self.assertNotEqual(after["kid"], before["kid"])
        self.assertEqual(after["events"], 2)
        self.assertIn("回复控制在两句以内", after["canon"])
        reopened = self._service()
        self.assertEqual(reopened.view("u1")["kid"], after["kid"])
        self.assertEqual(reopened.view("u1")["events"], 2)
        self.assertIn("回复控制在两句以内", reopened.view("u1")["canon"])

    def test_pin_and_unpin_reach_the_prompt(self) -> None:
        """S5: a pinned memory takes its seat; unpin gives it back."""
        out = self.service.turn("u1", "我下周三要去体检")
        pinned = self.service.pin("u1", out["event_id"])
        self.assertEqual([item["text"] for item in pinned["pins"]], ["我下周三要去体检"])
        prompt = self.service.turn("u1", "你好")["prompt"]
        self.assertIn("## never forget", prompt)
        self.assertIn("我下周三要去体检", prompt)
        cleared = self.service.unpin("u1", out["event_id"])
        self.assertEqual(cleared["pins"], [])
        later = self.service.turn("u1", "今天做什么")["prompt"]
        self.assertNotIn("## never forget", later)

    def test_concurrent_turns_keep_the_chain_valid(self) -> None:
        """S6: eight writers on one key serialise; no torn append."""
        errors: list[str] = []

        def work(index: int) -> None:
            try:
                self.service.turn("race", f"第{index}句")
            except Exception as exc:  # noqa: BLE001 - reported below
                errors.append(repr(exc))

        writers = [threading.Thread(target=work, args=(i,)) for i in range(8)]
        for writer in writers:
            writer.start()
        for writer in writers:
            writer.join()
        self.assertEqual(errors, [])
        self.assertEqual(verify_path(self.service.store_for("race")).events, 8)

    def test_reply_runs_the_actuation_gate(self) -> None:
        """S11: a violating reply is refused and its text never lands."""
        service = self.service
        service.remember("u1", "别叫我宝贝")
        service.turn("u1", "你今天开心吗")
        refused = service.reply("u1", "开心呀，宝贝")
        self.assertFalse(refused["allowed"])
        self.assertEqual(refused["rule"], "禁称呼")
        allowed = service.reply("u1", "开心，你呢？")
        self.assertTrue(allowed["allowed"])
        self.assertEqual(allowed["rule"], "")
        # remember + turn + refusal + allowed, and the refused text is absent.
        self.assertEqual(service.view("u1")["events"], 4)
    def test_bad_keys_are_rejected(self) -> None:
        """S7: keys become directory names, so the check is a boundary."""
        for bad in ["", "   ", "../escape", "a/b", "a\\b", "x" * 200, "CON", ".hidden"]:
            with self.subTest(key=bad):
                with self.assertRaises(AiInviteError):
                    check_key(bad)
        self.assertEqual(check_key(" user-1.v2 "), "user-1.v2")
        with self.assertRaises(AiInviteError):
            self.service.turn("", "hello")
        with self.assertRaises(AiInviteError):
            self.service.turn("u1", "   ")

    def test_eviction_keeps_the_store(self) -> None:
        """S8: the pool is bounded; memory on disk is not."""
        service = self._service(max_sessions=1)
        service.turn("a", "我叫老周")
        kid = service.view("a")["kid"]
        service.turn("b", "我叫小林")  # evicts a
        self.assertEqual(service.stats()["sessions"], 1)
        self.assertEqual(service.view("a")["kid"], kid)
        self.assertEqual(service.view("a")["events"], 1)

    def test_empty_store_view_degrades(self) -> None:
        """S9: a user who never spoke has a view, not an exception."""
        view = self.service.view("fresh")
        self.assertEqual(view["kid"], "")
        self.assertEqual(view["events"], 0)
        self.assertEqual(view["card"], {})
        self.assertEqual(view["pins"], [])
        self.assertTrue(self.service.store_for("fresh").is_dir())

    def test_stats_and_close(self) -> None:
        """S10: the pool reports itself and can be dropped."""
        self.service.turn("u1", "你好")
        self.service.turn("u2", "你好")
        self.assertEqual(self.service.stats(), {"sessions": 2, "keys": 2})
        self.service.close()
        self.assertEqual(self.service.stats()["sessions"], 0)
        self.assertEqual(self.service.turn("u1", "还在吗")["model"], "qwen3.5:9b")


if __name__ == "__main__":
    unittest.main()