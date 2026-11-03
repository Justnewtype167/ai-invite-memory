"""V3: all 80 scored probes are bound to R1-R6 and satisfy both fences."""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from aiinvite.pcs.judge import FAIL, PASS, accepts_pass, judge_reply, violation_rejected
from aiinvite.pcs.probes import (
    RULE_IDS,
    load_all_probes,
    load_probes,
    load_rules_v2,
)


class TestProbesV3(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probes = load_all_probes()
        cls.rules = {rule.rule_id: rule for rule in load_rules_v2()}

    def test_all_probes_use_v2_rule_ids(self) -> None:
        """V3: every probe names one of R1-R6 and echoes its operator."""
        bad = []
        for probe in self.probes:
            if probe.rule not in RULE_IDS:
                bad.append((probe.probe_id, probe.rule))
                continue
            if probe.expect.op != self.rules[probe.rule].op:
                bad.append((probe.probe_id, "op-mismatch"))
        print(f"V3 probes={len(self.probes)} bad={bad}")
        self.assertEqual(len(self.probes), 80)
        self.assertEqual(bad, [])

    def test_accept_passes_and_violation_fails(self) -> None:
        """V3: every legal wording passes and every known violation fails."""
        bad_accept = [
            (probe.probe_id, text)
            for probe in self.probes
            for text in probe.accept
            if judge_reply(text, probe.expect) != PASS
        ]
        survived = [
            probe.probe_id
            for probe in self.probes
            if not violation_rejected(probe)
        ]
        print(f"V3 bad_accept={bad_accept} survived={survived}")
        self.assertEqual(bad_accept, [])
        self.assertEqual(survived, [])
        self.assertTrue(all(accepts_pass(probe) for probe in self.probes))
        self.assertTrue(all(judge_reply(probe.violation, probe.expect) == FAIL
                            for probe in self.probes))

    def test_r5_echo_source(self) -> None:
        """V3: R5 carries the user's last sentence and it matches the input."""
        r5 = [probe for probe in self.probes if probe.rule == "R5"]
        problems = []
        for probe in r5:
            source = probe.expect.echo_source
            if not source.strip():
                problems.append((probe.probe_id, "empty"))
            if source != probe.prompt:
                problems.append((probe.probe_id, source, probe.prompt))
        print(f"V3 r5 probes={len(r5)} problems={problems}")
        self.assertEqual(len(r5), 14)
        self.assertEqual(problems, [])

    def test_merged_ids_are_unique(self) -> None:
        """V3: the M6 set stays at 30 and merged ids never collide."""
        m6 = load_probes()
        ids = [probe.probe_id for probe in self.probes]
        print(f"V3 m6={len(m6)} merged={len(ids)} unique={len(set(ids))}")
        self.assertEqual(len(m6), 30)
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
