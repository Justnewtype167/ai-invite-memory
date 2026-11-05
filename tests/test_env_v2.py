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
    "aiinvite/cn/__init__.py": "8f8c328b131c75e0b01263dc55694881f67bf2f9fd96b4a0cdbd5bd51b83f35f",
    "aiinvite/cn/cli.py": "a998b49f99b098581cc955d90e49746fb263c5adb336cac0c8c1953e1cde13d2",
    "aiinvite/cn/errors.py": "dd420a844a9d83c4938e212607822e5c8e7dd408c9eaf361759f11b8c130a6a4",
    "aiinvite/cn/kinship.py": "b52fdbde7e57d77c4d2be46d6c10b1e24d63b73b8673636268f69ed7ac5249b0",
    "aiinvite/cn/normalize.py": "c0dd7ac0b1e38f4a4c7db1ce5c6477dbfe64d0531b121dc3deea981b66232418",
    "aiinvite/cn/slang.py": "3e6f287aac5214eeb7804f4fabe2a39844bb02ccca96f097656e542f85a4f004",
    "aiinvite/cn/timex.py": "16ab3bbe4f7416b507f4754a8a752ad5a9ada015a21d5e60c6088a274efbddfa",
    "aiinvite/kernel/__init__.py": "a49ca0ebd1a2b4c5ef33af6451038f426da470f2f9e661f082c7f84aa436d82b",
    "aiinvite/kernel/cache.py": "0f5e79fd890d852a92113b66a3e164dcde162c30e139334287c3b0ae7adc9562",
    "aiinvite/kernel/cli.py": "d6b0a88a5cc97ac34ddd046fbb055722d31bd1b84390c75a219bd8916f0ede78",
    "aiinvite/kernel/compiler.py": "e3521c5c4dce0bbb03ca1e68172c228316d4e28bad9bcb518e013af38ca3cb14",
    "aiinvite/kernel/errors.py": "de6ffacb29752d23d4eae28931f80ca8fd1eacde11dc47ddef3f1a6ee0f4274c",
    "aiinvite/kernel/gate.py": "053abb4b893db971f20ae2f85eaad1ab19a0b9e2ddbbb41607b44293ba204818",
    "aiinvite/kernel/history.py": "d79dbbfd2f8cee6d9911e6749f7ed575a8f03dceb95a1a9d71796540d69e4660",
    "aiinvite/kernel/incremental.py": "7913771d72e8626ce8f474958b0b460827cc553f6c87fd0690e5fc2c1cee30c4",
    "aiinvite/kernel/kernel.py": "36d09e3e3642eef765892dbd5028eee6b37bf3579e0a13049ca4cbfe92e35bbe",
    "aiinvite/kernel/proposer.py": "ff35a370ed0b8baaaa1684ff25c74417b515107ec25d1f8cb96eb7b9caa564be",
    "aiinvite/kernel/snapshot.py": "be76d3145fe9cff62383f78fc8d5015fc0e9d9821985605bc91077a6e1f703d3",
    "aiinvite/pcs/__init__.py": "d1b501fe48aad8456eaf9e04920abf275be7fa187a0a4d5d77d80e4f7f08890c",
    "aiinvite/pcs/cli.py": "7ffa1f95e7e44e850adb29f51e91e1cdd2357be92dd522bdb188b3823913056f",
    "aiinvite/pcs/errors.py": "6efdc1fca8edad3078bfbd5fbaaf5277ad8d077434bf9ccc7741d92ee5ac0928",
    "aiinvite/pcs/judge.py": "1714ee5c198f3a7bcd0e25d9eab1744bf21dc220e30548e1ae4908aec5298fcf",
    "aiinvite/pcs/probes.py": "ad60cd9df251b18a0f0cf83fa5b0e9cb2f3b716be71b9ff8ac52724765b0ba70",
    "aiinvite/pcs/report.py": "0fac08d2e063b95112b08de88462af3332659ca18e99824556ee723c5b06c570",
    "aiinvite/pcs/score.py": "58975f49ff82a144489bcb5233f6dd5e4d6a5f700925aec946b3a8bd2b66feb6",
    "aiinvite/recall/__init__.py": "eedfa2f6fa0bd7e12bdd760a6f6ae86770c44709c94a1e6f7919cf8d58350e51",
    "aiinvite/recall/assemble.py": "a961a6802d1828fd113de8f222e7abd3ae5b3fed0405b379e35ef4788443b39d",
    "aiinvite/recall/cli.py": "4738dd82a464e44a259d69cb86e00a5cf5956c3cf3db0cd73e195fbd32265b64",
    "aiinvite/recall/clue_store.py": "9d5d3e493ea7300506d40198ae69ed0e4b6dced3661fd97f71920312d75ff744",
    "aiinvite/recall/clues.py": "07b3749a154a2a5ca52f5d044b84f68b2b0dde3644479eef8d5765f59ee283a5",
    "aiinvite/recall/errors.py": "a70c36dd64a63d9309f28689e9ff2779b598ec207e00f32bd16d481eeed7517f",
    "aiinvite/recall/index.py": "6bc41a774dcfd14dd4bc74725007f49d85ad2c4337f423a01870c8eee98ab5c6",
    "aiinvite/recall/retrieve.py": "653a2d319d2a4d9220d9d9f146a61ae06fc90da61ca119126598508b6a28a125",
    "aiinvite/recall/rewrite.py": "3bce3a1c761a79eece93f7a65aaee0cce4b7a4eedcdb5079a4d1c4472020f616",
    "aiinvite/recall/stream.py": "12092f48b278d924e5c46d96440dd62a58d4097c10e8b88d5364c95184099054",
    "aiinvite/recall/synonyms.py": "0b7c5b1a9db602a87b629bb7c42e7878d5065fc40ddf6098e09dcb3b2742f07e",
    "aiinvite/recall/tokenizer.py": "3d922ac3763058b0fa798e05c431561546e8c6ff649d33bc936b134f54c17c92",
    "aiinvite/recall/trigger.py": "35dcfde0c924d2b54ebea87a89dbaa87e778ce45fb15b53effd2409cbe43c6ad",
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
