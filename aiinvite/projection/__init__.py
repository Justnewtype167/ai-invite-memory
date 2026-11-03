"""Deterministic projections from a persona kernel to output traces (M11)."""

from __future__ import annotations

from aiinvite.projection.action import (
    ActionMap,
    ActionRule,
    load_action_map,
    project_action,
)
from aiinvite.projection.emit import EMIT_MODES, emit, trace_digest
from aiinvite.projection.errors import E_PR_UNKNOWN_PROJECTOR, ProjectionError
from aiinvite.projection.gate import (
    GateRule,
    GateRules,
    Verdict,
    check,
    load_gate_rules,
)
from aiinvite.projection.text import project_text
from aiinvite.projection.trace import (
    ACTION_WHITELIST,
    PROJECTORS,
    SEGMENT_KINDS,
    Segment,
    Trace,
)

__all__ = [
    "ACTION_WHITELIST",
    "ActionMap",
    "ActionRule",
    "EMIT_MODES",
    "GateRule",
    "GateRules",
    "PROJECTORS",
    "ProjectionError",
    "SEGMENT_KINDS",
    "Segment",
    "Trace",
    "Verdict",
    "check",
    "emit",
    "load_action_map",
    "load_gate_rules",
    "project",
    "project_action",
    "project_text",
    "trace_digest",
]


def project(kernel: object, projector: str) -> Trace:
    """Project one kernel object through a named projector.

    Only the kernel object is accepted: a store, a path or evidence is never
    passed to a projector, which is what invariant I1 asserts.
    """
    if projector == "text_v1":
        return project_text(kernel)
    if projector == "action_v1":
        return project_action(kernel)
    raise ProjectionError(E_PR_UNKNOWN_PROJECTOR, f"未知投影器：{projector}")
