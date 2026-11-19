# -*- coding: utf-8 -*-
""""叫我早起" is a request, not a name: the command guard on the user card."""
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


class TestAddressCommands(unittest.TestCase):
    def _address(self, lines):
        root = pathlib.Path(tempfile.mkdtemp(prefix="addr_cmd_"))
        self.addCleanup(shutil.rmtree, root, True)
        store = root / "m"
        init_store(store)
        for index, text in enumerate(lines):
            append_event(store, "user", text, f"2026-11-0{index + 1}T09:00:00+08:00")
        seal_store(store)
        view = build_persona_view(store, policy=Policy(now="2026-11-01T10:00:00+08:00"))
        return view.user_card.to_payload()["address"]

    def test_wake_up_request_is_not_a_name(self) -> None:
        """The field bug: "叫我早起" became 称呼=早起."""
        address = self._address(["明天开始叫我早起吧"])
        self.assertEqual(address["call"], "")

    def test_daily_cue_before_the_verb_is_a_command(self) -> None:
        address = self._address(["每天叫我背单词"])
        self.assertEqual(address["call"], "")

    def test_reminder_cue_is_a_command(self) -> None:
        self.assertEqual(self._address(["记得叫我起床"])["call"], "")
        self.assertEqual(self._address(["叫我早点睡"])["call"], "")

    def test_real_names_survive(self) -> None:
        self.assertEqual(self._address(["以后就叫我老周吧"])["call"], "老周")
        self.assertEqual(self._address(["叫我一声宝贝"])["call"], "宝贝")
        self.assertEqual(self._address(["叫我小王"])["call"], "小王")

    def test_naming_tail_overrides_the_frequency_cue(self) -> None:
        """"每天叫我老周就好" names someone, so the cue must not veto it."""
        self.assertEqual(self._address(["每天叫我老周就好"])["call"], "老周")

    def test_command_does_not_become_a_taboo(self) -> None:
        address = self._address(["别叫我早起，叫我老周"])
        self.assertEqual(address["call"], "老周")
        self.assertEqual([item["text"] for item in address["never"]], [])

    def test_taboo_still_works(self) -> None:
        address = self._address(["我叫老周，别叫我宝贝"])
        self.assertEqual(address["call"], "老周")
        self.assertEqual([item["text"] for item in address["never"]], ["宝贝"])


if __name__ == "__main__":
    unittest.main()
