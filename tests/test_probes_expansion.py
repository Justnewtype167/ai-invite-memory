"""X1-X6: the 30+30+20 probe expansion and the R3 exact-question semantics."""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from jian_pcs.judge import FAIL, PASS, accepts_pass, judge_reply, violation_rejected
from jian_pcs.probes import (
    RULE_IDS,
    Expect,
    PROBE_FIELDS,
    load_all_probes,
    load_more_probes,
    load_probes,
    load_real_probes,
    load_rules_v2,
)


class TestProbeExpansion(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.more = load_more_probes()
        cls.real = load_real_probes()
        cls.rules = {rule.rule_id: rule for rule in load_rules_v2()}

    def test_probes_more_schema(self) -> None:
        """X1: 30 new probes, complete fields, unique ids, five per rule."""
        ids = [probe.probe_id for probe in self.more]
        base_ids = {probe.probe_id for probe in load_probes()}
        print(f"X1 more={len(ids)} overlap={sorted(set(ids) & base_ids)}")
        self.assertEqual(len(ids), 30)
        self.assertEqual(len(set(ids)), 30)
        self.assertEqual(set(ids) & base_ids, set())
        counts = {rule: 0 for rule in RULE_IDS}
        for probe in self.more:
            self.assertIn(probe.rule, RULE_IDS)
            counts[probe.rule] += 1
            self.assertIn(probe.expect.op, self._operator(probe.rule))
            self.assertGreaterEqual(len(probe.accept), 2)
            self.assertLessEqual(len(probe.accept), 3)
            self.assertTrue(probe.violation.strip())
        print(f"X1 per-rule={counts}")
        self.assertEqual(counts, {rule: 5 for rule in RULE_IDS})

    def test_probes_more_judge(self) -> None:
        """X2: 120 assertions -- every accept passes, every violation fails."""
        checked = 0
        for probe in self.more:
            for text in probe.accept:
                self.assertEqual(judge_reply(text, probe.expect), PASS, probe.probe_id)
                checked += 1
            self.assertEqual(judge_reply(probe.violation, probe.expect), FAIL,
                             probe.probe_id)
            checked += 1
        print(f"X2 assertions={checked}")
        self.assertEqual(checked, 120)
        self.assertTrue(all(accepts_pass(probe) for probe in self.more))
        self.assertTrue(all(violation_rejected(probe) for probe in self.more))

    def test_r3_exact(self) -> None:
        """X3: exact=true needs exactly one question; default stays 'at most'."""
        exact = Expect(
            op="max_sentences_and_questions",
            sentences=2,
            questions=1,
            questions_exact=True,
        )
        lenient = Expect(
            op="max_sentences_and_questions",
            sentences=2,
            questions=1,
        )
        print(
            "X3 zero-question exact="
            f"{judge_reply('我在。你先说。', exact)} "
            f"lenient={judge_reply('我在。你先说。', lenient)}"
        )
        self.assertEqual(judge_reply("我在。你先说。", exact), FAIL)
        self.assertEqual(judge_reply("我在。你先说。", lenient), PASS)
        self.assertEqual(judge_reply("我在。你先说，哪里最累？", exact), PASS)
        self.assertEqual(judge_reply("你怎么样？要不要说说？", exact), FAIL)
        self.assertTrue(self.rules["R3"].questions_exact)
        self.assertEqual(self.rules["R3"].questions, 1)
        self.assertEqual(self.rules["R3"].sentences, 2)

    def test_all_probes_80(self) -> None:
        """X4/X6: base 30 + more 30 + real 20, every id unique."""
        merged = load_all_probes()
        ids = [probe.probe_id for probe in merged]
        print(f"X4 base={len(load_probes())} more={len(self.more)} "
              f"real={len(self.real)} merged={len(ids)}")
        self.assertEqual(len(merged), 80)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(load_probes()), 30)
        self.assertEqual(len(self.real), 20)

    def test_real_probes_use_v2_rules(self) -> None:
        """X6: the 20 colloquial probes are bound to R1-R6 and both fences."""
        bad = [
            probe.probe_id for probe in self.real
            if probe.rule not in RULE_IDS
            or probe.expect.op != self.rules[probe.rule].op
        ]
        survived = [probe.probe_id for probe in self.real
                    if not violation_rejected(probe)]
        print(f"X6 real={len(self.real)} bad={bad} survived={survived}")
        self.assertEqual(len(self.real), 20)
        self.assertEqual(bad, [])
        self.assertEqual(survived, [])
        missing = [
            name for name in PROBE_FIELDS if not hasattr(self.real[0], name)
        ]
        self.assertEqual(missing, [])

    def _operator(self, rule_id: str) -> str:
        return self.rules[rule_id].op


if __name__ == "__main__":
    unittest.main()
