"""P2: a proposal changes ``self.md`` only; canon, state and graph stay put."""

from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import kn_fixtures

from jian_kernel.compiler import compile_kernel
from jian_kernel.kernel import ORIGIN_RULE_ONLY, ORIGIN_WITH_PROPOSALS, Policy
from jian_kernel.proposer import record_proposal

NOW = "2026-10-29T10:00:00+08:00"
STAMP = "2026-10-29T02:00:00Z"
STYLE_TEXT = "说话时偶尔停顿，不急着给结论"


class TestProposalEffect(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_prop_eff_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        kn_fixtures.write_store(self.root, [
            ("2026-01-01T09:00:00Z", "今天天气不错", "turn", None),
            ("2026-01-02T09:00:00Z", "以后不许半夜打电话", "directive", "lock"),
        ])
        self.policy = Policy(now=NOW)

    def test_style_changes_but_canon_state_graph_do_not(self) -> None:
        """P2: only the style section changes, so the kid changes."""
        before = compile_kernel(self.root, self.policy)
        record_proposal(
            self.root, "self.style", STYLE_TEXT, "deepseek-v4", "ab12cd34", STAMP
        )
        after = compile_kernel(self.root, self.policy)
        print(
            f"P2 kid_before={before.kid[:12]} kid_after={after.kid[:12]} "
            f"origin={after.origin} style={len(after.style)}"
        )
        self.assertEqual(before.origin, ORIGIN_RULE_ONLY)
        self.assertEqual(after.origin, ORIGIN_WITH_PROPOSALS)
        self.assertEqual(before.canon, after.canon)
        self.assertEqual(before.state, after.state)
        self.assertEqual(before.edges, after.edges)
        self.assertEqual(before.anchors, after.anchors)
        self.assertEqual(before.canon_md, after.canon_md)
        self.assertNotEqual(before.self_md, after.self_md)
        self.assertIn("## Style", after.self_md)
        self.assertIn(STYLE_TEXT, after.self_md)
        self.assertEqual(after.style, (STYLE_TEXT,))
        self.assertNotEqual(before.kid, after.kid)

    def test_promise_like_proposal_stays_out_of_canon(self) -> None:
        """P2: a proposal that reads like a promise must not enter canon."""
        before = compile_kernel(self.root, self.policy)
        record_proposal(
            self.root, "self.style", "我答应你以后会先听你说完", "m", "ab12cd34", STAMP
        )
        after = compile_kernel(self.root, self.policy)
        self.assertNotIn("promise", [entry.kind for entry in after.canon])
        self.assertEqual(before.canon, after.canon)
        self.assertEqual(before.state, after.state)


if __name__ == "__main__":
    unittest.main()
