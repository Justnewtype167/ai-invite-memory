"""S1: five event types join the verifiable chain with strict schemas."""

from __future__ import annotations

import json
import pathlib
import shutil
import tempfile
import unittest

from aiinvite.capsule import (
    append_event,
    export_capsule,
    import_capsule,
    init_store,
    seal_store,
    verify_path,
)
from aiinvite.errors import E_SCHEMA, AiInviteError
from aiinvite.event import parse_event

STAMP = "2026-10-28T09:00:00Z"


class TestEventTypes(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_ev_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "mem"
        init_store(self.store)

    def _append_all(self) -> list:
        events = [
            append_event(self.store, "user", "早上好", STAMP),
            append_event(
                self.store, type="feedback", kind="praise",
                text="你记得真准", target="ev_000001", t=STAMP,
            ),
            append_event(
                self.store, type="directive", kind="lock",
                text="每周日晚上视频", t=STAMP,
            ),
            append_event(self.store, type="milestone", text="她通过了考试", t=STAMP),
            append_event(self.store, type="checkpoint", text="a" * 64, t=STAMP),
        ]
        return events

    def test_all_types_roundtrip_and_verify(self) -> None:
        """S1: each type parses back, seals, verifies, exports and imports."""
        events = self._append_all()
        self.assertEqual(
            [event.type for event in events],
            ["turn", "feedback", "directive", "milestone", "checkpoint"],
        )
        self.assertEqual(events[1].kind, "praise")
        self.assertEqual(events[1].target, "ev_000001")
        self.assertIsNone(events[3].role)
        self.assertIsNone(events[3].kind)
        lines = (self.store / "evidence" / "seg-0001.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        for line, event in zip(lines, events):
            self.assertEqual(parse_event(json.loads(line)), event)
        seal_store(self.store)
        sealed = verify_path(self.store)
        self.assertEqual(sealed.events, 5)
        capsule = self.root / "mem.aiem"
        export_capsule(self.store, capsule)
        copied = self.root / "copied"
        import_capsule(capsule, copied)
        self.assertEqual(verify_path(copied).events, 5)
        self.assertEqual(verify_path(capsule).events, 5)

    def test_old_signature_still_writes_turn(self) -> None:
        """S1: append_event(store, role, text, t) keeps working."""
        event = append_event(self.store, "assistant", "旧签名可用", STAMP)
        self.assertEqual(event.type, "turn")
        self.assertEqual(event.role, "assistant")
        self.assertIsNone(event.kind)

    def _broken(self, event, change) -> None:
        data = json.loads(event.to_line())
        change(data)
        with self.assertRaises(AiInviteError) as context:
            parse_event(data)
        self.assertEqual(context.exception.code, E_SCHEMA)

    def test_missing_required_field_is_schema_error(self) -> None:
        """S1: a directive without kind is rejected."""
        events = self._append_all()
        self._broken(events[2], lambda data: data.pop("kind"))
        self._broken(events[3], lambda data: data.pop("text"))

    def test_forbidden_field_is_schema_error(self) -> None:
        """S1: role on a directive, kind on a turn, target on a milestone."""
        events = self._append_all()
        self._broken(events[2], lambda data: data.update({"role": "user"}))
        self._broken(events[0], lambda data: data.update({"kind": "lock"}))
        self._broken(events[3], lambda data: data.update({"target": "ev_000001"}))

    def test_bad_type_and_bad_kind(self) -> None:
        """S1: unknown type and unknown kind are both E_SCHEMA."""
        events = self._append_all()
        self._broken(events[0], lambda data: data.update({"type": "notes"}))
        self._broken(events[1], lambda data: data.update({"kind": "neutral"}))
        self._broken(events[1], lambda data: data.update({"target": "ev_1"}))

    def test_new_event_rejects_illegal_combinations(self) -> None:
        """S1: the writer enforces the same schema as the reader."""
        cases = (
            {"type": "directive", "role": "user", "kind": "lock"},
            {"type": "turn", "kind": "lock"},
            {"type": "milestone", "target": "ev_000001"},
            {"type": "feedback"},
        )
        for extra in cases:
            with self.subTest(extra=extra):
                with self.assertRaises(AiInviteError) as context:
                    append_event(self.store, text="x", t=STAMP, **extra)
                self.assertEqual(context.exception.code, E_SCHEMA)


if __name__ == "__main__":
    unittest.main()
