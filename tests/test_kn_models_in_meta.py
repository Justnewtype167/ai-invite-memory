"""Q5: META.models records every model in ascending order and enters the kid."""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import kn_fixtures

from jian_kernel.history import record_kernel
from jian_kernel.kernel import Policy
from jian_kernel.proposer import record_proposal

NOW = "2026-10-29T10:00:00+08:00"
STAMP = "2026-10-29T02:00:00Z"
TEXT = "回答前先停半秒"


class TestModelsInMeta(unittest.TestCase):
    def setUp(self) -> None:
        self.stores: list[pathlib.Path] = []
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        for store in self.stores:
            shutil.rmtree(store, True)

    def _store(self, models: list[str]) -> pathlib.Path:
        store = pathlib.Path(tempfile.mkdtemp(prefix="jian_q5_"))
        self.stores.append(store)
        kn_fixtures.write_store(store, kn_fixtures.chat_turns(10))
        for model in models:
            record_proposal(
                store, "self.style", TEXT, model,
                "ab12cd34", STAMP, quant="Q4_K_M",
                weights_sha="a1b2c3d4", temp_milli=0, seed=1,
            )
        return store

    def test_models_are_sorted_and_change_the_kid(self) -> None:
        """Q5: two models give two sorted META entries and a different kid."""
        two = self._store(["alpha", "beta"])
        one = self._store(["alpha", "alpha"])
        result_two = record_kernel(two, Policy(now=NOW))
        result_one = record_kernel(one, Policy(now=NOW))
        meta = json.loads((two / "kernel" / "META.json").read_text(encoding="utf-8"))
        print(
            f"Q5 models={meta['models']} proposals={meta['proposals']} "
            f"kid_two={result_two.kid[:12]} kid_one={result_one.kid[:12]}"
        )
        self.assertEqual(
            meta["models"],
            ["alpha/Q4_K_M/a1b2c3d4", "beta/Q4_K_M/a1b2c3d4"],
        )
        self.assertEqual(meta["proposals"], {"accepted": 2, "rejected": 0})
        self.assertNotEqual(result_two.kid, result_one.kid)


if __name__ == "__main__":
    unittest.main()
