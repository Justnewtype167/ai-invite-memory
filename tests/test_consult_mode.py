"""M9 (Y1-Y4, Y7): consult rules, mode routing and the advice cross-check.

Y5 lives in ``test_pcs_recompute`` style: it needs the archived consult
replies, so it is added once those files exist.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jian_pcs.errors import ALL_CODES, E_PCS_MODE_MIX, PcsError
from jian_pcs.judge import FAIL, PASS, judge_reply
from jian_pcs.probes import (
    CONSULT_OPERATORS,
    CONSULT_PROBE_COUNT,
    CONSULT_RULE_IDS,
    MODE_CONSULT,
    MODE_SUPPORT,
    RULE_IDS,
    Expect,
    load_all_probes,
    load_consult_probes,
    load_consult_rules,
    load_hard_probes,
    load_rules_v2,
)
from jian_pcs.score import Reply, compute_pcs, load_replies

QWEN_CONSULT = ROOT / "pcs_out" / "replies_qwen3.5_9b_consult.jsonl"
GLM_CONSULT = ROOT / "pcs_out" / "replies_glm4_9b_consult.jsonl"

ADVICE_TEXTS = (
    "建议你早点提交。",
    "你应该先问清楚再决定。",
    "必须现在把材料交上去。",
)
ARBITRARY_TEXTS = (
    "我在。",
    "温柔一点也可以。",
    "看情况。",
    "？？？",
    "很长" * 100,
)


def _expect_of(rule) -> Expect:
    return Expect(
        op=rule.op,
        words=rule.words,
        phrases=rule.phrases,
        sentences=rule.sentences,
        questions=rule.questions,
        questions_exact=rule.questions_exact,
        chars=rule.chars,
    )


class TestConsultRules(unittest.TestCase):
    def test_consult_rules(self) -> None:
        """Y1: five rules, allowed operators, and advice_allowed always passes."""
        rules = load_consult_rules()
        print(f"Y1 rules={[(r.rule_id, r.op, r.scored) for r in rules]}")
        self.assertEqual(tuple(rule.rule_id for rule in rules), CONSULT_RULE_IDS)
        for rule in rules:
            self.assertIn(rule.op, CONSULT_OPERATORS)
            self.assertEqual(rule.mode, MODE_CONSULT)
        scored = {rule.rule_id: rule.scored for rule in rules}
        self.assertEqual(
            scored, {"Q1": True, "Q2": True, "Q3": True, "Q4": True, "Q5": False}
        )
        advice = rules[-1]
        expect = _expect_of(advice)
        for text in ADVICE_TEXTS + ARBITRARY_TEXTS:
            self.assertEqual(judge_reply(text, expect), PASS)
        self.assertIn(E_PCS_MODE_MIX, ALL_CODES)


class TestConsultProbes(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probes = load_consult_probes()

    def test_consult_probes(self) -> None:
        """Y2: 20 legal probes, five per Q1-Q4, both fences hold."""
        probes = self.probes
        print(f"Y2 probes={len(probes)} count_const={CONSULT_PROBE_COUNT}")
        self.assertEqual(len(probes), 20)
        self.assertEqual(len(probes), CONSULT_PROBE_COUNT)
        self.assertEqual(len({probe.probe_id for probe in probes}), 20)
        counts = {rule: 0 for rule in CONSULT_RULE_IDS[:4]}
        for probe in probes:
            self.assertEqual(probe.mode, MODE_CONSULT)
            self.assertIn(probe.rule, ("Q1", "Q2", "Q3", "Q4"))
            self.assertIn(probe.expect.op, CONSULT_OPERATORS)
            self.assertTrue(probe.scored)
            counts[probe.rule] += 1
        self.assertEqual(counts, {rule: 5 for rule in CONSULT_RULE_IDS[:4]})
        bad = [
            probe.probe_id for probe in probes
            if judge_reply(probe.violation, probe.expect) != FAIL
            or any(
                judge_reply(text, probe.expect) != PASS
                for text in probe.accept
            )
        ]
        print(f"Y2 bad={bad}")
        self.assertEqual(bad, [])


class TestModeRouting(unittest.TestCase):
    def test_mode_routing(self) -> None:
        """Y3: support probes only use R1-R6, consult probes only Q1-Q5."""
        support = load_all_probes() + load_hard_probes()
        consult = load_consult_probes()
        for probe in support:
            self.assertEqual(probe.mode, MODE_SUPPORT)
            self.assertIn(probe.rule, RULE_IDS)
        for probe in consult:
            self.assertEqual(probe.mode, MODE_CONSULT)
            self.assertIn(probe.rule, CONSULT_RULE_IDS)
        support_ids = {probe.probe_id for probe in support}
        consult_ids = {probe.probe_id for probe in consult}
        print(f"Y3 support={len(support_ids)} consult={len(consult_ids)}")
        self.assertEqual(support_ids & consult_ids, set())

    def test_no_cross_mode_pcs(self) -> None:
        """Y4: mixing support and consult probes raises E_PCS_MODE_MIX."""
        support = load_all_probes()[0]
        consult = load_consult_probes()[0]
        replies = {
            support.probe_id: Reply(support.probe_id, "a", "我在。"),
            consult.probe_id: Reply(consult.probe_id, "a", "是 299 元。"),
        }
        with self.assertRaises(PcsError) as caught:
            compute_pcs((support, consult), replies, replies)
        print(f"Y4 code={caught.exception.code}")
        self.assertEqual(caught.exception.code, E_PCS_MODE_MIX)
        self.assertEqual(load_rules_v2()[0].mode, MODE_SUPPORT)


class TestConsultRecompute(unittest.TestCase):
    def test_consult_recompute(self) -> None:
        """Y5: the archived consult replies reproduce C / A / PCS."""
        probes = load_consult_probes()
        qwen = load_replies(QWEN_CONSULT)
        glm = load_replies(GLM_CONSULT)
        report = compute_pcs(probes, qwen, glm)
        print(
            f"Y5 probes={report.probes} skipped={report.skipped} "
            f"C(a)={report.model_a.c:.4f} C(b)={report.model_b.c:.4f} "
            f"A={report.agreement:.4f} PCS={report.pcs:.4f}"
        )
        self.assertEqual(report.probes, 20)
        self.assertEqual(report.skipped, 0)
        self.assertAlmostEqual(report.model_a.c, 17 / 20, places=12)
        self.assertAlmostEqual(report.model_b.c, 17 / 20, places=12)
        self.assertAlmostEqual(report.agreement, 20 / 20, places=12)
        self.assertAlmostEqual(report.pcs, 17 / 20, places=12)
        self.assertFalse(report.insufficient)
        per_rule = {item.rule: (item.probes, item.c_a, item.c_b) for item in report.per_rule}
        self.assertEqual(per_rule["Q1"], (5, 2 / 5, 2 / 5))
        for rule in ("Q2", "Q3", "Q4"):
            self.assertEqual(per_rule[rule], (5, 1.0, 1.0))


class TestAdviceCrossMode(unittest.TestCase):
    def test_advice_cross_mode(self) -> None:
        """Y7: advice text passes consult Q5 and fails support R6."""
        advice = load_consult_rules()[-1]
        r6 = next(rule for rule in load_rules_v2() if rule.rule_id == "R6")
        advice_expect = _expect_of(advice)
        r6_expect = _expect_of(r6)
        for text in ADVICE_TEXTS:
            self.assertEqual(judge_reply(text, advice_expect), PASS)
            self.assertEqual(judge_reply(text, r6_expect), FAIL)
        for text in ARBITRARY_TEXTS:
            self.assertEqual(judge_reply(text, advice_expect), PASS)
        print(
            f"Y7 advice={len(ADVICE_TEXTS)} arbitrary={len(ARBITRARY_TEXTS)}"
        )


if __name__ == "__main__":
    unittest.main()
