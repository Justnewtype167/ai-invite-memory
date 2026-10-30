"""Q4: SubprocessProposer success, failure and timeout paths, never online."""

from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

from jian_kernel.errors import E_PROPOSER_FAILED, KernelError
from jian_kernel.proposer import LiveProposal, SubprocessProposer

SUCCESS = """
import json
import sys

request = json.loads(sys.stdin.readline())
reply = {
    "ok": True,
    "text": "收到负面经历时只确认，不评价情绪",
    "model": "fake-local",
    "quant": "Q4_K_M",
    "weights_sha": "9f8e7d6c",
    "temp_milli": 0,
    "seed": 7,
}
sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\\n")
"""

FAILURE = """
import json
import sys

sys.stdin.readline()
sys.stdout.write(json.dumps({"ok": False, "code": "E_PROPOSER_FAILED",
                            "message": "model exploded"}) + "\\n")
"""

TIMEOUT = """
import sys
import time

sys.stdin.readline()
time.sleep(3)
sys.stdout.write('{"ok": true}\\n')
"""


class TestSubprocessProposer(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_q4_"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _script(self, name: str, source: str) -> pathlib.Path:
        path = self.root / name
        path.write_text(source, encoding="utf-8")
        return path

    def test_success_path(self) -> None:
        """Q4: a fixed reply becomes a validated LiveProposal."""
        script = self._script("ok.py", SUCCESS)
        proposer = SubprocessProposer([sys.executable, str(script)], timeout=30)
        result = proposer.propose("self.conduct", "evidence text", "ab12cd34")
        print(
            f"Q4 success text={result.text} model={result.model} "
            f"seed={result.seed}"
        )
        self.assertIsInstance(result, LiveProposal)
        self.assertEqual(result.target, "self.conduct")
        self.assertEqual(result.prompt_sha, "ab12cd34")
        self.assertEqual(result.model, "fake-local")
        self.assertEqual(result.quant, "Q4_K_M")
        self.assertEqual(result.weights_sha, "9f8e7d6c")
        self.assertEqual(result.temp_milli, 0)
        self.assertEqual(result.seed, 7)

    def test_failure_path(self) -> None:
        """Q4: an ok=false reply raises E_PROPOSER_FAILED."""
        script = self._script("fail.py", FAILURE)
        proposer = SubprocessProposer([sys.executable, str(script)], timeout=30)
        with self.assertRaises(KernelError) as caught:
            proposer.propose("self.style", "evidence text", "ab12cd34")
        print(f"Q4 failure -> {caught.exception.code}")
        self.assertEqual(caught.exception.code, E_PROPOSER_FAILED)
        self.assertIn("model exploded", caught.exception.message)

    def test_timeout_path(self) -> None:
        """Q4: a slow proposer is killed and reported as E_PROPOSER_FAILED."""
        script = self._script("slow.py", TIMEOUT)
        proposer = SubprocessProposer([sys.executable, str(script)], timeout=1)
        with self.assertRaises(KernelError) as caught:
            proposer.propose("self.style", "evidence text", "ab12cd34")
        print(f"Q4 timeout -> {caught.exception.code}")
        self.assertEqual(caught.exception.code, E_PROPOSER_FAILED)
        self.assertIn("超时", caught.exception.message)


if __name__ == "__main__":
    unittest.main()
