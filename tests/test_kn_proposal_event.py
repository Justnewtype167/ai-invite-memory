"""P1: ``proposal`` is the sixth event type with target/model/prompt_sha."""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import kn_fixtures

from jian.errors import E_SCHEMA, JianError
from jian.event import new_event, parse_event
from jian_kernel.proposer import record_proposal

STAMP = "2026-10-29T02:00:00Z"


class TestProposalEvent(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_prop_ev_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        kn_fixtures.write_store(self.root, [
            ("2026-01-01T09:00:00Z", "今天天气不错", "turn", None),
            *kn_fixtures.chat_turns(9),
        ])

    def _last_line(self) -> dict[str, object]:
        path = self.root / "evidence" / "seg-0001.jsonl"
        last = [line for line in path.read_text(encoding="utf-8").splitlines() if line][-1]
        return json.loads(last)

    def test_round_trip(self) -> None:
        """P1: a proposal event round-trips through parse_event."""
        event = record_proposal(
            self.root, "self.style", "说话时慢一点", "deepseek-v4", "ab12cd34", STAMP
        )
        data = self._last_line()
        parsed = parse_event(data)
        print(
            f"P1 id={event.event_id} type={parsed.type} target={parsed.target} "
            f"model={parsed.model} prompt_sha={parsed.prompt_sha}"
        )
        self.assertEqual(event.event_id, "ev_000011")
        self.assertEqual(parsed.type, "proposal")
        self.assertEqual(parsed.target, "self.style")
        self.assertEqual(parsed.model, "deepseek-v4")
        self.assertEqual(parsed.prompt_sha, "ab12cd34")
        self.assertEqual(parsed.text, "说话时慢一点")
        self.assertIsNone(parsed.role)
        self.assertIsNone(parsed.kind)

    def test_missing_required_fields_are_schema(self) -> None:
        """P1: missing model / prompt_sha and a stray role are E_SCHEMA."""
        record_proposal(
            self.root, "self.style", "说话时慢一点", "deepseek-v4", "ab12cd34", STAMP
        )
        data = self._last_line()
        cases: list[tuple[str, dict[str, object]]] = []
        for field in ("model", "prompt_sha", "target"):
            broken = dict(data)
            broken.pop(field)
            cases.append((f"missing {field}", broken))
        with_role = dict(data)
        with_role["role"] = "user"
        cases.append(("role present", with_role))
        for label, body in cases:
            with self.assertRaises(JianError) as caught:
                parse_event(body)
            print(f"P1 {label} -> {caught.exception.code}")
            self.assertEqual(caught.exception.code, E_SCHEMA)

    def test_new_event_rejects_role_and_kind(self) -> None:
        """P1: new_event rejects role/kind on a proposal before hashing."""
        for role, kind in (("user", None), (None, "note")):
            with self.assertRaises(JianError) as caught:
                new_event(
                    2, "seg-0001", STAMP, role, "x", "0" * 64,
                    type="proposal", kind=kind, target="self.style", model="m",
                    prompt_sha="ab",
                )
            print(f"P1 role={role} kind={kind} -> {caught.exception.code}")
            self.assertEqual(caught.exception.code, E_SCHEMA)


if __name__ == "__main__":
    unittest.main()
