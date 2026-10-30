"""U3: collapse rate R and normalized depth D from scripted multi-turn groups."""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from jian_pcs.probes import load_hard_probes
from jian_pcs.score import Reply, score_collapse


class TestCollapse(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        probe = next(
            p for p in load_hard_probes()
            if p.kind == "multi_turn" and len(p.turns) >= 4
        )
        cls.probe = probe
        cls.turns = len(probe.turns)
        cls.good = probe.accept[0]
        cls.bad = probe.violation

    def _reply(self, texts: list[str]) -> Reply:
        return Reply(
            self.probe.probe_id, "scripted", texts[-1], 0, 42, tuple(texts)
        )

    def test_steady_to_the_end(self) -> None:
        """U3: no violation -> R=0 and D is n/a, never a full-turn count."""
        reply = self._reply([self.good] * self.turns)
        score = score_collapse((self.probe,), {self.probe.probe_id: reply})
        print(f"U3 steady r={score.r} d={score.d}")
        self.assertEqual(score.replied, 1)
        self.assertEqual(score.violating, 0)
        self.assertEqual(score.r, 0.0)
        self.assertIsNone(score.d)

    def test_collapse_at_turn_three(self) -> None:
        """U3: first violation on turn 3 -> D = 3 / total turns."""
        texts = [self.good, self.good, self.bad] + [self.good] * (self.turns - 3)
        reply = self._reply(texts)
        score = score_collapse((self.probe,), {self.probe.probe_id: reply})
        expected = 3.0 / self.turns
        print(f"U3 collapse turn=3 d={score.d} expected={expected}")
        self.assertEqual(score.r, 1.0)
        self.assertAlmostEqual(score.d, expected, places=12)

    def test_collapse_at_turn_one(self) -> None:
        """U3: violating from the first reply -> D = 1 / total turns."""
        reply = self._reply([self.bad] * self.turns)
        score = score_collapse((self.probe,), {self.probe.probe_id: reply})
        expected = 1.0 / self.turns
        print(f"U3 collapse turn=1 d={score.d} expected={expected}")
        self.assertEqual(score.r, 1.0)
        self.assertAlmostEqual(score.d, expected, places=12)

    def test_collapse_on_last_turn_differs_from_steady(self) -> None:
        """U3: a last-turn collapse scores 1.0, not the steady full-turn count."""
        texts = [self.good] * (self.turns - 1) + [self.bad]
        reply = self._reply(texts)
        collapsed = score_collapse((self.probe,), {self.probe.probe_id: reply})
        steady = score_collapse(
            (self.probe,),
            {self.probe.probe_id: self._reply([self.good] * self.turns)},
        )
        print(f"U3 last-turn d={collapsed.d} steady d={steady.d}")
        self.assertEqual(collapsed.r, 1.0)
        self.assertAlmostEqual(collapsed.d, 1.0, places=12)
        self.assertIsNone(steady.d)

    def test_mean_across_steered_probes(self) -> None:
        """U3: D averages violating probes only; steady ones do not dilute it."""
        others = [
            p for p in load_hard_probes()
            if p.kind == "multi_turn" and p.probe_id != self.probe.probe_id
        ][:1]
        steady = self._reply([self.good] * self.turns)
        collapsed = Reply(
            others[0].probe_id, "scripted", others[0].violation, 0, 42,
            (others[0].violation,) * len(others[0].turns),
        )
        score = score_collapse(
            (self.probe, others[0]),
            {self.probe.probe_id: steady, others[0].probe_id: collapsed},
        )
        expected = 1.0 / len(others[0].turns)
        print(f"U3 mean r={score.r} d={score.d} expected={expected}")
        self.assertEqual(score.replied, 2)
        self.assertEqual(score.violating, 1)
        self.assertEqual(score.r, 0.5)
        self.assertAlmostEqual(score.d, expected, places=12)

    def test_missing_reply_is_skipped_not_stable(self) -> None:
        """U3: a missing reply is excluded, so it cannot inflate stability."""
        steady = self._reply([self.good] * self.turns)
        score = score_collapse((self.probe,), {self.probe.probe_id: steady})
        print(f"U3 replied={score.replied} skipped={score.skipped}")
        self.assertEqual(score.replied, 1)
        self.assertEqual(score.skipped, 0)
        absent = score_collapse((self.probe,), {})
        print(f"U3 absent replied={absent.replied} skipped={absent.skipped}")
        self.assertEqual(absent.replied, 0)
        self.assertEqual(absent.skipped, 1)
        self.assertEqual(absent.r, 0.0)
        self.assertIsNone(absent.d)


if __name__ == "__main__":
    unittest.main()
