"""T1-T8: a torn tail stops the next write instead of corrupting the chain."""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.capsule import append_event, init_store
from aiinvite.chain import check_tail
from aiinvite.errors import E_CHAIN_MISSING, E_SCHEMA, E_TAMPER, AiInviteError
from aiinvite.host import HostSession

STAMP = "2026-11-01T09:00:00+08:00"
NOW = "2026-11-01T12:00:00+08:00"


class TestCheckTail(unittest.TestCase):
    """The cheap check: last segment only, runs on every open."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="tail_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "m"
        init_store(self.store)
        self.segment = self.store / "evidence" / "seg-0001.jsonl"
        self.chain_path = self.store / "chain.json"

    def _append(self, count=2):
        for index in range(count):
            append_event(self.store, "user", f"第{index}句", STAMP)

    def _chain(self) -> dict:
        return json.loads(self.chain_path.read_text(encoding="utf-8"))

    def _assert_code(self, code, func=check_tail):
        with self.assertRaises(AiInviteError) as caught:
            func(self.store)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_t1_empty_store_is_intact(self) -> None:
        """T1: a store with no events has a valid empty tail."""
        check_tail(self.store)

    def test_t2_consistent_store_passes(self) -> None:
        """T2: the normal case costs nothing and reports nothing."""
        self._append()
        check_tail(self.store)

    def test_t3_extra_line_in_the_segment(self) -> None:
        """T3: a line written before the chain commit leaves a stale count."""
        self._append()
        append_event(self.store, "user", "被中断的一句", STAMP)
        chain = self._chain()
        chain["segments"][-1]["count"] = 2
        self.chain_path.write_text(json.dumps(chain), encoding="utf-8")
        self._assert_code(E_CHAIN_MISSING)

    def test_t4_half_line_at_the_end(self) -> None:
        """T4: a torn write is refused before the next append seals the damage."""
        self._append()
        with self.segment.open("ab") as handle:
            handle.write(b'{"ep":"seg-0001","hash":"')
        self._assert_code(E_SCHEMA)

    def test_t5_chain_points_at_a_missing_segment(self) -> None:
        """T5: a segment that vanished is not silently recreated."""
        self._append()
        self.segment.unlink()
        self._assert_code(E_CHAIN_MISSING)

    def test_t6_segment_the_chain_never_recorded(self) -> None:
        """T6: a stray segment means a crash or an edit; both need a human."""
        self._append()
        (self.store / "evidence" / "seg-0002.jsonl").write_text("", encoding="utf-8")
        self._assert_code(E_CHAIN_MISSING)

    def test_t7_tail_event_no_longer_matches_the_chain(self) -> None:
        """T7: the last line is parsed, so an edited tail is caught here."""
        self._append()
        lines = self.segment.read_text(encoding="utf-8").splitlines()
        lines[-1] = lines[-1].replace("第1句", "第9句")
        self.segment.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._assert_code(E_TAMPER)

    def test_t8_host_session_refuses_a_torn_store(self) -> None:
        """T8: the refusal reaches the caller of the API, not just the checker."""
        self._append()
        chain = self._chain()
        chain["segments"][-1]["count"] = 1
        self.chain_path.write_text(json.dumps(chain), encoding="utf-8")
        self._assert_code(E_CHAIN_MISSING, lambda store: HostSession(store, "glm4:9b", now=NOW))

    def test_t9_a_normal_store_opens(self) -> None:
        """T9: the check does not get in the way of an intact store."""
        self._append()
        session = HostSession(self.store, "glm4:9b", now=NOW)
        self.assertIn("## this turn", session.prompt_for("你好"))


if __name__ == "__main__":
    unittest.main()
