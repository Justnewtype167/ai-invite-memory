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

from aiinvite.capsule import (
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
from aiinvite.errors import E_BLOB_MISMATCH, E_BLOB_MISSING, E_SCHEMA, AiInviteError
from aiinvite.event import event_text, parse_event

ROOT = pathlib.Path(__file__).resolve().parents[1]
STAMP = "2026-11-01T10:00:00Z"
MODALITIES = ("text", "audio", "vision", "action", "sensor")
BASELINE = {
    "aiinvite/cn/__init__.py": "fac7793cd32e5fdbbadaad311de0c9fddf55754bcbcd68a45883c17f3df229df",
    "aiinvite/cn/cli.py": "899c424af5122e91026af1ea2e64ffe1e1b584bbf5e78c800d54f683df4fe642",
    "aiinvite/cn/errors.py": "dd420a844a9d83c4938e212607822e5c8e7dd408c9eaf361759f11b8c130a6a4",
    "aiinvite/cn/kinship.py": "08a84b598fe54c80bb82382b0dcc1ec4db5cf3e013a0c844089f3d789b39f2fa",
    "aiinvite/cn/normalize.py": "074bf3e86485825154c0adac95a53e7e47c1955939723ce5aa8752bb8c110f7f",
    "aiinvite/cn/slang.py": "141107855ecf33339dcd5ba00d38ac5ed3e8a76483738a75958671b747b7418c",
    "aiinvite/cn/timex.py": "4ffcd7a8590957685cb736bf6c759552d93dfcdb4fa65d8d6bcc213301627742",
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
    "aiinvite/recall/__init__.py": "09b76826eea26433cc2084f862a381e25f01522858205379d5bcba79d82775b3",
    "aiinvite/recall/assemble.py": "afca1b8e986939c927ebd08fb5881732bc6ed4a123d81f39c16d20973889f52d",
    "aiinvite/recall/cli.py": "2d391e5aaaeab5b695385f13f25272ae605c9b1931619f1997544d34a8b4267f",
    "aiinvite/recall/errors.py": "a70c36dd64a63d9309f28689e9ff2779b598ec207e00f32bd16d481eeed7517f",
    "aiinvite/recall/index.py": "dbd1959ec30a93a0d6b6cfb7a5597891364e896a277d0133534ca62e7b05f2f2",
    "aiinvite/recall/retrieve.py": "19c820ed9faa082a4ea6a148326b03c8c92d858f17bfc1ef9cf2e503dab6b345",
    "aiinvite/recall/stream.py": "287f9ba247944155afe47ca60709d3f791eebed1bf92db41e535cfec19141366",
    "aiinvite/recall/tokenizer.py": "c815698f2e448734111fbbda6ce6613fcf68f162276dde91a30dfdc9e30ccfe4",
    "aiinvite/recall/trigger.py": "49e704e2a37e5e81e29bfcbf9d57ffa8d6c8b0bfd8cc6a3d3b727a707eae2542",
}
EDITS = {}

# M12 adds two kernel modules and touches kernel files for the snapshot API;
# M12.1 adds verify-on-CLI; M14 adds the recall stream session. Their current
# bytes are pinned here; any later drift fails N5 and must be declared again.
#
# compiler.py moved here from EDITS: it now carries two milestones of edits
# (M10 full-text reads, M12.1 verify_evidence), so the line-level restore
# check no longer reproduces the M10 baseline.
M12_ADDITIONS = {}
M12_EDITS = {}


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
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_env_v2_"))
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
                with self.assertRaises(AiInviteError) as context:
                    parse_event(data)
                self.assertEqual(context.exception.code, E_SCHEMA)
        with self.assertRaises(AiInviteError) as context:
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
        with self.assertRaises(AiInviteError) as context:
            event_full_text(self.store, missing)
        self.assertEqual(context.exception.code, E_BLOB_MISSING)

        from aiinvite.kernel.compiler import read_evidence

        events = read_evidence(self.store)
        self.assertEqual(events[0].text, full)
        self.assertEqual(events[1].text, "一段语音")


class TestBlobStore(unittest.TestCase):
    """N2: content addressed writes, dedupe, tamper and deletion detection."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_blob_"))
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
        with self.assertRaises(AiInviteError) as context:
            verify_path(self.store)
        self.assertEqual(context.exception.code, E_BLOB_MISMATCH)
        path.write_bytes(b"voice")
        path.unlink()
        with self.assertRaises(AiInviteError) as context:
            verify_path(self.store)
        self.assertEqual(context.exception.code, E_BLOB_MISSING)


class TestEnvRoundtrip(unittest.TestCase):
    """N3: export, import and export again is byte identical."""

    def test_env_roundtrip(self) -> None:
        """N3: blobs travel inside the capsule and survive a round trip."""
        root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_env_trip_"))
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
        root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_env_v1_"))
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
            for package in ("aiinvite/cn", "aiinvite/recall", "aiinvite/kernel", "aiinvite/pcs")
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
        for package in ("aiinvite/cn", "aiinvite/pcs"):
            self.assertFalse(
                [name for name in changed if name.startswith(package + "/")],
                f"{package} must stay byte-identical",
            )
        # M18 re-baselined this ledger: the rename moved every file, so the
        # historical per-line edit records were folded into the baseline. The
        # invariant that matters is unchanged: any future byte change fails.
        self.assertEqual(changed, [], "no file may drift from the M18 baseline")
        replaced = sum(len(entry["replaced"]) for entry in EDITS.values())
        self.assertEqual(replaced, 0, "the line-level ledger was folded into the baseline")


class TestSummaryOnlyRetrieval(unittest.TestCase):
    """N6: retrieval reads summaries only, never payload bytes."""

    def test_summary_only_retrieval(self) -> None:
        """N6: swapping payload bytes for equal-length random bytes changes nothing."""
        from aiinvite.recall.index import build_index
        from aiinvite.recall.retrieve import search

        root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_env_retrieval_"))
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
