"""K5: every entry must trace to evidence; proposals are validated."""

from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import kn_fixtures

from aiinvite.kernel.errors import E_KN_IO, E_KN_UNSOURCED, KernelError
from aiinvite.kernel.compiler import compile_kernel
from aiinvite.kernel.kernel import Policy
from aiinvite.kernel.proposer import NullProposer, Proposal, ReplayProposer

NOW = "2026-10-29T10:00:00+08:00"


class FixedProposer:
    """A deterministic proposer used only by tests."""

    def __init__(self, proposals: list[Proposal]) -> None:
        self._proposals = proposals

    def propose(self, store: pathlib.Path, policy: Policy) -> list[Proposal]:
        """Return the fixed proposal list."""
        return list(self._proposals)


class TestSources(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_kn_src_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        kn_fixtures.write_store(self.root, [
            ("2026-01-01T09:00:00Z", "今天天气不错", "turn", None),
            ("2026-01-02T09:00:00Z", "以后不许半夜打电话", "directive", "lock"),
        ])
        self.policy = Policy(now=NOW)

    def test_empty_evidence_is_unsourced(self) -> None:
        """K5: a proposal with no evidence raises E_KN_UNSOURCED."""
        proposer = FixedProposer([Proposal("没有出处的条目", ())])
        with self.assertRaises(KernelError) as caught:
            compile_kernel(self.root, self.policy, proposer)
        print(f"K5 empty={caught.exception.code}")
        self.assertEqual(caught.exception.code, E_KN_UNSOURCED)

    def test_missing_event_is_unsourced(self) -> None:
        """K5: evidence pointing at an absent event raises E_KN_UNSOURCED."""
        proposer = FixedProposer([Proposal("假出处", ("ev_999999",))])
        with self.assertRaises(KernelError) as caught:
            compile_kernel(self.root, self.policy, proposer)
        self.assertEqual(caught.exception.code, E_KN_UNSOURCED)
        self.assertIn("ev_999999", caught.exception.message)

    def test_sourced_proposal_is_accepted(self) -> None:
        """K5: a sourced proposal adds one canon entry."""
        proposer = FixedProposer([Proposal("备注条目", ("ev_000001",))])
        kernel = compile_kernel(self.root, self.policy, proposer)
        notes = [entry for entry in kernel.canon if entry.kind == "note"]
        print(f"K5 notes={len(notes)} evidence={notes[0].evidence}")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].evidence, ("ev_000001",))
        baseline = compile_kernel(self.root, self.policy, NullProposer())
        self.assertNotEqual(kernel.kid, baseline.kid)

    def test_replay_proposer(self) -> None:
        """K5: replayed proposals behave exactly like direct proposals."""
        path = self.root / "proposals.jsonl"
        path.write_bytes(
            b'{"evidence":["ev_000001"],"kind":"note","text":"\xe5\xa4\x87\xe6\xb3\xa8"}\n'
        )
        replayed = compile_kernel(self.root, self.policy, ReplayProposer(path))
        direct = compile_kernel(
            self.root, self.policy, FixedProposer([Proposal("备注", ("ev_000001",))])
        )
        self.assertEqual(replayed.kid, direct.kid)

    def test_replay_rejects_bad_lines(self) -> None:
        """K5: a malformed replay file raises E_KN_IO."""
        path = self.root / "proposals.jsonl"
        path.write_text("{not json}\n", encoding="utf-8")
        with self.assertRaises(KernelError) as caught:
            compile_kernel(self.root, self.policy, ReplayProposer(path))
        self.assertEqual(caught.exception.code, E_KN_IO)

    def test_unknown_event_type_is_io(self) -> None:
        """K5: evidence with an unsupported type raises E_KN_IO."""
        bad = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_kn_bad_"))
        self.addCleanup(shutil.rmtree, bad, True)
        kn_fixtures.write_store(bad, [
            ("2026-01-01T09:00:00Z", "测试", "unknown", None),
        ])
        with self.assertRaises(KernelError) as caught:
            compile_kernel(bad, self.policy)
        self.assertEqual(caught.exception.code, E_KN_IO)


if __name__ == "__main__":
    unittest.main()
