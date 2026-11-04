# -*- coding: utf-8 -*-
"""C3: a later taboo must not erase an earlier, valid form of address."""
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


class TestEarlierName(unittest.TestCase):
    def _card(self, lines):
        root = pathlib.Path(tempfile.mkdtemp(prefix="earlier_"))
        self.addCleanup(shutil.rmtree, root, True)
        store = root / "m"
        init_store(store)
        for index, text in enumerate(lines):
            append_event(store, "user", text, f"2026-11-0{index + 1}T09:00:00+08:00")
        seal_store(store)
        view = build_persona_view(store, policy=Policy(now="2026-11-01T10:00:00+08:00"))
        return view.user_card.to_payload()["address"]

    def test_later_taboo_keeps_the_earlier_name(self) -> None:
        """C3: "叫我老周" then "叫我一声宝贝" leaves 老周, not empty."""
        address = self._card(["我叫老周，别叫我宝贝", "叫我一声宝贝"])
        self.assertEqual(address["call"], "老周")
        names = [item["text"] for item in address["never"]]
        self.assertIn("宝贝", names)


if __name__ == "__main__":
    unittest.main()