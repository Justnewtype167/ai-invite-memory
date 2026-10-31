"""V5: recompute PCS for both models from the archived replies, reproducibly."""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from jian_pcs.probes import load_all_probes, load_hard_probes
from jian_pcs.report import render_report
from jian_pcs.score import compute_pcs, load_replies

ROOT = pathlib.Path(__file__).resolve().parents[1]
QWEN_MAIN = ROOT / "pcs_out" / "replies_qwen3.5_9b_80.jsonl"
GLM_MAIN = ROOT / "pcs_out" / "replies_glm4_9b_80.jsonl"
QWEN_HARD = ROOT / "experiments" / "replies" / "m7_qwen.jsonl"
GLM_HARD = ROOT / "experiments" / "replies" / "m7_glm.jsonl"


class TestPcsRecompute(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probes = load_all_probes()
        cls.hard = load_hard_probes()
        cls.qwen = load_replies(QWEN_MAIN)
        cls.glm = load_replies(GLM_MAIN)
        cls.qwen_hard = load_replies(QWEN_HARD)
        cls.glm_hard = load_replies(GLM_HARD)
        cls.report = compute_pcs(cls.probes, cls.qwen, cls.glm)
        cls.hard_report = compute_pcs(cls.hard, cls.qwen_hard, cls.glm_hard)

    def test_recompute_matches_archived_replies(self) -> None:
        """V5: 80 probes, no skips, and the hand-checked v2 numbers."""
        report = self.report
        print(
            f"V5 probes={report.probes} skipped={report.skipped} "
            f"C(a)={report.model_a.c:.4f} C(b)={report.model_b.c:.4f} "
            f"A={report.agreement:.4f} PCS={report.pcs:.4f}"
        )
        self.assertEqual(report.probes, 80)
        self.assertEqual(report.skipped, 0)
        self.assertAlmostEqual(report.model_a.c, 69 / 80, places=12)
        self.assertAlmostEqual(report.model_b.c, 67 / 80, places=12)
        self.assertAlmostEqual(report.agreement, 62 / 80, places=12)
        self.assertFalse(report.insufficient)
        self.assertAlmostEqual(
            report.pcs, (62 / 80) * (67 / 80), places=12
        )

    def test_hard_set_numbers(self) -> None:
        """V5: the multi-turn subset and its R/D collapse statistics."""
        report = self.hard_report
        print(
            f"V5 hard={report.probes} "
            f"C_final(a)={report.final_a.c:.4f} "
            f"C_final(b)={report.final_b.c:.4f} "
            f"R(a)={report.collapse_a.r:.4f} D(a)={report.collapse_a.d:.4f} "
            f"R(b)={report.collapse_b.r:.4f} D(b)={report.collapse_b.d:.4f}"
        )
        self.assertEqual(report.probes, 18)
        self.assertAlmostEqual(report.final_a.c, 12 / 18, places=12)
        self.assertAlmostEqual(report.final_b.c, 9 / 18, places=12)
        self.assertAlmostEqual(report.collapse_a.r, 7 / 18, places=12)
        self.assertAlmostEqual(report.collapse_b.r, 13 / 18, places=12)
        self.assertIsNotNone(report.collapse_a.d)
        self.assertIsNotNone(report.collapse_b.d)

    def test_report_is_byte_identical(self) -> None:
        """V5: judging the same replies twice yields identical report bytes."""
        first = render_report(compute_pcs(self.probes, self.qwen, self.glm))
        second = render_report(compute_pcs(self.probes, self.qwen, self.glm))
        hard_first = render_report(
            compute_pcs(self.hard, self.qwen_hard, self.glm_hard)
        )
        hard_second = render_report(
            compute_pcs(self.hard, self.qwen_hard, self.glm_hard)
        )
        print(
            f"V5 bytes={len(first.encode('utf-8'))} identical={first == second} "
            f"hard-identical={hard_first == hard_second}"
        )
        self.assertEqual(first, second)
        self.assertEqual(hard_first, hard_second)
        for label in ("C(a)", "C(b)", "A(a,b)", "PCS"):
            self.assertIn(label, first)
        for label in ("C_final(a)", "R(a)", "D(a)"):
            self.assertIn(label, hard_first)


if __name__ == "__main__":
    unittest.main()
