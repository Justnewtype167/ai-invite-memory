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

# sha256 of every source file in the six packages before M10; an
# edit must be declared in ALLOWED_CHANGES below, otherwise the ratchet fails.
FROZEN_DIGESTS = {
    "jian/__init__.py": "bde7ba3f7b2d7cecac8b284a0f4b4958ef7c463d86be8bd9dfe51bbfb30874bf",
    "jian/canonical.py": "a271683dd6bc9d5edaedce274249ff594122123b7eb120d2317517158445b757",
    "jian/capsule.py": "8e746448130e72be9b99a7c8f78b5be73c8a6631f0e3433e2d860e95bdf1aa76",
    "jian/chain.py": "d107f3c00482c385b1d027ac774c106fb2ed2dbb448f8745896650ddeef7e4a7",
    "jian/cli.py": "69a1d8d6aa82d6f4c4bf287b1fe9b14400aa4cd36c1b743179123c6a875d5323",
    "jian/errors.py": "d1a54fd42da5528225cfde1742b9c37131fbabe5234b98a27e0a9234598b2fec",
    "jian/event.py": "6f24b2affa4728f05df63053935e19ce48a882cc0963d22470d886566633a14a",
    "jian_kernel/__init__.py": "0e6abd2f4d27d87a94453ee36aab70ac093d1b002ed9f453365146146f258f80",
    "jian_kernel/cli.py": "9c45b7aa55f42e4af4350ab9bcbcbbe5ce07513f8be78d3f0b6db54ceec63902",
    "jian_kernel/compiler.py": "a4be2a88409429589dd4084b1b60a316fb51a1550aeeb47b3c6ed9d8f43c2e46",
    "jian_kernel/errors.py": "9a33269b938c633672b2e22f22df1023c4eaed5e378559d04d4a4575cd581ca5",
    "jian_kernel/gate.py": "960fb8b655a16515c43c478f5ee8bac5762a1f8a059588670a75e806c26a872a",
    "jian_kernel/history.py": "d08c85ded030a0a4c5c301b25d96ed24df8011a3140782f932789443c34c3ace",
    "jian_kernel/kernel.py": "faac0333bdd0892edecae94b550a7b49da6e478898ccceeb62410ada5ba4749c",
    "jian_kernel/proposer.py": "8c7ffaba5432c08b326d8bfb8894405bd3eb85ef3bddd65b55f7d2b037e4d508",
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
    "jian_pcs/__init__.py": "250a01df396288b8752489db1dd0ec7c90a493a9c9a7c171f82612f6aefab6f9",
    "jian_pcs/cli.py": "9f2f4d9ad39875d90365c3616f5d512013a4eb0f54ab0010943436141fe68c99",
    "jian_pcs/errors.py": "6efdc1fca8edad3078bfbd5fbaaf5277ad8d077434bf9ccc7741d92ee5ac0928",
    "jian_pcs/judge.py": "45b1cfb63c21d5b867e4638c2d6e6674e3eefb13f7445a45a0d72d127816a412",
    "jian_pcs/probes.py": "4de3b690641c236cc94ce37507e310b421731d5df2941eef3add13c7f1de047e",
    "jian_pcs/report.py": "26633cb51d822e729158da133b68ac336b934232b4a12b30135913b373700bdc",
    "jian_pcs/score.py": "28fe4f226ce8e7d052d80ee8409763c062f114ed7921adad964a8b1a7b08d88b",
    "jian_projection/__init__.py": (
        "2918c12193c4a9327ea12b49dc10e0fc3fe137650d918a3705b175747467d11f"
    ),
    "jian_projection/action.py": (
        "2bb135820646c05e3362bb96f851395efd3802a6b7eebce27f8247833d38fae7"
    ),
    "jian_projection/errors.py": (
        "d87cb2b0f0150dbc78d90ec92ca692bf34da7d5ba340a934decbb021fd3ac9b9"
    ),
    "jian_projection/text.py": (
        "3b79d162e686f364bc7c19eab9ad53e7311bedb75f1a1b09c60675601ef878fb"
    ),
    "jian_projection/trace.py": (
        "b91e9d343c863a4db73a6234d40d55a681b21e4828f5638c5474528b855921e9"
    ),
}

