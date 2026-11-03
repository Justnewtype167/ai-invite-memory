"""C6: the frozen M1 suite (31 tests) must still pass unchanged."""

from __future__ import annotations

import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
M1_MODULES = ("test_canonical", "test_chain", "test_capsule", "test_cli")
M1_TEST_COUNT = 31


def _load(name: str):
    path = ROOT / "tests" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"m1_{name}", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestM1Regression(unittest.TestCase):
    def test_m1_suite_is_green(self) -> None:
        """C6: all 31 M1 tests still run green with zero skips."""
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for name in M1_MODULES:
            suite.addTests(loader.loadTestsFromModule(_load(name)))
        result = unittest.TestResult()
        suite.run(result)
        self.assertEqual(result.testsRun, M1_TEST_COUNT)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.skipped, [])

    def test_base_package_is_untouched_by_m2(self) -> None:
        """C6: M2 has no source files inside the frozen base package."""
        frozen = ROOT / "aiinvite"
        self.assertTrue(frozen.is_dir())
        self.assertFalse((frozen / "cn.py").exists())
        self.assertTrue((frozen / "cn").is_dir())


if __name__ == "__main__":
    unittest.main()
