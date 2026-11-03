"""Q3: a proposal needs ten turn/feedback events; nine is refused."""

from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import kn_fixtures

from aiinvite.kernel.errors import E_KN_THIN_EVIDENCE, KernelError
from aiinvite.kernel.proposer import record_proposal

STAMP = "2026-10-29T02:00:00Z"
TEXT = "回答前先停半秒"


class TestThinEvidence(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_q3_"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _count(self) -> int:
        folder = self.root / "evidence"
        return sum(
            len([line for line in path.read_text(encoding="utf-8").splitlines() if line])
            for path in folder.glob("seg-*.jsonl")
        )

    def test_nine_events_are_refused(self) -> None:
        """Q3: nine turns raise E_KN_THIN_EVIDENCE and write nothing."""
        kn_fixtures.write_store(self.root, kn_fixtures.chat_turns(9))
        before = self._count()
        with self.assertRaises(KernelError) as caught:
            record_proposal(self.root, "self.style", TEXT, "m", "ab12cd34", STAMP)
        print(f"Q3 nine -> {caught.exception.code} before={before} after={self._count()}")
        self.assertEqual(caught.exception.code, E_KN_THIN_EVIDENCE)
        self.assertEqual(self._count(), before)

    def test_ten_turns_are_enough(self) -> None:
        """Q3: ten turns let one proposal through."""
        kn_fixtures.write_store(self.root, kn_fixtures.chat_turns(10))
        event = record_proposal(
            self.root, "self.style", TEXT, "m", "ab12cd34", STAMP
        )
        print(f"Q3 ten -> {event.event_id}")
        self.assertEqual(event.event_id, "ev_000011")

    def test_turns_plus_feedback_are_counted(self) -> None:
        """Q3: one feedback event counts, so nine turns plus one is enough."""
        events = kn_fixtures.chat_turns(9) + [
            ("2026-03-01T09:00:00Z", "谢谢你记得", "feedback", "praise"),
        ]
        kn_fixtures.write_store(self.root, events)
        event = record_proposal(
            self.root, "self.style", TEXT, "m", "ab12cd34", STAMP
        )
        print(f"Q3 nine+feedback -> {event.event_id}")
        self.assertEqual(event.event_id, "ev_000011")


if __name__ == "__main__":
    unittest.main()