# New source files are not covered by the baseline; each one must be declared
# here with a reason so that nothing appears in a package unnoticed.
ALLOWED_ADDITIONS = {
    "jian_kernel/incremental.py": "M12: incremental compile and reconcile",
    "jian_kernel/snapshot.py": "M12: throwaway snapshot payload and digest",
    "jian_projection/emit.py": "M13: the only emit path, gate before sink",
    "jian_projection/gate.py": "M13: pure actuation gate over trace and kernel",
    "jian_recall/stream.py": "M14: stream session, chunks and entry-count statistics",
    "jian_succession/__init__.py": "M15: export the legacy capsule API",
    "jian_succession/errors.py": "M15: fixed E_SUCC_* codes",
    "jian_succession/model.py": "M15: capsule constants, letters and kid recomputation",
    "jian_succession/archive.py": "M15: zip, evidence and blob primitives",
    "jian_succession/legacy.py": "M15: export, verify and import a legacy capsule",
    "jian_persona/__init__.py": "M16: export the persona derivation API",
    "jian_persona/errors.py": "M16: fixed E_PERSONA_* codes",
    "jian_persona/model.py": "M16: trait definitions, activations and conflicts",
    "jian_persona/traits.py": "M16: vocabulary validation and deterministic resolution",
    "jian_persona/style_card.py": "M16: style card validation, recording and echo guard",
    "jian_persona/user_card.py": "M16: mechanical user card with pinned assembly",
    "jian_persona/view.py": "M16: shared persona view and four prompt groups",
}

# Every deviation from the baseline must be declared here with a reason.
ALLOWED_CHANGES = {
    "jian/event.py": (
        "M10: envelope v2 fields and event_text; M13: refusal type and trace; "
        "M16: trait / trait_off directive kinds and optional approval target"
    ),
    "jian/chain.py": "M10: optional chain blobs, blob store, fast scan, revival v2; M13: segment slot helpers",
    "jian/capsule.py": (
        "M10: payload API, v2 seal/export/import, event_full_text; M13: append_refusal; "
        "M16: provenance keywords on both append paths"
    ),
    "jian/errors.py": "M10: E_BLOB_MISSING and E_BLOB_MISMATCH",
    "jian_recall/index.py": "M10: retrieval reads summary through event_text",
    "jian_recall/errors.py": "M14: E_RC_STREAM for chunk boundary violations",
    "jian_recall/__init__.py": "M14: export the stream session API",
    "jian_recall/trigger.py": "M14.1: split triggers into per-predicate parts for caching",
    "jian_recall/assemble.py": "M14.1: share the pool-to-context step with the stream session",
    "jian_kernel/compiler.py": (
        "M10: full text via event_full_text; M12.1: verify_evidence and --no-verify; "
        "M16: refusal type and the persona skip list"
    ),
    "jian_kernel/proposer.py": "M10: proposal text goes through event_text",
    "jian_kernel/errors.py": "M12: E_KN_SNAPSHOT, E_KN_DRIFT; M12.1: E_KN_TAMPER",
    "jian_kernel/__init__.py": "M12: export the incremental and reconcile API",
    "jian_kernel/cli.py": "M12: compile --incremental and reconcile; M12.1: --no-verify",
    "jian_kernel/gate.py": "M16: accept persona targets for direct callers of check_proposals",
    "jian_kernel/kernel.py": "M16: persona target and directive-kind constants",
    "jian_projection/__init__.py": "M13: export gate and emit",
    "jian_projection/action.py": "M13: carry the segment role through projection",
    "jian_projection/errors.py": "M13: E_PR_GATE_RULES and E_PR_GATE_SCOPE",
    "jian_projection/text.py": "M13: mark narrative as description and canon as constraint",
    "jian_projection/trace.py": "M13: Segment.role (speech / description / constraint)",
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
                "jian",
                "jian_cn",
                "jian_recall",
                "jian_kernel",
                "jian_pcs",
                "jian_projection",
                "jian_succession",
                "jian_persona",
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
