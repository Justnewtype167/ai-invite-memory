"""R7: all 178 frozen M1-M5.2 tests stay green and the six packages stay byte-identical."""

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
    "test_kn_proposal_fields",
    "test_kn_two_targets",
    "test_kn_thin_evidence",
    "test_kn_subprocess_proposer",
    "test_kn_models_in_meta",
    "test_kn_live_fallback",
)
FROZEN_COUNT = 178

# sha256 of every source file, re-baselined at M18 (the rename moved every
# file, so the baseline was regenerated once; from here on any byte change fails).
FROZEN_DIGESTS = {
    "aiinvite/__init__.py": "156c2a8a88ba3c398efeb037f7cb57c36cffb23e145f0555fd774048aa8636ad",
    "aiinvite/canonical.py": "d62bb641aba457706bd6d4f2fe8ad0af2d29bb74e8ca0c4e690942d263235cce",
    "aiinvite/capsule.py": "6376933fbed96fcc47e0fca911e89ecbfea5eaf7fda8545d1505bd9340a58ab1",
    "aiinvite/chain.py": "c30b71e0aed2ad2a30c7e79d368d82f3f3d0a50d3812ef6566587d9209ffb388",
    "aiinvite/cli.py": "21876229f3bcfa2708c424ba57f5993e3af100149c321d92953b9edce830f6dc",
    "aiinvite/cn/__init__.py": "8f8c328b131c75e0b01263dc55694881f67bf2f9fd96b4a0cdbd5bd51b83f35f",
    "aiinvite/cn/cli.py": "a998b49f99b098581cc955d90e49746fb263c5adb336cac0c8c1953e1cde13d2",
    "aiinvite/cn/errors.py": "dd420a844a9d83c4938e212607822e5c8e7dd408c9eaf361759f11b8c130a6a4",
    "aiinvite/cn/kinship.py": "b52fdbde7e57d77c4d2be46d6c10b1e24d63b73b8673636268f69ed7ac5249b0",
    "aiinvite/cn/normalize.py": "c0dd7ac0b1e38f4a4c7db1ce5c6477dbfe64d0531b121dc3deea981b66232418",
    "aiinvite/cn/slang.py": "3e6f287aac5214eeb7804f4fabe2a39844bb02ccca96f097656e542f85a4f004",
    "aiinvite/cn/timex.py": "16ab3bbe4f7416b507f4754a8a752ad5a9ada015a21d5e60c6088a274efbddfa",
    "aiinvite/errors.py": "f961adc2f3ad652a2cce3d6e148475b152a448bb32cfe2552de08c760817df5e",
    "aiinvite/event.py": "7cdec28600a28f810a527ea131d180b8941c253e6563d884911d797c161b2b89",
    "aiinvite/kernel/__init__.py": "a49ca0ebd1a2b4c5ef33af6451038f426da470f2f9e661f082c7f84aa436d82b",
    "aiinvite/kernel/cli.py": "d6b0a88a5cc97ac34ddd046fbb055722d31bd1b84390c75a219bd8916f0ede78",
    "aiinvite/kernel/compiler.py": "2724e8667cea54b5d5eab791305493618328df848008d560e904092a4181674c",
    "aiinvite/kernel/errors.py": "de6ffacb29752d23d4eae28931f80ca8fd1eacde11dc47ddef3f1a6ee0f4274c",
    "aiinvite/kernel/gate.py": "053abb4b893db971f20ae2f85eaad1ab19a0b9e2ddbbb41607b44293ba204818",
    "aiinvite/kernel/history.py": "d79dbbfd2f8cee6d9911e6749f7ed575a8f03dceb95a1a9d71796540d69e4660",
    "aiinvite/kernel/incremental.py": "341d1a2b3c0efe43406da01ccc47e73ec1ebcc50d16d81e5bcfda5bee234e58f",
    "aiinvite/kernel/kernel.py": "412d348e729322f9f457761fa1a875a46ce906af0f17e8c770abdc2fe6ab616a",
    "aiinvite/kernel/proposer.py": "ff35a370ed0b8baaaa1684ff25c74417b515107ec25d1f8cb96eb7b9caa564be",
    "aiinvite/kernel/snapshot.py": "be76d3145fe9cff62383f78fc8d5015fc0e9d9821985605bc91077a6e1f703d3",
    "aiinvite/pcs/__init__.py": "d1b501fe48aad8456eaf9e04920abf275be7fa187a0a4d5d77d80e4f7f08890c",
    "aiinvite/pcs/cli.py": "7ffa1f95e7e44e850adb29f51e91e1cdd2357be92dd522bdb188b3823913056f",
    "aiinvite/pcs/errors.py": "6efdc1fca8edad3078bfbd5fbaaf5277ad8d077434bf9ccc7741d92ee5ac0928",
    "aiinvite/pcs/judge.py": "1714ee5c198f3a7bcd0e25d9eab1744bf21dc220e30548e1ae4908aec5298fcf",
    "aiinvite/pcs/probes.py": "ad60cd9df251b18a0f0cf83fa5b0e9cb2f3b716be71b9ff8ac52724765b0ba70",
    "aiinvite/pcs/report.py": "0fac08d2e063b95112b08de88462af3332659ca18e99824556ee723c5b06c570",
    "aiinvite/pcs/score.py": "58975f49ff82a144489bcb5233f6dd5e4d6a5f700925aec946b3a8bd2b66feb6",
    "aiinvite/persona/__init__.py": "793fa9ddeec0bf861989c5f5a0bf66992ba597c72808941336a368f14a879410",
    "aiinvite/persona/errors.py": "c565b4d206ad2e79d87500f4f6293a36105d553722b8c2ba3896c91b73d9d170",
    "aiinvite/persona/model.py": "d7c03b142b79346289b24f706d64b68a6ee63652ed7510f4b4e0f6566dbc33ff",
    "aiinvite/persona/style_card.py": "1dc769c247ac3e131caf70dc1207d9f2b452a879d8a25b0399fa4eb52250753b",
    "aiinvite/persona/traits.py": "980c7774d04a104bb4f65ecfa8b37525850e16ada1b58ecad4c3195c049920ac",
    "aiinvite/persona/user_card.py": "8fae4a89525929136fd168943865460465f31dfe7fa9f53747de3709890cd9f6",
    "aiinvite/persona/view.py": "f6296562cb3ae36e75de23a14db6665d9b4e53621ceec08e65e7e98ca022624f",
    "aiinvite/projection/__init__.py": "e8da557758624df10ff1f930479b4d6e7244293d22c75d45775942478af1dfad",
    "aiinvite/projection/action.py": "abe2b87f0b2822a7ef512c4cf335b98085e15141656f5b433a2e009e375cd1d8",
    "aiinvite/projection/emit.py": "7d095396a0ecf3ddce3ad028f5d563e69114f26944091551133aa3dfae7f194b",
    "aiinvite/projection/errors.py": "8583d64c34087bdaf6d3cee5f241b7a7e5320823971be3dda9cb2623cf7b6e63",
    "aiinvite/projection/gate.py": "ea9dea2c39f257c51e029a12c2b13515c3e552c3a442b0ca74f946670c3a6424",
    "aiinvite/projection/text.py": "6f019b97f13a3114ed4e351a6566b0136303cf97c38fc4af44eca57585745660",
    "aiinvite/projection/trace.py": "f8d4049ca39827bc09b1a0b28513a6df40678a43f9fa6620490d744893b3832c",
    "aiinvite/recall/__init__.py": "eedfa2f6fa0bd7e12bdd760a6f6ae86770c44709c94a1e6f7919cf8d58350e51",
    "aiinvite/recall/assemble.py": "dffd2beeea19aeb343b0e5cda4a99b8a4a61fe38cbdb75fa57f22539ba072ac2",
    "aiinvite/recall/cli.py": "4738dd82a464e44a259d69cb86e00a5cf5956c3cf3db0cd73e195fbd32265b64",
    "aiinvite/recall/errors.py": "a70c36dd64a63d9309f28689e9ff2779b598ec207e00f32bd16d481eeed7517f",
    "aiinvite/recall/index.py": "617f9d62992a4628f13b81bc13f9e71e0cfa4df2758fe7122b4edb513d620ee0",
    "aiinvite/recall/retrieve.py": "c3f80c7a124574992b8836260769ea92ae263bb69b7d0efe2d35f96cf648136c",
    "aiinvite/recall/stream.py": "a7ef3844eef9c3668086f062d34648147acc6a04449ded8f2cef51c2a851cfb0",
    "aiinvite/recall/tokenizer.py": "c815698f2e448734111fbbda6ce6613fcf68f162276dde91a30dfdc9e30ccfe4",
    "aiinvite/recall/trigger.py": "35dcfde0c924d2b54ebea87a89dbaa87e778ce45fb15b53effd2409cbe43c6ad",
    "aiinvite/succession/__init__.py": "89378f8f13c6cd52fc3f50a518353da4b789c2ae08ac778fce91dae9a1af4b74",
    "aiinvite/succession/archive.py": "1c9f90627ea9279f840da67426d366ba1381bd7aec1a09f1173dfc4281c7636e",
    "aiinvite/succession/errors.py": "8bc02ae2f1e64759acf9e9374dc3aca934cdfa4db60ecc417a9aff397d258528",
    "aiinvite/succession/legacy.py": "86be089a3b3bbcfe6c028b2490913eb8aa0cd5e827722b7d5c4883f552e164bc",
    "aiinvite/succession/model.py": "981b9502d8fec62c0d9df3b5f9cb2c60a12c9ffcfee5c5f0892336aff8605c64",
}

