"""Proposer failure downgrades to rule fallback unless --strict-proposals is set."""

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

import kn_fixtures

from jian_kernel.compiler import compile_kernel
from jian_kernel.errors import E_PROPOSER_FAILED, KernelError
from jian_kernel.kernel import ORIGIN_RULE_FALLBACK, ORIGIN_RULE_ONLY, Policy
from jian_kernel.proposer import ingest_live

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOW = "2026-10-29T10:00:00+08:00"

FAILURE = """
import json
import sys

sys.stdin.readline()
sys.stdout.write(json.dumps({"ok": False, "code": "E_PROPOSER_FAILED",
                            "message": "cuda out of memory"}) + "\\n")
"""

SUCCESS = """
import json
import sys

request = json.loads(sys.stdin.readline())
sys.stdout.write(json.dumps({"ok": True, "text": "回答前先停半秒",
                            "model": "fake-local", "temp_milli": 0,
                            "seed": 7}) + "\\n")
"""


class TestLiveFallback(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_fb_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        kn_fixtures.write_store(self.root, kn_fixtures.chat_turns(10))
        self.fail_script = self.root / "fail.py"
        self.fail_script.write_text(FAILURE, encoding="utf-8")
        self.ok_script = self.root / "ok.py"
        self.ok_script.write_text(SUCCESS, encoding="utf-8")

    def test_failure_is_downgraded(self) -> None:
        """A failed proposer leaves evidence intact and forces rule_fallback."""
        rule_only = compile_kernel(self.root, Policy(now=NOW))
        outcome = ingest_live(
            self.root, [sys.executable, str(self.fail_script)], timeout=30
        )
        fallback = compile_kernel(self.root, Policy(now=NOW, force_fallback=True))
        print(
            f"FB failed={outcome.failed} errors={len(outcome.errors)} "
            f"origin={fallback.origin} kid_rule={rule_only.kid[:12]} "
            f"kid_fallback={fallback.kid[:12]}"
        )
        self.assertEqual(outcome.failed, 2)
        self.assertEqual(outcome.recorded, ())
        self.assertIn("cuda out of memory", outcome.errors[0])
        self.assertEqual(fallback.origin, ORIGIN_RULE_FALLBACK)
        self.assertEqual(rule_only.origin, ORIGIN_RULE_ONLY)
        self.assertNotEqual(fallback.kid, rule_only.kid)

    def test_strict_proposals_raise(self) -> None:
        """--strict-proposals turns the first failure into a hard error."""
        with self.assertRaises(KernelError) as caught:
            ingest_live(
                self.root, [sys.executable, str(self.fail_script)],
                timeout=30, strict=True,
            )
        print(f"FB strict -> {caught.exception.code}")
        self.assertEqual(caught.exception.code, E_PROPOSER_FAILED)

    def test_success_is_not_fallback(self) -> None:
        """A working proposer records both targets and stays with_proposals."""
        outcome = ingest_live(
            self.root, [sys.executable, str(self.ok_script)], timeout=30
        )
        kernel = compile_kernel(self.root, Policy(now=NOW))
        print(f"FB ok recorded={len(outcome.recorded)} origin={kernel.origin}")
        self.assertEqual(outcome.failed, 0)
        self.assertEqual(len(outcome.recorded), 2)
        self.assertEqual(kernel.origin, "with_proposals")

    def test_cli_downgrades_by_default(self) -> None:
        """compile exits 0, reports proposals_failed and rule_fallback."""
        completed = self._cli(["--proposer-cmd",
                               f'"{sys.executable}" "{self.fail_script}"'])
        payload = json.loads(completed.stdout.splitlines()[-1])
        print(
            f"FB cli rc={completed.returncode} origin={payload['origin']} "
            f"failed={payload['proposals_failed']}"
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(payload["origin"], ORIGIN_RULE_FALLBACK)
        self.assertEqual(payload["proposals_failed"], 2)
        self.assertIn("proposer fallback", completed.stderr)

    def test_cli_strict_fails(self) -> None:
        """compile --strict-proposals exits 1 instead of downgrading."""
        completed = self._cli(["--proposer-cmd",
                               f'"{sys.executable}" "{self.fail_script}"',
                               "--strict-proposals"])
        print(f"FB cli strict rc={completed.returncode}")
        self.assertEqual(completed.returncode, 1)

    def _cli(self, extra: list[str]) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable, "-m", "jian_kernel.cli", "compile",
            str(self.root), "--now", NOW, *extra,
        ]
        return subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONUTF8": "1"}, timeout=120,
        )


if __name__ == "__main__":
    unittest.main()
