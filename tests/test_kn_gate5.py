"""P5: G5a target whitelist, G5b source fields, G5c per-target quota."""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import kn_fixtures

from jian.canonical import dumps
from jian.event import compute_hash, format_id, normalize_time
from jian_kernel.compiler import compile_kernel
from jian_kernel.errors import E_KN_BAD_PROPOSAL, E_KN_BAD_TARGET, KernelError
from jian_kernel.kernel import STYLE_MAX_PER_TARGET, Policy
from jian_kernel.proposer import record_proposal

NOW = "2026-10-29T10:00:00+08:00"
STAMP = "2026-10-29T02:00:00Z"


class TestGateFive(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_g5_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        kn_fixtures.write_store(self.root, [
            ("2026-01-01T09:00:00Z", "今天天气不错", "turn", None),
            *kn_fixtures.chat_turns(9),
        ])

    def _raw(self, target: str, text: str, model: str, prompt_sha: str) -> None:
        """Append a hand-built proposal without any input validation."""
        folder = self.root / "evidence"
        path = folder / "seg-0001.jsonl"
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
        previous = str(json.loads(lines[-1])["hash"])
        body: dict[str, object] = {
            "ep": "seg-0001",
            "id": format_id(len(lines) + 1),
            "model": model,
            "prev": previous,
            "prompt_sha": prompt_sha,
            "t": normalize_time(STAMP),
            "target": target,
            "text": text,
            "type": "proposal",
            "v": 1,
        }
        body["hash"] = compute_hash(previous, body)
        path.write_bytes(
            path.read_bytes() + dumps(body) + b"\n"
        )

    def test_bad_target_is_refused(self) -> None:
        """P5: a proposal aimed at canon raises E_KN_BAD_TARGET."""
        self._raw("canon", "想把这条写进 canon", "m", "ab12cd34")
        with self.assertRaises(KernelError) as caught:
            compile_kernel(self.root, Policy(now=NOW))
        print(f"P5 target=canon -> {caught.exception.code}")
        self.assertEqual(caught.exception.code, E_KN_BAD_TARGET)

    def test_record_refuses_bad_target(self) -> None:
        """P5: record_proposal refuses a target outside the whitelist."""
        with self.assertRaises(KernelError) as caught:
            record_proposal(self.root, "state", "x", "m", "ab12cd34", STAMP)
        self.assertEqual(caught.exception.code, E_KN_BAD_TARGET)

    def test_empty_model_is_refused(self) -> None:
        """P5: G5b rejects a proposal with no model."""
        self._raw("self.style", "风格", "", "ab12cd34")
        with self.assertRaises(KernelError) as caught:
            compile_kernel(self.root, Policy(now=NOW))
        print(f"P5 empty model -> {caught.exception.code}")
        self.assertEqual(caught.exception.code, E_KN_BAD_PROPOSAL)

    def test_per_target_quota(self) -> None:
        """P5: twelve proposals accept eight, the rest count as rejected."""
        for index in range(12):
            record_proposal(
                self.root, "self.style", f"风格{index:02d}", "m", "ab12cd34",
                f"2026-10-0{index % 9 + 1}T02:00:00Z",
            )
        kernel = compile_kernel(self.root, Policy(now=NOW))
        print(f"P5 accepted={len(kernel.style)} rejected={kernel.rejected}")
        self.assertEqual(len(kernel.style), STYLE_MAX_PER_TARGET)
        self.assertEqual(kernel.rejected, 4)


if __name__ == "__main__":
    unittest.main()
