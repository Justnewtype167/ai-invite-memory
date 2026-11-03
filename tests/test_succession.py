"""M15: legacy capsules, redaction records and inheritance declarations."""

from __future__ import annotations

import json
import pathlib
import shutil
import tempfile
import unittest
import zipfile

from aiinvite.capsule import append_event, init_store, seal_store, verify_path
from aiinvite.kernel.kernel import Policy

from aiinvite.succession import (
    LegacyInfo,
    Letter,
    SuccessionError,
    export_legacy,
    import_legacy,
    load_policy,
    policy_bytes,
    recompute_kid,
    verify_legacy,
)
from aiinvite.succession import archive
from aiinvite.succession.errors import (
    E_SUCC_HEADER,
    E_SUCC_IO,
    E_SUCC_MODE,
    E_SUCC_REDACTION,
    E_SUCC_SCHEMA,
)
from aiinvite.succession.model import (
    MODE_INHERIT,
    POLICY_PATH,
    REDACTION_PATH,
    SUCCESSION_PATH,
    LegacyInfo as InfoClass,
    policy_from_bytes,
)

NOW = "2026-11-01T00:00:00Z"
EXCLUDED = {
    "ev_000005": "third_party",
    "ev_000006": "third_party",
    "ev_000007": "private",
}
ROWS = (
    ("user", "我叫林知夏，在杭州做产品。", "2024-01-02T09:00:00+08:00"),
    ("assistant", "记下了，知夏。", "2024-01-02T09:00:05+08:00"),
    ("user", "我养了一只猫叫团子。", "2024-02-11T21:00:00+08:00"),
    ("assistant", "团子是个好名字。", "2024-02-11T21:00:05+08:00"),
    ("user", "同事王工说这个方案不可行。", "2024-03-01T10:00:00+08:00"),
    ("assistant", "王工的意见记下了。", "2024-03-01T10:00:05+08:00"),
    ("user", "我和陈默吵架了。", "2024-04-05T20:00:00+08:00"),
    ("assistant", "我在听。", "2024-04-05T20:00:05+08:00"),
    ("user", "我答应过你，六月带你去看海。", "2024-05-01T09:00:00+08:00"),
    ("assistant", "我记住这个约定。", "2024-05-01T09:00:05+08:00"),
    ("user", "今天我升职了。", "2024-06-01T18:00:00+08:00"),
    ("assistant", "恭喜你，知夏。", "2024-06-01T18:00:05+08:00"),
)
LETTER = Letter("知夏", NOW, "接手的人", "你好，替我把团子照顾好。")


def build_store(root: pathlib.Path) -> pathlib.Path:
    """Write a small sealed store with third-party speech and one feedback."""
    store = root / "store"
    init_store(store)
    for role, text, stamp in ROWS:
        append_event(store, role, text, stamp)
    append_event(
        store, type="feedback", kind="correction", text="你昨天记错了",
        t="2024-06-02T09:00:00+08:00",
    )
    append_event(
        store, role="assistant", text="是我记错了，改过来。",
        t="2024-06-02T09:00:05+08:00",
    )
    seal_store(store)
    return store


