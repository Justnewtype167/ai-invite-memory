"""Q2: self.style and self.conduct render as two sections with distinct kids."""

from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import kn_fixtures

from jian_kernel.compiler import compile_kernel
from jian_kernel.kernel import ORIGIN_WITH_PROPOSALS, Policy
from jian_kernel.proposer import record_proposal

NOW = "2026-10-29T10:00:00+08:00"
STAMP = "2026-10-29T02:00:00Z"
STYLE_TEXT = "回答前先停半秒"
CONDUCT_TEXT = "收到负面经历时只确认，不评价情绪"


class TestTwoTargets(unittest.TestCase):
    def setUp(self) -> None:
        self.stores: list[pathlib.Path] = []
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        for store in self.stores:
            shutil.rmtree(store, True)

    def _store(self, style: bool, conduct: bool) -> pathlib.Path:
        store = pathlib.Path(tempfile.mkdtemp(prefix="jian_q2_"))
        self.stores.append(store)
        kn_fixtures.write_store(store, kn_fixtures.chat_turns(10))
        if style:
            record_proposal(store, "self.style", STYLE_TEXT, "m", "ab12cd34", STAMP)
        if conduct:
            record_proposal(store, "self.conduct", CONDUCT_TEXT, "m", "ab12cd34", STAMP)
        return store

    def test_two_sections_and_three_kids(self) -> None:
        """Q2: both targets render as separate sections and kids all differ."""
        both = compile_kernel(self._store(True, True), Policy(now=NOW))
        style_only = compile_kernel(self._store(True, False), Policy(now=NOW))
        conduct_only = compile_kernel(self._store(False, True), Policy(now=NOW))
        print(
            f"Q2 both={both.kid[:12]} style={style_only.kid[:12]} "
            f"conduct={conduct_only.kid[:12]}"
        )
        self.assertEqual(both.origin, ORIGIN_WITH_PROPOSALS)
        self.assertIn("## Style", both.self_md)
        self.assertIn(STYLE_TEXT, both.self_md)
        self.assertIn("## Conduct", both.self_md)
        self.assertIn(CONDUCT_TEXT, both.self_md)
        self.assertEqual(len(both.style), 2)
        self.assertNotEqual(both.kid, style_only.kid)
        self.assertNotEqual(both.kid, conduct_only.kid)
        self.assertNotEqual(style_only.kid, conduct_only.kid)


if __name__ == "__main__":
    unittest.main()
