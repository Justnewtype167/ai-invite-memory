"""PCS: behavioural identity across models. Zero dependencies, zero network."""

from __future__ import annotations

from jian_pcs.errors import (
    E_PCS_IO,
    E_PCS_SCHEMA,
    PcsError,
)
from jian_pcs.judge import (
    FAIL,
    PASS,
    UNKNOWN,
    accepts_pass,
    judge_reply,
    violation_rejected,
)
from jian_pcs.probes import (
    AskBefore,
    Expect,
    Probe,
    load_all_probes,
    load_hard_probes,
    load_probes,
    validate_expect,
)
from jian_pcs.report import render_report
from jian_pcs.score import (
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
    "AskBefore",
    "CollapseScore",
    "Expect",
    "FAIL",
    "ModelScore",
    "PASS",
    "PcsError",
    "PcsReport",
    "Probe",
    "Reply",
    "RuleScore",
    "UNKNOWN",
    "accepts_pass",
    "compute_pcs",
    "judge_reply",
    "load_all_probes",
    "load_hard_probes",
    "load_probes",
    "load_replies",
    "render_report",
    "score_collapse",
    "score_model",
    "validate_expect",
    "violation_rejected",
]
