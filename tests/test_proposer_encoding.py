"""Proposer stdio is UTF-8 on every locale (M38)."""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.kernel.proposer import SubprocessProposer

PROBE = """
import json
import sys

request = json.loads(sys.stdin.readline())
reply = {
    "ok": True,
    "text": "in=%s out=%s echo=%s" % (sys.stdin.encoding, sys.stdout.encoding, request["evidence"]),
    "model": "probe",
    "quant": "Q4_K_M",
    "weights_sha": "9f8e7d6c",
    "temp_milli": 0,
    "seed": 7,
}
sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\\n")
"""


class TestProposerEncoding(unittest.TestCase):
    """E1-E2: the child is told UTF-8, and Chinese survives the round trip."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="proposer_enc_"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _proposer(self) -> SubprocessProposer:
        script = self.root / "probe.py"
        script.write_text(PROBE, encoding="utf-8")
        return SubprocessProposer([sys.executable, str(script)], timeout=60)

    def test_e1_child_stdio_is_utf8(self) -> None:
        """E1: without this the child writes cp936 and the parent decodes U+FFFD."""
        result = self._proposer().propose("self.conduct", "evidence", "ab12cd34")
        self.assertIn("in=utf-8", result.text.lower())
        self.assertIn("out=utf-8", result.text.lower())

    def test_e2_chinese_survives(self) -> None:
        """E2: a real Chinese proposal comes back byte-identical."""
        text = "收到负面经历时只确认，不评价情绪"
        result = self._proposer().propose("self.conduct", text, "ab12cd34")
        self.assertIn("echo=" + text, result.text)
        self.assertNotIn("\\ufffd", result.text)


if __name__ == "__main__":
    unittest.main()
