"""Shared fixtures for PCS tests: scripted replies and rule expectations."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from aiinvite.pcs.probes import Expect, Probe, load_rules_v2


def reply_for(probe: Probe, obey: bool) -> str:
    """Return a scripted compliant or violating reply for one probe."""
    return probe.accept[0] if obey else probe.violation


def expect_of(rule_id: str) -> Expect:
    """Build a probe-free expectation from the rule program (R1-R4, R6)."""
    rule = next(rule for rule in load_rules_v2() if rule.rule_id == rule_id)
    return Expect(
        op=rule.op,
        words=rule.words,
        sentences=rule.sentences,
        questions=rule.questions,
        questions_exact=rule.questions_exact,
        chars=rule.chars,
    )
