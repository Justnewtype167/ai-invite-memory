"""P4: the three origins are distinct, and fallback changes the kid."""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import kn_fixtures

from jian_kernel.compiler import compile_kernel
from jian_kernel.history import history, record_kernel, restore, verify_kernel
from jian_kernel.kernel import (
    ORIGIN_RULE_FALLBACK,
    ORIGIN_RULE_ONLY,
    ORIGIN_WITH_PROPOSALS,
    Policy,
)
from jian_kernel.proposer import record_proposal

NOW = "2026-10-29T10:00:00+08:00"
STAMP = "2026-10-29T02:00:00Z"
EVENTS = [
    ("2026-01-01T09:00:00Z", "今天天气不错", "turn", None),
    ("2026-01-02T09:00:00Z", "以后不许半夜打电话", "directive", "lock"),
    *kn_fixtures.chat_turns(9),
]


class TestFallback(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(self._cleanup)
        self.stores: list[pathlib.Path] = []

    def _cleanup(self) -> None:
        for store in self.stores:
            shutil.rmtree(store, True)

    def _store(self, with_proposal: bool) -> pathlib.Path:
        store = pathlib.Path(tempfile.mkdtemp(prefix="jian_prop_fb_"))
        self.stores.append(store)
        kn_fixtures.write_store(store, EVENTS)
        if with_proposal:
            record_proposal(
                store, "self.style", "说话时偶尔停顿", "deepseek-v4", "ab12cd34",
                STAMP,
            )
        return store

    def test_three_origins_have_three_kids(self) -> None:
        """P4: rule_only, with_proposals and rule_fallback are distinct kids."""
        plain = self._store(False)
        with_prop = self._store(True)
        kid_rule = compile_kernel(plain, Policy(now=NOW)).kid
        kid_proposal = compile_kernel(with_prop, Policy(now=NOW)).kid
        result = record_kernel(
            plain, Policy(now=NOW, require_proposals=True), allow_fallback=True
        )
        kid_fallback = result.kid
        print(
            f"P4 rule_only={kid_rule[:12]} with_proposals={kid_proposal[:12]} "
            f"rule_fallback={kid_fallback[:12]}"
        )
        self.assertEqual(result.origin, ORIGIN_RULE_FALLBACK)
        meta = json.loads((plain / "kernel" / "META.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["origin"], ORIGIN_RULE_FALLBACK)
        self.assertEqual(history(plain)[-1].origin, ORIGIN_RULE_FALLBACK)
        self.assertEqual(kid_rule,
                         compile_kernel(plain, Policy(now=NOW)).kid)
        self.assertNotEqual(kid_rule, kid_fallback)
        self.assertNotEqual(kid_proposal, kid_fallback)
        self.assertNotEqual(kid_rule, kid_proposal)
        self.assertEqual(compile_kernel(with_prop, Policy(now=NOW)).origin,
                         ORIGIN_WITH_PROPOSALS)
        self.assertEqual(compile_kernel(self._store(False), Policy(now=NOW)).origin,
                         ORIGIN_RULE_ONLY)

    def test_fallback_record_verifies_and_restores(self) -> None:
        """P4: verify and restore rebuild the same policy from the origin."""
        store = self._store(False)
        result = record_kernel(
            store, Policy(now=NOW, require_proposals=True), allow_fallback=True
        )
        report = verify_kernel(store)
        print(f"P4 verify kid={report.kid[:12]} version={report.version}")
        self.assertEqual(report.kid, result.kid)
        self.assertEqual(restore(store, 1).kid, result.kid)


if __name__ == "__main__":
    unittest.main()
