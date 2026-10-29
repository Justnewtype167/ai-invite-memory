"""K6: the 104 frozen M1-M3 tests stay green and the packages stay untouched."""

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
)
FROZEN_COUNT = 104
FROZEN_PACKAGES = ("jian", "jian_cn", "jian_recall")


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
        """K6: all 104 frozen M1-M3 tests still pass with zero skips."""
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for name in MODULES:
            suite.addTests(loader.loadTestsFromModule(_load(name)))
        result = unittest.TestResult()
        suite.run(result)
        print(
            f"K6 frozen tests={result.testsRun} failures={len(result.failures)} "
            f"errors={len(result.errors)} skipped={len(result.skipped)}"
        )
        self.assertEqual(result.testsRun, FROZEN_COUNT)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.skipped, [])

    def test_frozen_packages_do_not_know_the_kernel(self) -> None:
        """K6: no frozen source mentions the M4 package."""
        offenders: list[str] = []
        for name in FROZEN_PACKAGES:
            for path in sorted((ROOT / name).rglob("*.py")):
                if "jian_kernel" in path.read_text(encoding="utf-8"):
                    offenders.append(str(path))
        self.assertEqual(offenders, [])
        for name in FROZEN_PACKAGES:
            self.assertFalse((ROOT / name / "kernel.py").exists())
        self.assertTrue((ROOT / "jian_kernel" / "compiler.py").is_file())


if __name__ == "__main__":
    unittest.main()
