"""T3: PCS matches hand-computed values on three scripted reply sets."""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pcs_fixtures

from aiinvite.pcs.probes import load_probes
from aiinvite.pcs.score import Reply, compute_pcs


def _all(probes, obey: bool) -> dict[str, Reply]:
    return {
        probe.probe_id: Reply(
            probe.probe_id, "scripted", pcs_fixtures.reply_for(probe, obey)
        )
        for probe in probes
    }


class TestScore(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probes = load_probes()

    def test_all_obey_equals_c(self) -> None:
        """T3: when both models pass everything, PCS equals C = 1.0."""
        replies = _all(self.probes, True)
        report = compute_pcs(self.probes, replies, replies)
        print(
            f"T3 all-obey C={report.model_a.c:.4f} A={report.agreement:.4f} "
            f"PCS={report.pcs:.4f}"
        )
        self.assertEqual(report.model_a.c, 1.0)
        self.assertEqual(report.agreement, 1.0)
        self.assertEqual(report.pcs, report.model_a.c)

    def test_both_violate_agreement_one_but_pcs_zero(self) -> None:
        """T3: two models agreeing on every violation gives A=1, PCS=0."""
        replies = _all(self.probes, False)
        report = compute_pcs(self.probes, replies, replies)
        print(
            f"T3 both-violate C(a)={report.model_a.c:.4f} "
            f"C(b)={report.model_b.c:.4f} A={report.agreement:.4f} "
            f"PCS={report.pcs:.4f}"
        )
        self.assertEqual(report.model_a.c, 0.0)
        self.assertEqual(report.model_b.c, 0.0)
        self.assertEqual(report.agreement, 1.0)
        self.assertEqual(report.pcs, 0.0)

    def test_half_obey_matches_hand_count(self) -> None:
        """T3: 20/30 vs 15/30 with 25/30 agreement gives PCS 5/12."""
        replies_a = {}
        replies_b = {}
        for index, probe in enumerate(self.probes):
            obey_a = index < 20
            obey_b = index < 15
            replies_a[probe.probe_id] = Reply(
                probe.probe_id, "a", pcs_fixtures.reply_for(probe, obey_a)
            )
            replies_b[probe.probe_id] = Reply(
                probe.probe_id, "b", pcs_fixtures.reply_for(probe, obey_b)
            )
        report = compute_pcs(self.probes, replies_a, replies_b)
        print(
            f"T3 half C(a)={report.model_a.c:.4f} C(b)={report.model_b.c:.4f} "
            f"A={report.agreement:.4f} PCS={report.pcs:.4f}"
        )
        self.assertAlmostEqual(report.model_a.c, 20 / 30, places=12)
        self.assertAlmostEqual(report.model_b.c, 15 / 30, places=12)
        self.assertAlmostEqual(report.agreement, 25 / 30, places=12)
        self.assertAlmostEqual(report.pcs, (25 / 30) * (15 / 30), places=12)


if __name__ == "__main__":
    unittest.main()
