"""T4: self-comparison, skip counting and the insufficient-conformance floor."""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pcs_fixtures

from jian_pcs.probes import load_probes
from jian_pcs.score import Reply, compute_pcs, score_model


def _replies(probes, pass_count: int) -> dict[str, Reply]:
    return {
        probe.probe_id: Reply(
            probe.probe_id, "scripted",
            pcs_fixtures.reply_for(probe, index < pass_count),
        )
        for index, probe in enumerate(probes)
    }


class TestEdges(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probes = load_probes()

    def test_self_comparison_equals_c(self) -> None:
        """T4: comparing a model with itself yields PCS == C(a)."""
        replies = _replies(self.probes, 20)
        report = compute_pcs(self.probes, replies, replies)
        print(
            f"T4 self C(a)={report.model_a.c:.4f} A={report.agreement:.4f} "
            f"PCS={report.pcs:.4f}"
        )
        self.assertEqual(report.agreement, 1.0)
        self.assertEqual(report.pcs, report.model_a.c)

    def test_skipped_unknown_are_counted(self) -> None:
        """T4: three empty replies are skipped, not counted as passes."""
        replies = _replies(self.probes, 20)
        for probe in self.probes[:3]:
            replies[probe.probe_id] = Reply(probe.probe_id, "scripted", "")
        report = compute_pcs(self.probes, replies, replies)
        score = score_model(self.probes, replies)
        print(
            f"T4 skipped={report.skipped} judged={score.judged} "
            f"skipped_model={score.skipped} C={score.c:.4f}"
        )
        self.assertEqual(report.skipped, 3)
        self.assertEqual(score.skipped, 3)
        self.assertEqual(score.judged, 27)
        self.assertAlmostEqual(score.c, 17 / 27, places=12)

    def test_low_conformance_floors_pcs_to_zero(self) -> None:
        """T4: min(C) < 0.5 forces PCS to 0 with the flag, even when A > 0."""
        replies_a = _replies(self.probes, 10)
        replies_b = _replies(self.probes, 20)
        report = compute_pcs(self.probes, replies_a, replies_b)
        print(
            f"T4 low C(a)={report.model_a.c:.4f} C(b)={report.model_b.c:.4f} "
            f"A={report.agreement:.4f} PCS={report.pcs:.4f} "
            f"insufficient={report.insufficient}"
        )
        self.assertGreater(report.agreement, 0.0)
        self.assertLess(report.model_a.c, 0.5)
        self.assertEqual(report.pcs, 0.0)
        self.assertTrue(report.insufficient)


if __name__ == "__main__":
    unittest.main()
