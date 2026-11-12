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
    "aiinvite/__init__.py": "5006902bc0d55ad29666e7200b5658ee4f3267acf657f718bb057196100ba1d5",
    "aiinvite/canonical.py": "d62bb641aba457706bd6d4f2fe8ad0af2d29bb74e8ca0c4e690942d263235cce",
    "aiinvite/capsule.py": "36eab3fbe82b31aadf9b389936e9010d3e8711d212e1b434fef0ceefda4bf286",
    "aiinvite/chain.py": "c30b71e0aed2ad2a30c7e79d368d82f3f3d0a50d3812ef6566587d9209ffb388",
    "aiinvite/cli.py": "4d4cb31df0e87cae522590eebc596d61f75dc1d9b04703058c380ed483c2739c",
    "aiinvite/cn/__init__.py": "8f8c328b131c75e0b01263dc55694881f67bf2f9fd96b4a0cdbd5bd51b83f35f",
    "aiinvite/cn/cli.py": "a998b49f99b098581cc955d90e49746fb263c5adb336cac0c8c1953e1cde13d2",
    "aiinvite/cn/errors.py": "dd420a844a9d83c4938e212607822e5c8e7dd408c9eaf361759f11b8c130a6a4",
    "aiinvite/cn/kinship.py": "b52fdbde7e57d77c4d2be46d6c10b1e24d63b73b8673636268f69ed7ac5249b0",
    "aiinvite/cn/normalize.py": "c0dd7ac0b1e38f4a4c7db1ce5c6477dbfe64d0531b121dc3deea981b66232418",
    "aiinvite/cn/slang.py": "3e6f287aac5214eeb7804f4fabe2a39844bb02ccca96f097656e542f85a4f004",
    "aiinvite/cn/timex.py": "16ab3bbe4f7416b507f4754a8a752ad5a9ada015a21d5e60c6088a274efbddfa",
    "aiinvite/demo/__init__.py": "ff893837c6710592c7504a11bc18a4cb4e7c402a208d016104899ff98a01e299",
    "aiinvite/demo/app.py": "b8a8362bfa65f3a6e4b898e41a38bec753aa1905dc1724d8351b91bd6f2ebcae",
    "aiinvite/demo/engine.py": "dac9fd6ec662496fc782fa573baa3be8a871f5b04776bd2c3246029abb7365a5",
    "aiinvite/errors.py": "f961adc2f3ad652a2cce3d6e148475b152a448bb32cfe2552de08c760817df5e",
    "aiinvite/event.py": "df369ac05c3b733d978a86cda53d98bcba9467e7ecd3cd17866f3ec3bb44a34e",
    "aiinvite/host/__init__.py": "5dcb7f7ee17657de1be60839f6027deac0eb2dfd556ae81ad693fb7879b729cf",
    "aiinvite/kernel/__init__.py": "a49ca0ebd1a2b4c5ef33af6451038f426da470f2f9e661f082c7f84aa436d82b",
    "aiinvite/kernel/cache.py": "9dbab1eccda4e0fb37aa641e35b86e1cab5aece33ad67973e681c16a2f22dc6d",
    "aiinvite/kernel/cli.py": "d6b0a88a5cc97ac34ddd046fbb055722d31bd1b84390c75a219bd8916f0ede78",
    "aiinvite/kernel/compiler.py": "e3521c5c4dce0bbb03ca1e68172c228316d4e28bad9bcb518e013af38ca3cb14",
    "aiinvite/kernel/errors.py": "de6ffacb29752d23d4eae28931f80ca8fd1eacde11dc47ddef3f1a6ee0f4274c",
    "aiinvite/kernel/gate.py": "053abb4b893db971f20ae2f85eaad1ab19a0b9e2ddbbb41607b44293ba204818",
    "aiinvite/kernel/history.py": "d79dbbfd2f8cee6d9911e6749f7ed575a8f03dceb95a1a9d71796540d69e4660",
    "aiinvite/kernel/incremental.py": "7913771d72e8626ce8f474958b0b460827cc553f6c87fd0690e5fc2c1cee30c4",
    "aiinvite/kernel/kernel.py": "36d09e3e3642eef765892dbd5028eee6b37bf3579e0a13049ca4cbfe92e35bbe",
    "aiinvite/kernel/proposer.py": "ff35a370ed0b8baaaa1684ff25c74417b515107ec25d1f8cb96eb7b9caa564be",
    "aiinvite/kernel/snapshot.py": "69417524a06e1266a66dc440c86170b158b44124d702cbb58b156e24834415fc",
    "aiinvite/pcs/__init__.py": "d1b501fe48aad8456eaf9e04920abf275be7fa187a0a4d5d77d80e4f7f08890c",
    "aiinvite/pcs/cli.py": "7ffa1f95e7e44e850adb29f51e91e1cdd2357be92dd522bdb188b3823913056f",
    "aiinvite/pcs/errors.py": "6efdc1fca8edad3078bfbd5fbaaf5277ad8d077434bf9ccc7741d92ee5ac0928",
    "aiinvite/pcs/judge.py": "1714ee5c198f3a7bcd0e25d9eab1744bf21dc220e30548e1ae4908aec5298fcf",
    "aiinvite/pcs/probes.py": "ad60cd9df251b18a0f0cf83fa5b0e9cb2f3b716be71b9ff8ac52724765b0ba70",
    "aiinvite/pcs/report.py": "0fac08d2e063b95112b08de88462af3332659ca18e99824556ee723c5b06c570",
    "aiinvite/pcs/score.py": "58975f49ff82a144489bcb5233f6dd5e4d6a5f700925aec946b3a8bd2b66feb6",
    "aiinvite/persona/__init__.py": "34a2e078e550dff7fe964a3d19e99e3fe9d7bbacdf76186b504b0bbf8219af11",
    "aiinvite/persona/card_fold.py": "2870268873a6bfd8b213fbc4c398be6306183e74d38b2a289e6ec77f864b341d",
    "aiinvite/persona/errors.py": "c565b4d206ad2e79d87500f4f6293a36105d553722b8c2ba3896c91b73d9d170",
    "aiinvite/persona/model.py": "d7c03b142b79346289b24f706d64b68a6ee63652ed7510f4b4e0f6566dbc33ff",
    "aiinvite/persona/pins.py": "afaa30495a5da5a093697fcc4e015f3565f18efeb26b139edeebf56e0c57a32b",
    "aiinvite/persona/style_card.py": "934b314f8a2fd81ebfc89cf31c2cf62753966f08b94c6c54603f1de5a1e2d1f6",
    "aiinvite/persona/traits.py": "980c7774d04a104bb4f65ecfa8b37525850e16ada1b58ecad4c3195c049920ac",
    "aiinvite/persona/user_card.py": "63db09a1db3512f8c0026123e9fd06e94068253686fb175c1d437021ad34ed07",
    "aiinvite/persona/view.py": "7a3e9d500eff649010282a26d051c633ed25515fb89defe6ca9cf4ed72062f94",
    "aiinvite/projection/__init__.py": "e8da557758624df10ff1f930479b4d6e7244293d22c75d45775942478af1dfad",
    "aiinvite/projection/action.py": "abe2b87f0b2822a7ef512c4cf335b98085e15141656f5b433a2e009e375cd1d8",
    "aiinvite/projection/emit.py": "7d095396a0ecf3ddce3ad028f5d563e69114f26944091551133aa3dfae7f194b",
    "aiinvite/projection/errors.py": "8583d64c34087bdaf6d3cee5f241b7a7e5320823971be3dda9cb2623cf7b6e63",
    "aiinvite/projection/gate.py": "ea9dea2c39f257c51e029a12c2b13515c3e552c3a442b0ca74f946670c3a6424",
    "aiinvite/projection/text.py": "6f019b97f13a3114ed4e351a6566b0136303cf97c38fc4af44eca57585745660",
    "aiinvite/projection/trace.py": "f8d4049ca39827bc09b1a0b28513a6df40678a43f9fa6620490d744893b3832c",
    "aiinvite/recall/__init__.py": "eedfa2f6fa0bd7e12bdd760a6f6ae86770c44709c94a1e6f7919cf8d58350e51",
    "aiinvite/recall/assemble.py": "a961a6802d1828fd113de8f222e7abd3ae5b3fed0405b379e35ef4788443b39d",
    "aiinvite/recall/cli.py": "4738dd82a464e44a259d69cb86e00a5cf5956c3cf3db0cd73e195fbd32265b64",
    "aiinvite/recall/clue_store.py": "93269c02b1e3d8d20702461519866b8561860a1f3c041769daa88065b45696bd",
    "aiinvite/recall/clues.py": "11afc1c10168686e8e0fb2d44bbbb95c0fc7f1ff81455d485aa60e6e7be21ce7",
    "aiinvite/recall/errors.py": "a70c36dd64a63d9309f28689e9ff2779b598ec207e00f32bd16d481eeed7517f",
    "aiinvite/recall/index.py": "b5bc53a8fef731f3bdcba6493df248d622adf7c4888126d5392a45747f4dc692",
    "aiinvite/recall/retrieve.py": "bcc55909978bf824acd067ea37d6d89506e3884373da332ad4f3fd486eee5962",
    "aiinvite/recall/rewrite.py": "3bce3a1c761a79eece93f7a65aaee0cce4b7a4eedcdb5079a4d1c4472020f616",
    "aiinvite/recall/stream.py": "12092f48b278d924e5c46d96440dd62a58d4097c10e8b88d5364c95184099054",
    "aiinvite/recall/synonyms.py": "0b7c5b1a9db602a87b629bb7c42e7878d5065fc40ddf6098e09dcb3b2742f07e",
    "aiinvite/recall/tokenizer.py": "3d922ac3763058b0fa798e05c431561546e8c6ff649d33bc936b134f54c17c92",
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
