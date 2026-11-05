"""X1-X6: memory must be portable while the companion is still talking."""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.capsule import (
    append_event,
    import_capsule,
    init_store,
    seal_store,
    snapshot_capsule,
    verify_path,
)
from aiinvite.kernel.compiler import compile_kernel
from aiinvite.kernel.kernel import Policy
from aiinvite.persona.pins import derive_pins
from aiinvite.host import HostSession

STAMP = "2026-11-01T09:00:00+08:00"
NOW = "2026-11-01T12:00:00+08:00"


class TestSnapshot(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="snapshot_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "m"
        init_store(self.store)
        append_event(self.store, "user", "我叫老周", STAMP)
        append_event(self.store, "assistant", "记住了", STAMP)
        self.fact = append_event(self.store, "user", "我的狗叫阿黄，它去年走了", STAMP)
        self.capsule = self.root / "backup.aiem"

    def test_x1_the_original_keeps_working(self) -> None:
        """X1: exporting a snapshot never freezes the live store."""
        before = compile_kernel(self.store, Policy(now=NOW)).kid
        snapshot_capsule(self.store, self.capsule)
        after = compile_kernel(self.store, Policy(now=NOW)).kid
        self.assertEqual(before, after)
        append_event(self.store, "user", "我还在", STAMP)
        grown = compile_kernel(self.store, Policy(now=NOW)).kid
        self.assertNotEqual(after, grown)

    def test_x2_the_capsule_verifies(self) -> None:
        """X2: the exported file is a valid, sealed capsule."""
        exported = snapshot_capsule(self.store, self.capsule)
        result = verify_path(self.capsule)
        self.assertEqual(result.events, exported.events)
        self.assertEqual(result.head, exported.head)

    def test_x3_the_kid_survives_the_move(self) -> None:
        """X3: the same memory on another machine is the same companion."""
        exported = snapshot_capsule(self.store, self.capsule)
        moved = self.root / "other-machine"
        import_capsule(self.capsule, moved)
        mine = compile_kernel(self.store, Policy(now=NOW))
        theirs = compile_kernel(moved, Policy(now=NOW))
        self.assertEqual(mine.kid, theirs.kid)
        self.assertEqual(mine.kid, exported.head and mine.kid)

    def test_x4_the_card_and_pins_survive(self) -> None:
        """X4: what the companion remembers about you travels too."""
        session = HostSession(self.store, "glm4:9b", now=NOW)
        session.pin(self.fact)
        mine = derive_pins(session._events())
        snapshot_capsule(self.store, self.capsule)
        moved = self.root / "other-machine-2"
        import_capsule(self.capsule, moved)
        theirs = derive_pins(HostSession(moved, "glm4:9b", now=NOW)._events())
        self.assertEqual([p.text for p in mine], [p.text for p in theirs])

    def test_x5_derived_data_is_not_shipped(self) -> None:
        """X5: the index and the clues are rebuilt, never carried."""
        HostSession(self.store, "glm4:9b", now=NOW).prompt_for("在吗")
        self.assertTrue((self.store / ".index").exists())
        snapshot_capsule(self.store, self.capsule)
        moved = self.root / "other-machine-3"
        import_capsule(self.capsule, moved)
        self.assertFalse((moved / ".index").exists())
        self.assertFalse((moved / ".clues").exists())

    def test_x6_import_refuses_a_live_store(self) -> None:
        """X6: importing must never merge into or overwrite existing memory."""
        snapshot_capsule(self.store, self.capsule)
        with self.assertRaises(Exception):
            import_capsule(self.capsule, self.store)


if __name__ == "__main__":
    unittest.main()
