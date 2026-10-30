"""S6: all 161 frozen M1-M5.1 tests stay green after M5.2, and two packages stay byte-identical."""

from __future__ import annotations

import hashlib
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
    "test_ev_types",
    "test_ev_compat",
    "test_rc_dedupe",
    "test_rc_coverage",
    "test_rc_determinism",
    "test_kn_compile",
    "test_kn_determinism",
    "test_kn_gate",
    "test_kn_history",
    "test_kn_sources",
    "test_kn_regression",
    "test_kn_proposal_event",
    "test_kn_proposal_effect",
    "test_kn_proposal_required",
    "test_kn_fallback",
    "test_kn_gate5",
    "test_kn_proposal_determinism",
)
FROZEN_COUNT = 161

# sha256 of every source file in the two frozen packages; any edit breaks M5.
FROZEN_DIGESTS = {
    "jian_cn/__init__.py": "4da6b5679be5c8112b1a8aff17dbcc860cee86473333a761aab1614e28795c77",
    "jian_cn/cli.py": "1752a9843e20f1cea94aa4f968abe37b3124ce857afea649c543ddc7385db7fb",
    "jian_cn/errors.py": "dd420a844a9d83c4938e212607822e5c8e7dd408c9eaf361759f11b8c130a6a4",
    "jian_cn/kinship.py": "77b623ee3bcfa15f87ac44e32925f071b3575eccdc4fb1f6c5585f8da31e5dcb",
    "jian_cn/normalize.py": "eb324c8ee8e47a3c78bbcdd5e48b746987b03a2f8b0f45fb82c2905d1d120525",
    "jian_cn/slang.py": "42df9313d2b66162ee8f24307d129b34c38d0b2be89e591192a79946be382b42",
    "jian_cn/timex.py": "f9602049ef99c4b155ba8c726b51e952a53797fbc99abb8a209a4c4f89d7574d",
    "jian_recall/__init__.py": "f2e8f89eee35011563c2111656ea0a3abf76740da5fc57f276967d4b4413e4cf",
    "jian_recall/assemble.py": "ccb5ad2eddfe50151439c1ef4df83f1e477dff7f7f630bda6dc95e10455f8570",
    "jian_recall/cli.py": "33ecd64bdc8c9f42547c82cdd688fedfe44c5a04ab32c5d6541334c9b5a180ac",
    "jian_recall/errors.py": "37000fa2d668cc8ea8ce314f12f7331f945be6f79854a84f7001d23bdbffad4f",
    "jian_recall/index.py": "a532fa489a87a259c32d4335f061e9657429961fbf45c967a6847106d93ad329",
    "jian_recall/retrieve.py": "f551191730355077f40fc7cd80cba89b6190cb3975dc3e2a1a38c1799566082b",
    "jian_recall/tokenizer.py": "c815698f2e448734111fbbda6ce6613fcf68f162276dde91a30dfdc9e30ccfe4",
    "jian_recall/trigger.py": "4f198c620461a3ab204eb9b21a2f9438a2d0ff75af1bfb6b78fc8945c81fca92",
}


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
        """S6: all 161 frozen M1-M5.1 tests pass with zero skips."""
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

    def test_frozen_packages_are_byte_identical(self) -> None:
        """S6: M5 must not touch ``jian_cn`` or ``jian_recall`` at all."""
        found = {
            path.relative_to(ROOT).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for package in ("jian_cn", "jian_recall")
            for path in sorted((ROOT / package).rglob("*.py"))
        }
        self.assertEqual(sorted(found), sorted(FROZEN_DIGESTS))
        for name, digest in FROZEN_DIGESTS.items():
            self.assertEqual(found[name], digest, f"frozen file changed: {name}")


if __name__ == "__main__":
    unittest.main()
