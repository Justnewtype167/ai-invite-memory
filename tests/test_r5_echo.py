"""W1: every R5 probe carries the user's last sentence as ``echo_source``."""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from jian_pcs.probes import load_all_probes, load_rules_v2


class TestR5Echo(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probes = load_all_probes()
        cls.rules = {rule.rule_id: rule for rule in load_rules_v2()}

    def test_r5_echo_source(self) -> None:
        """W1: all 14 scored R5 probes fill echo_source from their own input."""
        r5 = [probe for probe in self.probes if probe.rule == "R5"]
        problems = []
        for probe in r5:
            source = probe.expect.echo_source
            if not source.strip():
                problems.append((probe.probe_id, "empty"))
                continue
            if probe.expect.op != self.rules["R5"].op:
                problems.append((probe.probe_id, "op-mismatch"))
            expected = probe.turns[-1] if probe.turns else probe.prompt
            if source != expected:
                problems.append((probe.probe_id, "not-user-last-turn"))
        print(f"W1 r5={len(r5)} problems={problems}")
        self.assertEqual(len(r5), 14)
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
