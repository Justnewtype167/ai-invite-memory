# -*- coding: utf-8 -*-
"""D7: a second launch opens the same memory instead of failing."""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.demo.engine import DemoEngine


class TestRelaunch(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="demo_relaunch_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "memory"

    def test_second_launch_reuses_the_store(self) -> None:
        """D7: opening the window twice must not raise on existing evidence."""
        first = DemoEngine(self.store, caller=lambda p, m: "好")
        first.send("我叫老周")
        kid = first.current_kid()

        second = DemoEngine(self.store, caller=lambda p, m: "好")
        self.assertEqual(second.current_kid(), kid)
        self.assertIn("老周", second.snapshot()["card"])

    def test_empty_dir_is_initialised(self) -> None:
        """D7: a first run creates the store."""
        DemoEngine(self.store, caller=lambda p, m: "好")
        self.assertTrue((self.store / "chain.json").is_file())


if __name__ == "__main__":
    unittest.main()