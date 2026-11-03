"""V1: the advertised version must be the packaged version."""
from __future__ import annotations

import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import aiinvite


class TestVersion(unittest.TestCase):
    def test_version_matches_pyproject(self) -> None:
        """V1: __version__ equals the version declared in pyproject.toml."""
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        declared = re.search(r'^version = "([^"]+)"', text, re.M)
        self.assertIsNotNone(declared)
        self.assertEqual(aiinvite.__version__, declared.group(1))


if __name__ == "__main__":
    unittest.main()
