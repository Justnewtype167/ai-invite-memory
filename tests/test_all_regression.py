"""S6: all 131 frozen M1-M4 tests stay green after M4.1."""

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
    "test_rc_tokenizer",
    "test_rc_index",
    "test_rc_retrieve",
    "test_rc_assemble",
    "test_rc_trigger",
    "test_rc_quality",
    "test_rc_perf",
    "test_rc_regression",
    "test_kn_compile",
    "test_kn_determinism",
    "test_kn_gate",
    "test_kn_history",
    "test_kn_sources",
    "test_kn_regression",
)
FROZEN_COUNT = 131


def _load(name: str):
    path = ROOT / "tests" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"all_{name}", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestAllRegression(unittest.TestCase):
    def test_frozen_suites_are_green(self) -> None:
        """S6: all 131 frozen M1-M4 tests pass with zero skips."""
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for name in MODULES:
            suite.addTests(loader.loadTestsFromModule(_load(name)))
        result = unittest.TestResult()
        suite.run(result)
        print(
            f"S6 frozen tests={result.testsRun} failures={len(result.failures)} "
            f"errors={len(result.errors)} skipped={len(result.skipped)}"
        )
        self.assertEqual(result.testsRun, FROZEN_COUNT)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.skipped, [])


if __name__ == "__main__":
    unittest.main()
