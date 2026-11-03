"""P1: every data file a package ships must be declared in pyproject."""
from __future__ import annotations

import fnmatch
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def declared_patterns() -> dict[str, list[str]]:
    """Return {package: [patterns]} from the pyproject package-data table."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"\[tool\.setuptools\.package-data\](.*)", text, re.S)
    if block is None:
        return {}
    table = {}
    for line in block.group(1).splitlines():
        match = re.match(r'\s*"([^"]+)"\s*=\s*\[(.*)\]\s*$', line)
        if not match:
            continue
        table[match.group(1)] = re.findall(r'"([^"]+)"', match.group(2))
    return table


class TestPackaging(unittest.TestCase):
    def test_every_data_file_is_declared(self) -> None:
        """P1: a data file not matched by any pattern is invisible after install."""
        table = declared_patterns()
        self.assertTrue(table, "package-data table missing")
        missing = []
        for package_dir in sorted((ROOT / "aiinvite").iterdir()):
            data = package_dir / "data"
            if not data.is_dir():
                continue
            key = "aiinvite." + package_dir.name
            patterns = table.get(key)
            if patterns is None:
                for path in data.iterdir():
                    missing.append(f"{key}: {path.name} (package has no entry)")
                continue
            for path in sorted(data.iterdir()):
                if path.is_dir():
                    continue
                if not any(fnmatch.fnmatch(path.name, pat.split("/")[-1]) for pat in patterns):
                    missing.append(f"{key}: {path.name} <- {patterns}")
        self.assertEqual(missing, [], "undeclared data files: " + "; ".join(missing))


if __name__ == "__main__":
    unittest.main()
