"""T5: the same reply files must produce a byte-identical report."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pcs_fixtures

from jian_pcs.probes import load_probes

ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestDeterminism(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_pcs_t5_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        probes = load_probes()
        self.a = self._write("a.jsonl", probes, 20)
        self.b = self._write("b.jsonl", probes, 15)

    def _write(self, name: str, probes, pass_count: int) -> pathlib.Path:
        path = self.root / name
        lines = []
        for index, probe in enumerate(probes):
            lines.append(json.dumps({
                "probe_id": probe.probe_id,
                "model": "scripted",
                "seed": 42,
                "temp_milli": 0,
                "text": pcs_fixtures.reply_for(probe.rule, index < pass_count),
            }, ensure_ascii=False))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _run(self) -> str:
        completed = subprocess.run(
            [sys.executable, "-m", "jian_pcs.cli", "pcs",
             "--a", str(self.a), "--b", str(self.b)],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONUTF8": "1"},
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout

    def test_report_is_byte_identical(self) -> None:
        """T5: two runs over the same inputs yield identical stdout bytes."""
        first = self._run()
        second = self._run()
        print(f"T5 bytes={len(first.encode('utf-8'))} identical={first == second}")
        self.assertEqual(first, second)
        for label in ("C(a)", "C(b)", "A(a,b)", "PCS"):
            self.assertIn(label, first)


if __name__ == "__main__":
    unittest.main()
