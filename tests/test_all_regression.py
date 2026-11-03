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
    "aiinvite/canonical.py": "702327a3e39911c66cbd4ce4dc68475d0a508ab8e28d9888ab78a13cdb8ecf03",
    "aiinvite/capsule.py": "5a03e5841c99c85aaa8fc592ca4bd8c8b7d257a2eeda79379b9b9b8365c84960",
    "aiinvite/chain.py": "461e9a7f61627349cd2e14002a6882132e855e81f28554ff63d6856ae31de105",
    "aiinvite/cli.py": "d0e5b2bb25813ced51967dd7995f0ba59b85e22d39911bce89281b5e0bfeadba",
    "aiinvite/cn/__init__.py": "fac7793cd32e5fdbbadaad311de0c9fddf55754bcbcd68a45883c17f3df229df",
    "aiinvite/cn/cli.py": "899c424af5122e91026af1ea2e64ffe1e1b584bbf5e78c800d54f683df4fe642",
    "aiinvite/cn/errors.py": "dd420a844a9d83c4938e212607822e5c8e7dd408c9eaf361759f11b8c130a6a4",
    "aiinvite/cn/kinship.py": "08a84b598fe54c80bb82382b0dcc1ec4db5cf3e013a0c844089f3d789b39f2fa",
    "aiinvite/cn/normalize.py": "074bf3e86485825154c0adac95a53e7e47c1955939723ce5aa8752bb8c110f7f",
    "aiinvite/cn/slang.py": "141107855ecf33339dcd5ba00d38ac5ed3e8a76483738a75958671b747b7418c",
    "aiinvite/cn/timex.py": "4ffcd7a8590957685cb736bf6c759552d93dfcdb4fa65d8d6bcc213301627742",
    "aiinvite/errors.py": "aae9ff149b0614554497c01ad65105a8f4b9783e9aecdceb4f9897e3b00579cc",
    "aiinvite/event.py": "4a3b0602fc98ac7d8468102d4cb9b14e254c0b97132a782ea6d10b41c46f4e95",
    "aiinvite/kernel/__init__.py": "ead1a2cfd56a9f6eedd245b78501d1f288f69129c8c974bf77cdaedd6446ef08",
    "aiinvite/kernel/cli.py": "03467453b9d7109fe1c6b5aaef9293a434dd10fd4b1aa4037e47ed7e39654fcc",
    "aiinvite/kernel/compiler.py": "10dc8072e2b710c94eeaa6d7d1de2fa12e663d766c27bf03066e41248fe7c03c",
    "aiinvite/kernel/errors.py": "de6ffacb29752d23d4eae28931f80ca8fd1eacde11dc47ddef3f1a6ee0f4274c",
    "aiinvite/kernel/gate.py": "99dbda8d4119705140046b2563cee113ceb0b1c466db6ed2ff338bd6bec1b2a7",
    "aiinvite/kernel/history.py": "f44cbd54f1926d1229f1da9a0fd005049be45c12489c47ecc804311481d0faa8",
    "aiinvite/kernel/incremental.py": "82983f66cec62d82f039e8d24b8afe526f46f7dec50ddea4ec7e4f29fec513d2",
    "aiinvite/kernel/kernel.py": "4d8694a86c70dfc35a9a379b117358e7456152727de106e0d01269fc6b20c393",
    "aiinvite/kernel/proposer.py": "998f7c4015d6fe2a8a987a80d93f214ab20e0ecf53d25efc138509065e9247ff",
    "aiinvite/kernel/snapshot.py": "4006adda2873324897dfda85958abd3edfe613562f82f71f9a23ffb6e3e87d8a",
    "aiinvite/pcs/__init__.py": "a1ca0aaf61d5f3c252490f410c4f0a1ed86ecf3e2c88c161355ae3612f88a008",
    "aiinvite/pcs/cli.py": "8c804bdabaed68db1d624308cf21dd3f10fdd9e02ff2e35d0e2f6948569301b2",
    "aiinvite/pcs/errors.py": "6efdc1fca8edad3078bfbd5fbaaf5277ad8d077434bf9ccc7741d92ee5ac0928",
    "aiinvite/pcs/judge.py": "4be709cd849de52f5dfded20842d44fd652d9c88f1470fd8a26ddd39a3c30183",
    "aiinvite/pcs/probes.py": "f17cfc27e9d2817ee92172120945a940fc215905da751c60df274ae9da6548dc",
    "aiinvite/pcs/report.py": "db2e6795b886759b935578b72273d22aeb9ec3687b5e4125923f2c693ea05493",
    "aiinvite/pcs/score.py": "047019d3030f34025b5a089fa9f9669b49469e13394db886e62527c215ac82be",
    "aiinvite/persona/__init__.py": "6d4b8f9324e16f9a9b659b993cc38246e4d98b90d3b0c1e00a74c90e49f97171",
    "aiinvite/persona/errors.py": "c565b4d206ad2e79d87500f4f6293a36105d553722b8c2ba3896c91b73d9d170",
    "aiinvite/persona/model.py": "d7c03b142b79346289b24f706d64b68a6ee63652ed7510f4b4e0f6566dbc33ff",
    "aiinvite/persona/style_card.py": "53274ba0a6fe7969cf0056ce21978245e054f678a2949fefc17dfd096e08e855",
    "aiinvite/persona/traits.py": "ed51ef206bf4b4708c44ceb357112d2e855d41f8f8239638a52106a823a4a48e",
    "aiinvite/persona/user_card.py": "6bdd0e211c2e33d2f2bd4dcddd699e9b09418ae4d1f908d041d6218bdd8ee5d6",
    "aiinvite/persona/view.py": "27968d4f85877a9f78c8f8b77109aa02cd0901af07ac069324cf730c4c18803e",
    "aiinvite/projection/__init__.py": "eba314cb345e362076f9bd927c892916326c22564b8d2fc90bdb8787c5025b7e",
    "aiinvite/projection/action.py": "c028eced6cbe1db3175c4a363bc7e46057ffe8316fbcbe3a524ec6cf8bcc7dee",
    "aiinvite/projection/emit.py": "a9b4ada55f20cf6bd95825a12e19a7781e2889d57ff2055b898194ed4bda29ad",
    "aiinvite/projection/errors.py": "8583d64c34087bdaf6d3cee5f241b7a7e5320823971be3dda9cb2623cf7b6e63",
    "aiinvite/projection/gate.py": "5348c215c529c507646f8b7d4f379f9963f540978cf7604bc026a6bdfdc5f476",
    "aiinvite/projection/text.py": "75f2bbce5ab98b07af7bff4d3213a5bbcc7ece878a37a0b49039344c1eaa35af",
    "aiinvite/projection/trace.py": "006c1ea1eb98c57372dac3dea8ac11aed84a75b9a3ca5f825ad2461d4a100cad",
    "aiinvite/recall/__init__.py": "09b76826eea26433cc2084f862a381e25f01522858205379d5bcba79d82775b3",
    "aiinvite/recall/assemble.py": "afca1b8e986939c927ebd08fb5881732bc6ed4a123d81f39c16d20973889f52d",
    "aiinvite/recall/cli.py": "2d391e5aaaeab5b695385f13f25272ae605c9b1931619f1997544d34a8b4267f",
    "aiinvite/recall/errors.py": "a70c36dd64a63d9309f28689e9ff2779b598ec207e00f32bd16d481eeed7517f",
    "aiinvite/recall/index.py": "dbd1959ec30a93a0d6b6cfb7a5597891364e896a277d0133534ca62e7b05f2f2",
    "aiinvite/recall/retrieve.py": "19c820ed9faa082a4ea6a148326b03c8c92d858f17bfc1ef9cf2e503dab6b345",
    "aiinvite/recall/stream.py": "287f9ba247944155afe47ca60709d3f791eebed1bf92db41e535cfec19141366",
    "aiinvite/recall/tokenizer.py": "c815698f2e448734111fbbda6ce6613fcf68f162276dde91a30dfdc9e30ccfe4",
    "aiinvite/recall/trigger.py": "49e704e2a37e5e81e29bfcbf9d57ffa8d6c8b0bfd8cc6a3d3b727a707eae2542",
    "aiinvite/succession/__init__.py": "7871d81ee8eb9de0348d415971db22a803f8da4f8d9fb238212ebc7c0b64ade1",
    "aiinvite/succession/archive.py": "6cd7056b2eb1bff8e2654a75b62b80b7da568e658f602664abbb31937016fb2c",
    "aiinvite/succession/errors.py": "8bc02ae2f1e64759acf9e9374dc3aca934cdfa4db60ecc417a9aff397d258528",
    "aiinvite/succession/legacy.py": "212d3ade2a9db8bb22aadee09a0181b252f24b87105d3aeb79f48206bde2f11a",
    "aiinvite/succession/model.py": "4cdf33a3eb9f84fed2610fb88740e6426103e7b5b6cc297f0dfdd43e29486d43",
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
