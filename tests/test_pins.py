"""P1-P5: the unforgettable layer really is unforgettable."""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.capsule import append_event, init_store, seal_store
from aiinvite.host import HostSession
from aiinvite.kernel.compiler import compile_kernel, read_evidence
from aiinvite.kernel.kernel import Policy
from aiinvite.persona.pins import MAX_PINS, derive_pins
from aiinvite.recall.tokenizer import estimate_tokens

STAMP = "2026-11-01T09:00:00+08:00"
NOW = "2026-11-01T12:00:00+08:00"


class TestPins(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="pins_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "m"
        init_store(self.store)
        self.fact = append_event(
            self.store, "user", "我的狗叫阿黄，它去年走了", STAMP
        )

    def _session(self, budget=4096, caller=None):
        return HostSession(
            self.store, "glm4:9b", budget=budget, now=NOW,
        )

    def test_p1_pin_survives_a_tight_budget(self) -> None:
        """P1: with 300 tokens the pin is still there and memory shrinks."""
        session = self._session(budget=300)
        session.pin(self.fact)
        prompt = session.prompt_for("你还记得我的狗吗")
        self.assertIn("阿黄", prompt)
        self.assertLessEqual(estimate_tokens(prompt), 300)
        self.assertIn("## never forget", prompt)

    def test_p2_pins_are_recomputable(self) -> None:
        """P2: deleting derived data changes nothing; pins come from evidence."""
        session = self._session()
        session.pin(self.fact)
        first = [pin.event_id for pin in derive_pins(read_evidence(self.store))]
        for stale in (".index", "kernel"):
            target = self.store / stale
            if target.exists():
                shutil.rmtree(target)
        second = [pin.event_id for pin in derive_pins(read_evidence(self.store))]
        self.assertEqual(first, second)

    def test_p3_pins_do_not_move_identity(self) -> None:
        """P3: pinning changes no kernel artifact, so the kid is unchanged."""
        before = compile_kernel(self.store, Policy(now=NOW))
        session = self._session()
        session.pin(self.fact)
        after = compile_kernel(self.store, Policy(now=NOW))
        self.assertEqual(before.kid, after.kid)
        self.assertEqual(before.canon, after.canon)
        self.assertEqual(before.self_md, after.self_md)

    def test_p4_unpin_removes_it(self) -> None:
        """P4: after unpin the memory is no longer forced into the prompt."""
        session = self._session()
        session.pin(self.fact)
        self.assertIn("阿黄", session.prompt_for("在吗"))
        session.unpin(self.fact)
        self.assertNotIn("## never forget", session.prompt_for("在吗"))

    def test_p5_unknown_target_is_ignored(self) -> None:
        """P5: a pin pointing at a missing event is skipped, not fatal."""
        session = self._session()
        session.pin("ev_999999")
        prompt = session.prompt_for("在吗")
        self.assertNotIn("## never forget", prompt)

    def test_cap_is_enforced(self) -> None:
        """P6: too many pins stops at the cap instead of eating the budget."""
        for index in range(MAX_PINS + 4):
            event = append_event(
                self.store, "user", "第" + str(index) + "件小事", STAMP
            )
            self._session().pin(event)
        pins = derive_pins(read_evidence(self.store))
        self.assertLessEqual(len(pins), MAX_PINS)


if __name__ == "__main__":
    unittest.main()
