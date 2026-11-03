# -*- coding: utf-8 -*-
"""D8: an unknown option must never become a directory name."""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.demo import app


class TestOptions(unittest.TestCase):
    def test_help_prints_usage_and_creates_nothing(self) -> None:
        """D8: --help returns without touching the filesystem."""
        before = set(pathlib.Path.cwd().iterdir())
        with self.assertRaises(SystemExit) as caught:
            app.main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        after = set(pathlib.Path.cwd().iterdir())
        self.assertEqual(before, after)

    def test_unknown_option_is_rejected(self) -> None:
        """D8: a typo is an error, not a store called --nope."""
        with self.assertRaises(SystemExit):
            app.main(["--nope"])

    def test_store_flag_is_parsed(self) -> None:
        """D8: --store is understood so the window can be pointed anywhere."""
        root = pathlib.Path(tempfile.mkdtemp(prefix="opt_"))
        parsed = app.parse_args(["--store", str(root), "--model", "glm4:9b"])
        self.assertEqual(parsed[0], root)
        self.assertEqual(parsed[1], "glm4:9b")


if __name__ == "__main__":
    unittest.main()