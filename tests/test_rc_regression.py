"""R8: the frozen M1 and M2 suites must stay green (75 tests)."""

from __future__ import annotations

import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULES = (
    "test_canonical",
    "test_chain",
    "test_capsule",
    "test_cli",
    "test_cn_normalize",
    "test_cn_kinship",
    "test_cn_timex",
    "test_cn_slang",
    "test_cn_hygiene",
    "test_cn_regression",
)
FROZEN_COUNT = 75


def _load(name: str):
    path = ROOT / "tests" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"frozen_{name}", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestRegression(unittest.TestCase):
    def test_frozen_suites_are_green(self) -> None:
        """R8: all 75 frozen M1/M2 tests still pass with zero skips."""
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for name in MODULES:
            suite.addTests(loader.loadTestsFromModule(_load(name)))
        result = unittest.TestResult()
        suite.run(result)
        print(
            f"R8 frozen tests={result.testsRun} failures={len(result.failures)} "
            f"errors={len(result.errors)} skipped={len(result.skipped)}"
        )
        self.assertEqual(result.testsRun, FROZEN_COUNT)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.skipped, [])

    def test_recall_package_is_additive(self) -> None:
        """R8: M3 keeps the frozen packages untouched."""
        frozen = ROOT / "jian"
        self.assertTrue((frozen / "event.py").is_file())
        self.assertFalse((frozen / "recall.py").exists())
        self.assertTrue((ROOT / "jian_recall" / "tokenizer.py").is_file())


if __name__ == "__main__":
    unittest.main()
