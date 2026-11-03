# -*- coding: utf-8 -*-
"""R1: evidence keeps the speaker, and only the user shapes the card."""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.capsule import append_event, init_store, seal_store
from aiinvite.kernel.compiler import compile_kernel, read_evidence
from aiinvite.kernel.kernel import Policy
from aiinvite.persona import build_persona_view

STAMP = "2026-11-03T11:00:00+08:00"
NOW = "2026-11-03T12:00:00+08:00"


class TestRoles(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="role_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "m"
        init_store(self.store)

    def test_role_survives_parsing(self) -> None:
        """R1: read_evidence must expose the speaker instead of None."""
        append_event(self.store, "user", "你好", STAMP)
        append_event(self.store, "assistant", "你好呀", STAMP)
        seal_store(self.store)
        roles = [event.role for event in read_evidence(self.store)]
        self.assertEqual(roles, ["user", "assistant"])

    def test_assistant_words_do_not_shape_the_card(self) -> None:
        """R1: only the user may add a taboo or a name to the card."""
        append_event(self.store, "user", "别叫我宝贝", STAMP)
        append_event(self.store, "assistant", "为什么你希望我别叫你宝贝？", STAMP)
        seal_store(self.store)
        view = build_persona_view(self.store, policy=Policy(now=NOW))
        payload = view.user_card.to_payload()
        names = [item["text"] for item in payload["address"]["never"]]
        self.assertEqual(names, ["宝贝"])

    def test_identity_is_unchanged_by_role(self) -> None:
        """R1: exposing role must not move the kid."""
        append_event(self.store, "user", "我叫老周", STAMP)
        seal_store(self.store)
        before = compile_kernel(self.store, Policy(now=NOW)).kid
        events = read_evidence(self.store)
        self.assertEqual(events[0].role, "user")
        self.assertEqual(compile_kernel(self.store, Policy(now=NOW)).kid, before)


if __name__ == "__main__":
    unittest.main()