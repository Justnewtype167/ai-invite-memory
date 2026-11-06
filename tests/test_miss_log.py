"""M1-M4: the miss log is the honest input for improving recall."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STAMP = "2026-11-01T09:00:00+08:00"
NOW = "2026-11-01T12:00:00+08:00"


class TestMissLog(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="miss_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = self.root / "appdata"
        self.home.mkdir()
        self.saved = os.environ.get("APPDATA")
        os.environ["APPDATA"] = str(self.home)
        self.addCleanup(self._restore)

        from aiinvite.demo.engine import DemoEngine

        self.engine = DemoEngine(
            self.root / "m", caller=lambda prompt, model: "好", now=NOW,
        )

    def _restore(self) -> None:
        if self.saved is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self.saved

    def _lines(self):
        from aiinvite.demo.engine import misses_path

        path = misses_path()
        if not path.is_file():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_m1_records_question_and_expectation(self) -> None:
        """M1: one line holds the question and what should have been recalled."""
        self.engine.send("你还记得那件难过的事吗")
        self.engine.record_miss("我的狗阿黄去年走了")
        lines = self._lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["question"], "你还记得那件难过的事吗")
        self.assertEqual(lines[0]["expected"], "我的狗阿黄去年走了")

    def test_m2_appends_instead_of_overwriting(self) -> None:
        """M2: every miss accumulates; nothing is lost."""
        self.engine.send("第一句")
        self.engine.record_miss("甲")
        self.engine.send("第二句")
        self.engine.record_miss("乙")
        self.assertEqual([line["expected"] for line in self._lines()], ["甲", "乙"])

    def test_m3_empty_expectation_is_rejected(self) -> None:
        """M3: a blank line teaches nothing, so it is refused."""
        from aiinvite.demo.engine import EngineError

        with self.assertRaises(EngineError):
            self.engine.record_miss("   ")

    def test_m4_records_what_was_actually_recalled(self) -> None:
        """M4: the log shows what it did recall, so the gap is visible."""
        self.engine.send("在吗")
        self.engine.record_miss("某个回忆")
        line = self._lines()[0]
        self.assertIsInstance(line["recalled"], list)
        self.assertIn("model", line)


if __name__ == "__main__":
    unittest.main()
