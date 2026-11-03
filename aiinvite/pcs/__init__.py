"""PCS: behavioural identity across models. Zero dependencies, zero network."""

from __future__ import annotations

from aiinvite.pcs.errors import (
    E_PCS_IO,
    E_PCS_SCHEMA,
    PcsError,
)
from aiinvite.pcs.judge import (
    FAIL,
    PASS,
    UNKNOWN,
    accepts_pass,
    judge_reply,
    violation_rejected,
)
from aiinvite.pcs.probes import (
    Expect,
    Probe,
    Rule,
    load_all_probes,
    load_hard_probes,
    load_probes,
    load_rules_v2,
    validate_expect,
)
from aiinvite.pcs.report import render_report
from aiinvite.pcs.score import (
    CollapseScore,
    ModelScore,
    PcsReport,
    RuleScore,
    Reply,
    compute_pcs,
    load_replies,
    score_collapse,
    score_model,
)

__all__ = [
    "E_PCS_IO",
    "E_PCS_SCHEMA",
    "CollapseScore",
    "Expect",
    "FAIL",
    "ModelScore",
    "PASS",
    "PcsError",
    "PcsReport",
    "Probe",
    "Reply",
    "Rule",
    "RuleScore",
    "UNKNOWN",
    "accepts_pass",
    "compute_pcs",
    "judge_reply",
    "load_all_probes",
    "load_hard_probes",
    "load_probes",
    "load_replies",
    "load_rules_v2",
    "render_report",
    "score_collapse",
    "score_model",
    "validate_expect",
    "violation_rejected",
]
