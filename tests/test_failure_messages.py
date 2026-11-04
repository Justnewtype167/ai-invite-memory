"""D10: a model failure must tell the user what to do about it."""
from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.demo.engine import explain_failure, explain_unreachable


class TestFailureMessages(unittest.TestCase):
    def test_oom_points_at_memory_or_a_smaller_model(self) -> None:
        """D10: an allocation failure is a memory problem, not a mystery 500."""
        text = explain_failure(500, "cudaMalloc failed: out of memory")
        self.assertIn("内存", text)
        self.assertIn("更小的模型", text)

    def test_cpu_repack_oom_is_also_memory(self) -> None:
        """D10: the CPU path fails the same way and gets the same advice."""
        text = explain_failure(500, "failed to allocate CPU_REPACK buffer")
        self.assertIn("内存", text)

    def test_missing_model_says_pull(self) -> None:
        """D10: a missing model is user-fixable with one command."""
        self.assertIn("ollama pull", explain_failure(404, "model not found"))

    def test_unreachable_names_the_service(self) -> None:
        """D10: a refused connection is about Ollama not running."""
        text = explain_unreachable("http://127.0.0.1:11434", "Connection refused")
        self.assertIn("Ollama", text)
        self.assertIn("没有打开", text)

    def test_unknown_failure_still_reports_the_code(self) -> None:
        """D10: do not hide an unknown failure behind generic advice."""
        self.assertIn("418", explain_failure(418, "teapot"))


if __name__ == "__main__":
    unittest.main()
