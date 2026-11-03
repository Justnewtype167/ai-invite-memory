"""P3: a required proposal is never silently replaced by rules."""

from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import kn_fixtures

from aiinvite.kernel.errors import E_KN_NO_PROPOSAL, KernelError
from aiinvite.kernel.compiler import compile_kernel
from aiinvite.kernel.history import record_kernel
from aiinvite.kernel.kernel import Policy

NOW = "2026-10-29T10:00:00+08:00"


class TestProposalRequired(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_prop_req_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        kn_fixtures.write_store(self.root, [
            ("2026-01-01T09:00:00Z", "今天天气不错", "turn", None),
        ])

    def test_compile_without_proposal_is_refused(self) -> None:
        """P3: require_proposals without --allow-fallback raises the fixed code."""
        with self.assertRaises(KernelError) as caught:
            compile_kernel(self.root, Policy(now=NOW, require_proposals=True))
        print(f"P3 compile -> {caught.exception.code}")
        self.assertEqual(caught.exception.code, E_KN_NO_PROPOSAL)
        self.assertIn("--allow-fallback", caught.exception.message)

    def test_record_without_proposal_writes_nothing(self) -> None:
        """P3: the refusal happens before any kernel byte is written."""
        with self.assertRaises(KernelError) as caught:
            record_kernel(
                self.root, Policy(now=NOW, require_proposals=True), force=False
            )
        print(f"P3 record -> {caught.exception.code}")
        self.assertEqual(caught.exception.code, E_KN_NO_PROPOSAL)
        self.assertEqual(kn_fixtures.snapshot(self.root), {})


if __name__ == "__main__":
    unittest.main()
