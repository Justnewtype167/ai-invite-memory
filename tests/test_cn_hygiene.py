"""C5: zero model/network/third-party, no floats, deterministic output."""

from __future__ import annotations

import json
import pathlib
import re
import unittest
from datetime import date

import jian_cn
from jian_cn.kinship import parse_kinship
from jian_cn.normalize import normalize
from jian_cn.slang import explain
from jian_cn.timex import parse_time

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "jian_cn"
DATA = PKG / "data"

ALLOWED_IMPORTS = {
    "__future__", "argparse", "calendar", "dataclasses", "datetime",
    "json", "pathlib", "re", "sys", "unicodedata", "jian_cn",
}
FORBIDDEN_TOKENS = (
    "requests", "urllib", "socket", "http://", "https://", "openai",
    "anthropic", "jieba", "opencc", "pypinyin", "numpy", "pandas",
)


def _sources() -> list[pathlib.Path]:
    return sorted(PKG.glob("*.py"))


class TestHygiene(unittest.TestCase):
    def test_imports_are_stdlib_or_local(self) -> None:
        """C5: only standard library and jian_cn modules may be imported."""
        pattern = re.compile(r"(?m)^\s*(?:import|from)\s+([A-Za-z_][\w.]*)")
        found: set[str] = set()
        for path in _sources():
            text = path.read_text(encoding="utf-8")
            for name in pattern.findall(text):
                found.add(name.split(".")[0])
        self.assertEqual(found - ALLOWED_IMPORTS, set(), f"unexpected imports: {found}")

    def test_no_network_or_model_tokens(self) -> None:
        """C5: the package never mentions network or model clients."""
        for path in _sources():
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                for token in FORBIDDEN_TOKENS:
                    self.assertNotIn(token, text)

    def test_no_placeholders_or_randomness(self) -> None:
        """C5: no TODO/pass/NotImplementedError and no unseeded randomness."""
        for path in _sources():
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn("TODO", text)
                self.assertNotIn("NotImplementedError", text)
                self.assertNotIn("import random", text)
                self.assertNotIn("datetime.now", text)

    def test_json_has_no_float(self) -> None:
        """C5: every data file parses with floats rejected."""

        def reject(value: str) -> None:
            raise AssertionError(f"float literal found: {value}")

        for path in sorted(DATA.glob("*.json")):
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                self.assertNotEqual(raw[:1], b"\xef", "BOM not allowed")
                self.assertNotIn(b"\r", raw, "CRLF not allowed")
                json.loads(raw.decode("utf-8"), parse_float=reject)

    def test_output_is_deterministic(self) -> None:
        """C5: two runs produce identical bytes."""
        runs = []
        for _ in range(2):
            payload = {
                "norm": normalize("臺灣裏面  ＡＢＣ"),
                "kinship": parse_kinship("我爸的弟弟的女儿").to_dict(),
                "timex": parse_time("大前天", "2026-10-29T10:00:00+08:00").to_dict(),
                "slang": explain("yyds", date(2026, 6, 1)),
            }
            runs.append(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        self.assertEqual(runs[0], runs[1])

    def test_public_api_is_exported(self) -> None:
        """C5: the package exposes its public functions."""
        for name in ("normalize", "parse_kinship", "parse_time", "usable"):
            self.assertTrue(hasattr(jian_cn, name), name)


if __name__ == "__main__":
    unittest.main()
