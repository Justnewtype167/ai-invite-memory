"""K3: the four gates fire, and a failed gate leaves kernel/ byte-identical."""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import kn_fixtures

from aiinvite.kernel.errors import (
    E_KN_GATE_CANON,
    E_KN_GATE_DELTA,
    E_KN_GATE_STATE,
    E_KN_STALE,
    KernelError,
)
from aiinvite.kernel.history import history, record_kernel, verify_kernel
from aiinvite.kernel.kernel import Policy

NOW = "2026-10-29T10:00:00+08:00"


class TestGate(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_kn_gate_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.policy = Policy(now=NOW)

    def _expect(self, code: str, before: dict[str, bytes]) -> None:
        with self.assertRaises(KernelError) as caught:
            record_kernel(self.root, self.policy)
        after = kn_fixtures.snapshot(self.root)
        print(f"K3 gate={code} unchanged={after == before}")
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(after, before, "gate failure must not touch kernel/")

    def test_disk_edit_is_refused_as_stale(self) -> None:
        """K3-1: an edited canon.md is a disk edit, so E_KN_STALE fires."""
        kn_fixtures.write_store(self.root, kn_fixtures.directives(5))
        record_kernel(self.root, self.policy)
        before = kn_fixtures.snapshot(self.root)
        path = self.root / "kernel" / "canon.md"
        text = path.read_text(encoding="utf-8")
        path.write_bytes(
            text.encode("utf-8")
            + b'- {"evidence":["ev_000001"],"kind":"note","text":"hand"}\n'
        )
        tampered = kn_fixtures.snapshot(self.root)
        self.assertNotEqual(tampered, before)
        self._expect(E_KN_STALE, tampered)

    def test_canon_gate_rejects_evidence_change(self) -> None:
        """K3-1: new evidence may not change canon without a new directive."""
        kn_fixtures.write_store(self.root, kn_fixtures.directives(5))
        record_kernel(self.root, self.policy)
        before = kn_fixtures.snapshot(self.root)
        kn_fixtures.append_events(self.root, [
            ("2026-06-01T09:00:00Z", "答应周末陪你去公园", "turn", None),
        ])
        self._expect(E_KN_GATE_CANON, before)

    def test_force_heals_a_hand_edit(self) -> None:
        """K3-1: --force rewrites the kernel and appends one audit line."""
        kn_fixtures.write_store(self.root, kn_fixtures.directives(5))
        record_kernel(self.root, self.policy)
        clean = kn_fixtures.snapshot(self.root)
        path = self.root / "kernel" / "canon.md"
        path.write_bytes(
            path.read_text(encoding="utf-8").encode("utf-8")
            + b'- {"evidence":["ev_000001"],"kind":"note","text":"hand"}\n'
        )
        tampered = kn_fixtures.snapshot(self.root)
        self.assertNotEqual(tampered, clean)
        result = record_kernel(self.root, self.policy, force=True)
        healed = kn_fixtures.snapshot(self.root)
        body = ("canon.md", "self.md", "state.json", "graph.json")
        same = all(healed[name] == clean[name] for name in body)
        print(f"K3 heal healed={result.healed} written={result.written} "
              f"restored={same}")
        self.assertTrue(result.healed)
        self.assertTrue(healed["HISTORY.jsonl"].startswith(clean["HISTORY.jsonl"]))
        self.assertFalse(result.written)
        self.assertEqual(result.version, 1)
        self.assertEqual(len(history(self.root)), 1)
        lines = (self.root / "kernel" / "HISTORY.jsonl").read_bytes().splitlines()
        audit = json.loads(lines[-1])
        self.assertEqual(audit["event"], "tamper_healed")
        self.assertEqual(audit["kid"], result.kid)
        self.assertEqual(audit["version"], 1)
        self.assertNotEqual(audit["found"], result.kid)
        for name in ("canon.md", "self.md", "state.json", "graph.json"):
            self.assertEqual(healed[name], clean[name])
        self.assertEqual(verify_kernel(self.root).kid, result.kid)

    def test_delta_gate_rejects_large_change(self) -> None:
        """K3-2: one new directive against one entry exceeds the delta limit."""
        kn_fixtures.write_store(self.root, kn_fixtures.directives(1))
        record_kernel(self.root, self.policy)
        before = kn_fixtures.snapshot(self.root)
        kn_fixtures.append_events(self.root, [
            ("2026-06-01T09:00:00Z", "规则二不许熬夜", "directive", "lock"),
        ])
        self._expect(E_KN_GATE_DELTA, before)

    def test_state_gate_rejects_jump(self) -> None:
        """K3-3: ten corrections move trust by 500, above the 200 limit."""
        kn_fixtures.write_store(self.root, kn_fixtures.directives(5))
        record_kernel(self.root, self.policy)
        before = kn_fixtures.snapshot(self.root)
        events = [
            (f"2026-06-{index:02d}T09:00:00Z", "你记错了", "feedback", "correction")
            for index in range(1, 11)
        ]
        kn_fixtures.append_events(self.root, events)
        self._expect(E_KN_GATE_STATE, before)

    def test_bootstrap_is_not_gated(self) -> None:
        """K3: the first record has no previous version to compare with."""
        kn_fixtures.write_store(self.root, kn_fixtures.directives(5))
        result = record_kernel(self.root, self.policy)
        self.assertTrue(result.written)
        self.assertEqual(result.version, 1)
        self.assertGreaterEqual(result.delta.added, 5)


if __name__ == "__main__":
    unittest.main()