# New source files are not covered by the baseline; each one must be declared
# here with a reason so that nothing appears in a package unnoticed.
ALLOWED_ADDITIONS = {}

# Every deviation from the baseline must be declared here with a reason.
ALLOWED_CHANGES = {}


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
        """S6: all 178 frozen M1-M5.2 tests pass with zero skips."""
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
        """S6: any deviation from the baseline must be declared in ALLOWED_CHANGES."""
        found = {
            path.relative_to(ROOT).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for package in (
                "aiinvite",
                "aiinvite/cn",
                "aiinvite/recall",
                "aiinvite/kernel",
                "aiinvite/pcs",
                "aiinvite/projection",
                "aiinvite/succession",
                "aiinvite/persona",
            )
            for path in sorted((ROOT / package).rglob("*.py"))
        }
        declared = sorted(list(FROZEN_DIGESTS) + list(ALLOWED_ADDITIONS))
        self.assertEqual(sorted(found), declared)
        changed = {
            name for name, digest in FROZEN_DIGESTS.items() if found[name] != digest
        }
        undeclared = sorted(changed - set(ALLOWED_CHANGES))
        self.assertEqual(undeclared, [], f"undeclared change: {undeclared}")
        stale = sorted(set(ALLOWED_CHANGES) - changed)
        self.assertEqual(stale, [], f"declared but unchanged: {stale}")


if __name__ == "__main__":
    unittest.main()
