"""N1-N6 and P0: the v2 payload envelope, the blob store and identity text."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import random
import shutil
import tempfile
import unittest

from jian.capsule import (
    BLOBS_DIR,
    append_event,
    append_payload_event,
    event_full_text,
    export_capsule,
    import_capsule,
    init_store,
    put_blob,
    read_blob,
    seal_store,
    verify_path,
)
from jian.errors import E_BLOB_MISMATCH, E_BLOB_MISSING, E_SCHEMA, JianError
from jian.event import event_text, parse_event

ROOT = pathlib.Path(__file__).resolve().parents[1]
STAMP = "2026-11-01T10:00:00Z"
MODALITIES = ("text", "audio", "vision", "action", "sensor")
BASELINE = {
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
    "jian_kernel/__init__.py": "0e6abd2f4d27d87a94453ee36aab70ac093d1b002ed9f453365146146f258f80",
    "jian_kernel/cli.py": "9c45b7aa55f42e4af4350ab9bcbcbbe5ce07513f8be78d3f0b6db54ceec63902",
    "jian_kernel/compiler.py": "a4be2a88409429589dd4084b1b60a316fb51a1550aeeb47b3c6ed9d8f43c2e46",
    "jian_kernel/errors.py": "9a33269b938c633672b2e22f22df1023c4eaed5e378559d04d4a4575cd581ca5",
    "jian_kernel/gate.py": "960fb8b655a16515c43c478f5ee8bac5762a1f8a059588670a75e806c26a872a",
    "jian_kernel/history.py": "d08c85ded030a0a4c5c301b25d96ed24df8011a3140782f932789443c34c3ace",
    "jian_kernel/kernel.py": "faac0333bdd0892edecae94b550a7b49da6e478898ccceeb62410ada5ba4749c",
    "jian_kernel/proposer.py": "8c7ffaba5432c08b326d8bfb8894405bd3eb85ef3bddd65b55f7d2b037e4d508",
    "jian_pcs/__init__.py": "250a01df396288b8752489db1dd0ec7c90a493a9c9a7c171f82612f6aefab6f9",
    "jian_pcs/cli.py": "9f2f4d9ad39875d90365c3616f5d512013a4eb0f54ab0010943436141fe68c99",
    "jian_pcs/errors.py": "6efdc1fca8edad3078bfbd5fbaaf5277ad8d077434bf9ccc7741d92ee5ac0928",
    "jian_pcs/judge.py": "45b1cfb63c21d5b867e4638c2d6e6674e3eefb13f7445a45a0d72d127816a412",
    "jian_pcs/probes.py": "4de3b690641c236cc94ce37507e310b421731d5df2941eef3add13c7f1de047e",
    "jian_pcs/report.py": "26633cb51d822e729158da133b68ac336b934232b4a12b30135913b373700bdc",
    "jian_pcs/score.py": "28fe4f226ce8e7d052d80ee8409763c062f114ed7921adad964a8b1a7b08d88b",
}
EDITS = {
    "jian_recall/index.py": {
        "added": ["from jian.event import event_text\n"],
        "replaced": [
            ('    text = event_text(data)\n', '    text = data.get("text")\n'),
        ],
    },

    "jian_kernel/proposer.py": {
        "added": ["    event_text,\n"],
        "replaced": [
            ('    text = event_text(data)\n', '    text = data.get("text")\n'),
        ],
    },
}

# M12 adds two kernel modules and touches kernel files for the snapshot API;
# M12.1 adds verify-on-CLI; M14 adds the recall stream session. Their current
# bytes are pinned here; any later drift fails N5 and must be declared again.
#
# compiler.py moved here from EDITS: it now carries two milestones of edits
# (M10 full-text reads, M12.1 verify_evidence), so the line-level restore
# check no longer reproduces the M10 baseline.
M12_ADDITIONS = {
    "jian_kernel/incremental.py": (
        "219bad591635174a9c77509d7188ea2fae0a836fd403e66e2539a17ad1bd6a5d"
    ),
    "jian_kernel/snapshot.py": (
        "71489979a001867a03ccdce5ea71250ff9025a5f7fcca9b7527a956511fe2d40"
    ),
    "jian_recall/stream.py": (
        "865ec458dc16aa4e1e6f56fdcfb541a8fbbe48fe22c0a501928bcc543a89f0ae"
    ),
}
M12_EDITS = {
    "jian_kernel/__init__.py": (
        "e6b96cf565c8efafa86fc5812a7a3dc05c3eb31608219607de8eb8cc7005c4a5"
    ),
    # M12.1: --no-verify flag, verify_evidence, E_KN_TAMPER
    "jian_kernel/cli.py": (
        "7e9c3091597e20287060416e498b969456c2742c2726fc2ff34d4390d101fc5f"
    ),
    "jian_kernel/compiler.py": (
        "b8117d33e59a3d21f5787f8fbc0c7480f7f5057aeafac03b428cea036f89bb9e"
    ),
    "jian_kernel/errors.py": (
        "de6ffacb29752d23d4eae28931f80ca8fd1eacde11dc47ddef3f1a6ee0f4274c"
    ),
    # M14: E_RC_STREAM and the stream session exports
    "jian_recall/errors.py": (
        "a70c36dd64a63d9309f28689e9ff2779b598ec207e00f32bd16d481eeed7517f"
    ),
    "jian_recall/__init__.py": (
        "a7770481301b7d1d8057dde2018d1aa830a77966c748e8690a8f644655adcc90"
    ),
}


def _load(name: str):
    path = ROOT / "tests" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"v2_{name}", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _lines(store: pathlib.Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (store / "evidence" / "seg-0001.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]


class TestEnvV2(unittest.TestCase):
    """N1: five modalities write, seal and verify; bad envelopes fail."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_env_v2_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "mem"
        init_store(self.store)

    def test_env_v2(self) -> None:
        """N1: all five modalities join one chain; schema rules hold."""
        for index, modality in enumerate(MODALITIES):
            append_payload_event(
                self.store,
                modality,
                f"摘要 {modality}",
                f"payload-{modality}".encode("utf-8"),
                role="user" if index % 2 == 0 else "assistant",
                t=STAMP,
            )
        rows = _lines(self.store)
        self.assertEqual(len(rows), 5)
        for row, modality in zip(rows, MODALITIES):
            self.assertEqual(row["v"], 2)
            self.assertEqual(row["modality"], modality)
            self.assertNotIn("text", row)
            self.assertEqual(event_text(row), row["summary"])
            self.assertEqual(parse_event(row).modality, modality)
        seal_store(self.store)
        sealed = verify_path(self.store)
        self.assertEqual(sealed.events, 5)
        self.assertEqual(sealed.segments, 1)
        chain = json.loads((self.store / "chain.json").read_text(encoding="utf-8"))
        self.assertEqual(len(chain["blobs"]), 5)
        manifest = json.loads((self.store / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["format"], 2)
        self.assertEqual(manifest["blob_count"], 5)

    def test_bad_envelopes_are_schema_errors(self) -> None:
        """N1: illegal modality, missing payload/summary, v2 text, long summary."""
        append_payload_event(
            self.store, "text", "合法摘要", b"ok", role="user", t=STAMP
        )
        good = _lines(self.store)[0]
        cases = (
            lambda data: data.update({"modality": "video"}),
            lambda data: data.pop("payload"),
            lambda data: data.pop("summary"),
            lambda data: data.update({"text": "不该出现"}),
            lambda data: data.update({"summary": "x" * 201}),
            lambda data: data.update({"payload": "sha256:ABC"}),
        )
        for change in cases:
            with self.subTest(change=change):
                data = json.loads(json.dumps(good))
                change(data)
                with self.assertRaises(JianError) as context:
                    parse_event(data)
                self.assertEqual(context.exception.code, E_SCHEMA)
        with self.assertRaises(JianError) as context:
            append_payload_event(
                self.store, "video", "摘要", b"x", role="user", t=STAMP
            )
        self.assertEqual(context.exception.code, E_SCHEMA)

    def test_event_text_accessor(self) -> None:
        """N1: the accessor reads text for v1, summary for v2, else empty."""
        self.assertEqual(event_text({"v": 1, "text": "旧"}), "旧")
        self.assertEqual(event_text({"v": 2, "summary": "新"}), "新")
        self.assertEqual(event_text({"v": 1}), "")
        self.assertEqual(event_text({"v": 2, "text": "被忽略"}), "")

    def test_event_full_text_reads_blob(self) -> None:
        """P0: identity text is the whole payload, summary stays retrieval-only."""
        full = "甲" * 150 + "乙" * 150
        summary = full[:200]
        append_payload_event(
            self.store, "text", summary, full.encode("utf-8"), role="user", t=STAMP
        )
        append_payload_event(
            self.store, "audio", "一段语音", b"voice", role="assistant", t=STAMP
        )
        rows = _lines(self.store)
        self.assertEqual(event_text(rows[0]), summary)
        self.assertEqual(event_full_text(self.store, rows[0]), full)
        self.assertEqual(len(full), 300)
        self.assertEqual(event_full_text(self.store, rows[1]), "一段语音")
        self.assertEqual(event_full_text(self.store, {"v": 1, "text": "旧"}), "旧")
        missing = dict(rows[0], payload="sha256:" + "0" * 64)
        with self.assertRaises(JianError) as context:
            event_full_text(self.store, missing)
        self.assertEqual(context.exception.code, E_BLOB_MISSING)

        from jian_kernel.compiler import read_evidence

        events = read_evidence(self.store)
        self.assertEqual(events[0].text, full)
        self.assertEqual(events[1].text, "一段语音")


class TestBlobStore(unittest.TestCase):
    """N2: content addressed writes, dedupe, tamper and deletion detection."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_blob_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "mem"
        init_store(self.store)

    def test_blob_store(self) -> None:
        """N2: address equals sha256, one file per content, tamper is caught."""
        first = put_blob(self.store, b"same bytes")
        second = put_blob(self.store, b"same bytes")
        self.assertEqual(first, hashlib.sha256(b"same bytes").hexdigest())
        self.assertEqual(first, second)
        self.assertEqual(len(list((self.store / BLOBS_DIR).iterdir())), 1)
        self.assertEqual(read_blob(self.store, first), b"same bytes")

        append_payload_event(self.store, "audio", "一段语音", b"voice", role="user", t=STAMP)
        seal_store(self.store)
        self.assertEqual(verify_path(self.store).events, 1)
        digest = hashlib.sha256(b"voice").hexdigest()
        path = self.store / BLOBS_DIR / digest
        path.write_bytes(b"tampered")
        with self.assertRaises(JianError) as context:
            verify_path(self.store)
        self.assertEqual(context.exception.code, E_BLOB_MISMATCH)
        path.write_bytes(b"voice")
        path.unlink()
        with self.assertRaises(JianError) as context:
            verify_path(self.store)
        self.assertEqual(context.exception.code, E_BLOB_MISSING)


class TestEnvRoundtrip(unittest.TestCase):
    """N3: export, import and export again is byte identical."""

    def test_env_roundtrip(self) -> None:
        """N3: blobs travel inside the capsule and survive a round trip."""
        root = pathlib.Path(tempfile.mkdtemp(prefix="jian_env_trip_"))
        self.addCleanup(shutil.rmtree, root, True)
        store = root / "mem"
        init_store(store)
        append_payload_event(store, "text", "她喜欢桂花", b"memory-1", role="user", t=STAMP)
        append_payload_event(store, "vision", "一张合照", b"\x00\x01\x02", role="assistant", t=STAMP)
        append_payload_event(store, "action", "握手动作", b"memory-1", role="user", t=STAMP)
        seal_store(store)
        first = root / "first.aiem"
        export_capsule(store, first)
        self.assertEqual(verify_path(first).events, 3)
        copied = root / "copied"
        import_capsule(first, copied)
        self.assertEqual(verify_path(copied).events, 3)
        self.assertEqual(len(list((copied / BLOBS_DIR).iterdir())), 2)
        second = root / "second.aiem"
        export_capsule(copied, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())


class TestEnvV1Compat(unittest.TestCase):
    """N4: v1 capsules, v1 directories and the 31 M1 tests stay intact."""

    def test_env_v1_compat(self) -> None:
        """N4: v1 verify/export/import and seal keep working."""
        root = pathlib.Path(tempfile.mkdtemp(prefix="jian_env_v1_"))
        self.addCleanup(shutil.rmtree, root, True)
        store = root / "mem"
        init_store(store)
        for index in range(4):
            role = "user" if index % 2 == 0 else "assistant"
            append_event(store, role, f"旧记忆 {index + 1}", STAMP)
        capsule = root / "old.aiem"
        seal_store(store)
        export_capsule(store, capsule)
        self.assertEqual(verify_path(capsule).events, 4)
        self.assertEqual(verify_path(store).events, 4)
        copied = root / "copied"
        import_capsule(capsule, copied)
        self.assertEqual(verify_path(copied).events, 4)
        rows = _lines(store)
        fields = {"ep", "hash", "id", "prev", "role", "t", "text", "type", "v"}
        for row in rows:
            self.assertEqual(set(row), fields)
            self.assertEqual(row["v"], 1)
        manifest = json.loads((store / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("format", manifest)
        self.assertNotIn("blob_count", manifest)
        self.assertFalse((store / BLOBS_DIR).exists())
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for name in ("test_canonical", "test_chain", "test_capsule", "test_cli"):
            suite.addTests(loader.loadTestsFromModule(_load(name)))
        result = unittest.TestResult()
        suite.run(result)
        print(
            f"N4 m1 tests={result.testsRun} failures={len(result.failures)} "
            f"errors={len(result.errors)} skipped={len(result.skipped)}"
        )
        self.assertEqual(result.testsRun, 31)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.skipped, [])


class TestUpperLayersTouchLimit(unittest.TestCase):
    """N5: the M10 line edits plus the declared M12 additions, nothing else."""

    def test_upper_layers_touch_limit(self) -> None:
        """N5: only declared files differ; restoring the M10 lines rebuilds baseline."""
        found = {
            path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for package in ("jian_cn", "jian_recall", "jian_kernel", "jian_pcs")
            for path in sorted((ROOT / package).rglob("*.py"))
        }
        self.assertEqual(sorted(found), sorted(list(BASELINE) + list(M12_ADDITIONS)))
        for name, digest in M12_ADDITIONS.items():
            self.assertEqual(found[name], digest, f"undeclared change in {name}")
        changed = [name for name in BASELINE if found[name] != BASELINE[name]]
        self.assertEqual(sorted(changed), sorted(list(EDITS) + list(M12_EDITS)))
        for name, digest in M12_EDITS.items():
            self.assertEqual(found[name], digest, f"undeclared change in {name}")
        for name in sorted(EDITS):
            text = (ROOT / name).read_text(encoding="utf-8")
            restored = text
            for after, before in EDITS[name]["replaced"]:
                self.assertEqual(text.count(after), 1, f"edited line missing: {name}")
                self.assertNotIn(before, text.replace(after, ""), f"old line survived: {name}")
                restored = restored.replace(after, before)
            for line in EDITS[name]["added"]:
                self.assertEqual(text.count(line), 1, f"added line missing: {name}")
                restored = restored.replace(line, "", 1)
            self.assertEqual(
                hashlib.sha256(restored.encode("utf-8")).hexdigest(),
                BASELINE[name],
                f"undeclared change in {name}",
            )
        for package in ("jian_cn", "jian_pcs"):
            self.assertFalse(
                [name for name in changed if name.startswith(package + "/")],
                f"{package} must stay byte-identical",
            )
        # M10 touched three files with one functional line each; M12.1 added
        # the verify gate, which moved compiler.py to the whole-file pin above;
        # M14 touched two recall files for the stream session.
        self.assertEqual(len(changed), 8)
        replaced = sum(len(entry["replaced"]) for entry in EDITS.values())
        self.assertEqual(replaced, 2, "two remaining M10 line-level edits")
        self.assertIn("jian_kernel/compiler.py", M12_EDITS, "compiler.py must stay pinned")


class TestSummaryOnlyRetrieval(unittest.TestCase):
    """N6: retrieval reads summaries only, never payload bytes."""

    def test_summary_only_retrieval(self) -> None:
        """N6: swapping payload bytes for equal-length random bytes changes nothing."""
        from jian_recall.index import build_index
        from jian_recall.retrieve import search

        root = pathlib.Path(tempfile.mkdtemp(prefix="jian_env_retrieval_"))
        self.addCleanup(shutil.rmtree, root, True)
        store = root / "mem"
        init_store(store)
        summaries = (
            "我妈下周三做手术",
            "她通过了考试",
            "每周日晚上视频",
            "她喜欢桂花",
            "今天下雨了",
        )
        payloads = [f"raw-bytes-{index}".encode("utf-8") for index in range(len(summaries))]
        for index, (summary, payload) in enumerate(zip(summaries, payloads)):
            append_payload_event(
                store, "text", summary, payload,
                role="user" if index % 2 == 0 else "assistant", t=STAMP,
            )
        build_index(store)
        query = "我妈手术是什么时候"
        before = [(hit.event_id, hit.text) for hit in search(store, query, 5)]
        self.assertIn(summaries[0], [text for _, text in before])
        self.assertTrue(all(text in summaries for _, text in before))

        rng = random.Random(20261101)
        for payload in payloads:
            digest = hashlib.sha256(payload).hexdigest()
            path = store / BLOBS_DIR / digest
            replacement = bytes(rng.getrandbits(8) for _ in range(len(payload)))
            self.assertNotEqual(replacement, payload)
            path.write_bytes(replacement)
        build_index(store)
        after = [(hit.event_id, hit.text) for hit in search(store, query, 5)]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
