"""P6: proposal replay is deterministic across processes and hash seeds."""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import kn_fixtures

from jian_kernel.proposer import record_proposal

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOW = "2026-10-29T10:00:00+08:00"
SCRIPT = (
    "import sys\n"
    "from pathlib import Path\n"
    "from jian_kernel.compiler import compile_kernel\n"
    "from jian_kernel.kernel import Policy\n"
    "kernel = compile_kernel(Path(sys.argv[1]), Policy(now=sys.argv[2]))\n"
    "print(kernel.kid)\n"
)


class TestProposalDeterminism(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_prop_det_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        kn_fixtures.write_store(self.root, [
            ("2026-01-01T09:00:00Z", "今天天气不错", "turn", None),
            ("2026-01-02T09:00:00Z", "以后不许半夜打电话", "directive", "lock"),
            *kn_fixtures.chat_turns(9),
        ])
        record_proposal(
            self.root, "self.style", "说话时偶尔停顿", "deepseek-v4", "ab12cd34",
            "2026-10-01T02:00:00Z",
        )
        record_proposal(
            self.root, "self.style", "不急着给结论", "deepseek-v4", "ab12cd34",
            "2026-10-02T02:00:00Z",
        )

    def test_kid_is_stable_across_hash_seeds(self) -> None:
        """P6: two processes with different PYTHONHASHSEED print the same kid."""
        kids: list[str] = []
        for seed in ("0", "12345"):
            env = dict(os.environ)
            env["PYTHONHASHSEED"] = seed
            completed = subprocess.run(
                [sys.executable, "-c", SCRIPT, str(self.root), NOW],
                cwd=str(ROOT), env=env, capture_output=True, text=True, check=True,
            )
            kids.append(completed.stdout.strip())
        print(f"P6 seed0={kids[0][:12]} seed12345={kids[1][:12]}")
        self.assertEqual(kids[0], kids[1])
        self.assertEqual(len(kids[0]), 64)


if __name__ == "__main__":
    unittest.main()
