"""K2: deleting the derived kernel and re-recording reproduces kid and version."""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import kn_fixtures

from aiinvite.kernel.compiler import compile_kernel
from aiinvite.kernel.history import history, record_kernel, restore
from aiinvite.kernel.kernel import Policy

NOW = "2026-10-29T10:00:00+08:00"


class TestDeterminism(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_kn_det_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        events = kn_fixtures.directives(5) + [
            ("2026-01-06T09:00:00Z", "今天天气不错", "turn", None),
        ]
        kn_fixtures.write_store(self.root, events)

    def test_rerun_after_delete_keeps_kid_and_version(self) -> None:
        """K2: delete kernel/, record again, kid and version stay the same."""
        policy = Policy(now=NOW)
        first = record_kernel(self.root, policy)
        kernel = compile_kernel(self.root, policy)
        meta = json.loads((self.root / "kernel" / "META.json").read_text("utf-8"))
        self.assertEqual(meta["generation"], 0)
        self.assertEqual(meta["compiler_version"], "0.4")

        shutil.rmtree(self.root / "kernel")
        again = record_kernel(self.root, policy)
        print(
            f"K2 first=({first.version},{first.kid[:12]}) "
            f"again=({again.version},{again.kid[:12]})"
        )
        self.assertEqual(again.kid, first.kid)
        self.assertEqual(again.version, first.version)
        self.assertEqual(again.version, 1)

        rebuilt = compile_kernel(self.root, policy)
        self.assertEqual(rebuilt.kid, kernel.kid)
        self.assertEqual(rebuilt.files(1), kernel.files(1))

        entries = history(self.root)
        self.assertEqual(len(entries), 1)
        self.assertEqual(restore(self.root, 1).kid, entries[0].kid)

    def test_version_is_not_part_of_kid(self) -> None:
        """K2: the same content under two ledger positions has one kid."""
        policy = Policy(now=NOW)
        result = record_kernel(self.root, policy)
        same = record_kernel(self.root, policy)
        self.assertEqual(same.kid, result.kid)
        self.assertEqual(same.version, result.version)
        self.assertFalse(same.written)


if __name__ == "__main__":
    unittest.main()
