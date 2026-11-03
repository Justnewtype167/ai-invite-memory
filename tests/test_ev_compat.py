"""S2: M1 stays intact -- 31 frozen tests and old capsules still verify."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import tempfile
import unittest

from aiinvite.capsule import append_event, export_capsule, init_store, seal_store, verify_path

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULES = ("test_canonical", "test_chain", "test_capsule", "test_cli")
FROZEN_COUNT = 31
STAMP = "2026-10-28T09:00:00Z"


def _load(name: str):
    path = ROOT / "tests" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"compat_{name}", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestM1Compat(unittest.TestCase):
    def test_m1_suites_still_green(self) -> None:
        """S2: all 31 frozen M1 tests pass with zero skips."""
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for name in MODULES:
            suite.addTests(loader.loadTestsFromModule(_load(name)))
        result = unittest.TestResult()
        suite.run(result)
        print(
            f"S2 m1 tests={result.testsRun} failures={len(result.failures)} "
            f"errors={len(result.errors)} skipped={len(result.skipped)}"
        )
        self.assertEqual(result.testsRun, FROZEN_COUNT)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.skipped, [])

    def test_old_capsule_still_verifies(self) -> None:
        """S2: a capsule of M1-shaped turn events verifies unchanged."""
        root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_compat_"))
        self.addCleanup(shutil.rmtree, root, True)
        store = root / "mem"
        init_store(store)
        for index in range(6):
            role = "user" if index % 2 == 0 else "assistant"
            append_event(store, role, f"旧记忆 {index + 1}", STAMP)
        seal_store(store)
        capsule = root / "old.aiem"
        export_capsule(store, capsule)
        events = [
            json.loads(line)
            for line in (store / "evidence" / "seg-0001.jsonl")
            .read_text(encoding="utf-8").splitlines()
        ]
        types = sorted({row["type"] for row in events})
        print(f"S2 old capsule events={len(events)} types={types}")
        fields = {"ep", "hash", "id", "prev", "role", "t", "text", "type", "v"}
        for row in events:
            self.assertEqual(row["type"], "turn")
            self.assertEqual(set(row), fields)
        self.assertEqual(verify_path(capsule).events, 6)
        self.assertEqual(verify_path(store).events, 6)


if __name__ == "__main__":
    unittest.main()
