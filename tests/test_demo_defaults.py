# -*- coding: utf-8 -*-
"""D6: the window must open a persistent store, not a temp one."""
from __future__ import annotations

import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.demo.engine import DEFAULT_MODEL, default_store, scratch_store


class TestDefaultStore(unittest.TestCase):
    def test_default_store_is_persistent(self) -> None:
        """D6: the default store lives under the user data dir, not in temp."""
        store = default_store()
        self.assertEqual(store.name, "memory")
        self.assertIn("AIInvite", str(store))
        temp = pathlib.Path(os.environ.get("TEMP") or tempfile_dir())
        self.assertNotIn(str(temp), str(store))

    def test_scratch_store_is_throwaway(self) -> None:
        """D6: the test helper still returns a temp path."""
        self.assertNotEqual(scratch_store(), scratch_store())

    def test_default_model_is_local(self) -> None:
        """D6: the window opens on the local model the user installed."""
        self.assertEqual(DEFAULT_MODEL, "glm4:9b")


def tempfile_dir() -> str:
    import tempfile

    return tempfile.gettempdir()


if __name__ == "__main__":
    unittest.main()