def rewrite(source: pathlib.Path, target: pathlib.Path, name: str, mutate) -> None:
    """Copy a capsule, replacing one entry and leaving the manifest untouched."""
    entries = archive.read_zip(source)
    payload = json.loads(entries[name].decode("utf-8"))
    entries[name] = json.dumps(
        mutate(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    archive.write_zip(entries, target)


def read_entry(path: pathlib.Path, name: str) -> dict[str, object]:
    """Return one JSON entry of a capsule."""
    return json.loads(archive.read_zip(path)[name].decode("utf-8"))


class TestSuccession(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_m15_"))
        cls.store = build_store(cls.root)
        cls.policy = Policy(now=NOW)
        cls.origin_kid = recompute_kid(cls.store, cls.policy)
        cls.plain = cls.root / "plain.aiem"
        cls.info = export_legacy(
            cls.store, cls.plain, policy=cls.policy, letter=LETTER
        )
        cls.redacted = cls.root / "redacted.aiem"
        cls.red_info = export_legacy(
            cls.store, cls.redacted, policy=cls.policy, letter=LETTER,
            exclude=EXCLUDED,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root, True)

    def test_legacy_roundtrip(self) -> None:
        """Y1: export -> verify -> import keeps kid, events and segments."""
        verified = verify_legacy(self.plain)
        self.assertEqual(verified.kid, self.info.kid)
        self.assertEqual(verified.events, 14)
        self.assertEqual(verified.segments, 1)
        target = self.root / "imported-plain"
        if target.exists():
            shutil.rmtree(target, True)
        imported = import_legacy(self.plain, target)
        self.assertEqual(imported.kid, self.info.kid)
        self.assertEqual(recompute_kid(target, load_policy(target / POLICY_PATH)),
                         imported.kid)
        self.assertEqual(verify_path(target).events, 14)

    def test_redaction_is_recorded(self) -> None:
        """Y2: every removal lands in redaction.json with a reason."""
        record = read_entry(self.redacted, REDACTION_PATH)
        self.assertEqual(record["excluded"], sorted(EXCLUDED))
        self.assertEqual(
            record["reason"], {key: EXCLUDED[key] for key in sorted(EXCLUDED)}
        )
        self.assertEqual(record["origin_kid"], self.origin_kid)
        self.assertEqual(record["redacted_kid"], self.red_info.kid)
        self.assertNotEqual(record["redacted_kid"], record["origin_kid"])
        self.assertEqual(len(record["reason"]), 3)
        self.assertEqual(self.red_info.events, 11)
        self.assertTrue(self.red_info.redacted)
        self.assertEqual(self.red_info.excluded, tuple(sorted(EXCLUDED)))

    def test_redaction_is_verifiable(self) -> None:
        """Y3: editing redaction.json is caught by verify."""
        bad = self.root / "bad-redaction.aiem"
        rewrite(self.redacted, bad, REDACTION_PATH,
                lambda data: {**data, "excluded": [], "reason": {}})
        with self.assertRaises(SuccessionError) as caught:
            verify_legacy(bad)
        self.assertEqual(caught.exception.code, E_SUCC_REDACTION)
        bad_reason = self.root / "bad-reason.aiem"
        rewrite(self.redacted, bad_reason, REDACTION_PATH,
                lambda data: {**data, "reason": {"ev_000005": "requested"}})
        with self.assertRaises(SuccessionError) as caught:
            verify_legacy(bad_reason)
        self.assertEqual(caught.exception.code, E_SUCC_REDACTION)

    def test_deleted_evidence_without_record_is_caught(self) -> None:
        """Y3b: dropping an event line breaks the manifest binding."""
        entries = archive.read_zip(self.plain)
        lines = entries["evidence/seg-0001.jsonl"].decode("utf-8").split("\n")
        kept = [line for index, line in enumerate(lines) if index != 3]
        entries["evidence/seg-0001.jsonl"] = "\n".join(kept).encode("utf-8")
        bad = self.root / "bad-silence.aiem"
        archive.write_zip(entries, bad)
        with self.assertRaises(SuccessionError) as caught:
            verify_legacy(bad)
        self.assertEqual(caught.exception.code, E_SUCC_HEADER)

    def test_successor_identity(self) -> None:
        """Y4: redaction changes the successor; no redaction keeps it."""
        verified = verify_legacy(self.redacted)
        self.assertNotEqual(verified.successor_kid, verified.origin_kid)
        self.assertNotEqual(verified.successor_kid, self.origin_kid)
        plain = verify_legacy(self.plain)
        self.assertFalse(plain.redacted)
        self.assertEqual(plain.successor_kid, plain.origin_kid)
        self.assertEqual(plain.successor_kid, self.origin_kid)

    def test_successor_kid_is_recomputable(self) -> None:
        """Y4b: the successor kid follows from evidence and policy alone."""
        entries = archive.read_zip(self.redacted)
        with tempfile.TemporaryDirectory(prefix="aiinvite_m15_re_") as folder:
            scratch = pathlib.Path(folder)
            for name, data in entries.items():
                if archive.entry_kind(name) is None:
                    continue
                archive.write_bytes(scratch / name, data)
            shipped = policy_from_bytes(entries[POLICY_PATH])
            recomputed = recompute_kid(scratch, shipped)
            changed = Policy(
                now="2027-11-01T00:00:00Z", delta_limit=shipped.delta_limit,
                require_proposals=shipped.require_proposals,
                allow_fallback=shipped.allow_fallback,
                force_fallback=shipped.force_fallback,
            )
            moved = recompute_kid(scratch, changed)
        self.assertEqual(recomputed, self.red_info.kid)
        self.assertNotEqual(moved, recomputed)
        succession = read_entry(self.redacted, SUCCESSION_PATH)
        self.assertEqual(succession["successor_kid"], recomputed)
        self.assertEqual(succession["derived_from"], self.origin_kid)
        bad = self.root / "bad-policy.aiem"
        rewrite(self.redacted, bad, POLICY_PATH,
                lambda data: {**data, "now": "2027-11-01T00:00:00Z"})
        with self.assertRaises(SuccessionError) as caught:
            verify_legacy(bad)
        self.assertEqual(caught.exception.code, E_SUCC_HEADER)

    def test_mode_is_inherit_only(self) -> None:
        """Y5: any mode other than inherit is rejected with E_SUCC_MODE."""
        for value in ("copy", "continue", "successor", ""):
            bad = self.root / f"bad-mode-{value or 'empty'}.aiem"
            rewrite(self.plain, bad, SUCCESSION_PATH,
                    lambda data, chosen=value: {**data, "mode": chosen})
            with self.assertRaises(SuccessionError) as caught:
                verify_legacy(bad)
            self.assertEqual(caught.exception.code, E_SUCC_MODE)
        self.assertEqual(
            read_entry(self.plain, SUCCESSION_PATH)["mode"], MODE_INHERIT
        )

    def test_capsule_contains_no_runnable_payload(self) -> None:
        """Y5b: the capsule ships data only, never an execution path."""
        names = sorted(archive.read_zip(self.plain))
        suffixes = {pathlib.Path(name).suffix for name in names}
        self.assertEqual(suffixes, {".json", ".jsonl", ".md", ".txt"})
        for name in names:
            self.assertIsNotNone(archive.entry_kind(name) or name == "manifest.json")

    def test_export_requires_a_sealed_store(self) -> None:
        """E_SUCC_SCHEMA when the source directory is still open."""
        open_store = self.root / "open-store"
        init_store(open_store)
        append_event(open_store, "user", "还没封存", "2024-01-02T09:00:00+08:00")
        with self.assertRaises(SuccessionError) as caught:
            export_legacy(open_store, self.root / "open.aiem", policy=self.policy)
        self.assertEqual(caught.exception.code, E_SUCC_SCHEMA)

    def test_exclusion_needs_known_ids_and_reasons(self) -> None:
        """E_SUCC_REDACTION for unknown ids, bad reasons and full exclusion."""
        for exclude in (
            {"ev_000099": "third_party"},
            {"ev_000005": "because"},
            {f"ev_{index:06d}": "private" for index in range(1, 15)},
        ):
            with self.assertRaises(SuccessionError) as caught:
                export_legacy(
                    self.store, self.root / "reject.aiem",
                    policy=self.policy, exclude=exclude,
                )
            self.assertEqual(caught.exception.code, E_SUCC_REDACTION)

    def test_capsule_is_byte_reproducible(self) -> None:
        """C4: the same store and policy produce identical capsule bytes."""
        again = self.root / "again.aiem"
        export_legacy(self.store, again, policy=self.policy, letter=LETTER)
        self.assertEqual(again.read_bytes(), self.plain.read_bytes())

    def test_import_refuses_a_non_empty_target(self) -> None:
        """E_SUCC_IO: importing never overwrites an existing store."""
        target = self.root / "occupied"
        target.mkdir(exist_ok=True)
        (target / "keep.txt").write_text("occupied", encoding="utf-8")
        with self.assertRaises(SuccessionError) as caught:
            import_legacy(self.plain, target)
        self.assertEqual(caught.exception.code, E_SUCC_IO)

    def test_letter_roundtrip(self) -> None:
        """C11: a letter survives its own text form, and malformed input fails."""
        body = LETTER.to_text()
        self.assertEqual(Letter.from_text(body), LETTER)
        with self.assertRaises(SuccessionError) as caught:
            Letter.from_text("who: 甲\nwhen: 2026-01-01\n")
        self.assertEqual(caught.exception.code, E_SUCC_SCHEMA)
        with self.assertRaises(SuccessionError) as caught:
            Letter.from_text("who: 甲\nwhen: 2026-01-01\nto: 乙\n\n   \n")
        self.assertEqual(caught.exception.code, E_SUCC_SCHEMA)

    def test_policy_roundtrip(self) -> None:
        """C11: the shipped policy decodes back to the exact hash inputs."""
        data = policy_bytes(self.policy)
        self.assertEqual(policy_bytes(policy_from_bytes(data)), data)
        self.assertEqual(policy_from_bytes(data).now, NOW)
        with self.assertRaises(SuccessionError) as caught:
            policy_from_bytes(b'{"now": 1}')
        self.assertEqual(caught.exception.code, E_SUCC_SCHEMA)
        with self.assertRaises(SuccessionError) as caught:
            policy_from_bytes(b"not json")
        self.assertEqual(caught.exception.code, E_SUCC_SCHEMA)

    def test_archive_primitives(self) -> None:
        """C11: zip, JSON and evidence helpers behave as the capsule needs."""
        entries = archive.read_zip(self.plain)
        self.assertEqual(sorted(entries), sorted(archive.read_zip(self.plain)))
        self.assertEqual(
            archive.require(entries, "REVIVAL.md"), entries["REVIVAL.md"]
        )
        with self.assertRaises(SuccessionError) as caught:
            archive.require(entries, "missing.json")
        self.assertEqual(caught.exception.code, E_SUCC_HEADER)
        for name in ("chain.json", "evidence/seg-0001.jsonl", "letters/letter-1.txt"):
            self.assertIsNotNone(archive.entry_kind(name))
        self.assertTrue(archive.entry_kind_is_legal("manifest.json"))
        self.assertFalse(archive.entry_kind_is_legal("run.py"))
        evidence = archive.evidence_entries(entries)
        self.assertEqual(archive.count_events(evidence), 14)
        self.assertEqual(
            archive.evidence_digest(evidence), archive.evidence_digest(evidence)
        )
        count, head, segments, events = archive.verify_evidence_set(evidence)
        self.assertEqual(count, 14)
        self.assertEqual(head, segments[-1].last)
        self.assertEqual(len(events), 14)
        self.assertIsNone(archive.blob_list(events))
        self.assertEqual(len(archive.segments_from_chain(archive.read_chain(self.store))), 1)
        with self.assertRaises(SuccessionError) as caught:
            archive.decode_json(b"[]", "x.json", E_SUCC_SCHEMA)
        self.assertEqual(caught.exception.code, E_SUCC_SCHEMA)

    def test_manifest_binds_every_entry(self) -> None:
        """C11: manifest.files lists every entry except the manifest itself."""
        manifest = read_entry(self.plain, "manifest.json")
        listed = [item["path"] for item in manifest["files"]]
        self.assertEqual(listed, sorted(listed))
        self.assertEqual(
            set(listed), set(archive.read_zip(self.plain)) - {"manifest.json"}
        )
        self.assertEqual(manifest["format"], "aiinvite.legacy/1")

    def test_manifest_and_chain_case_is_typed(self) -> None:
        """C11: the declared info type stays what callers receive."""
        info = verify_legacy(self.plain)
        self.assertIsInstance(info, InfoClass)
        self.assertIsInstance(self.info, LegacyInfo)
        chain = read_entry(self.plain, "chain.json")
        self.assertIsNotNone(chain["sealed_at"])
        self.assertEqual(archive.read_chain(self.store)["sealed_at"], chain["sealed_at"])


if __name__ == "__main__":
    unittest.main()
