"""Deterministic projections from a persona kernel to output traces (M11)."""

from __future__ import annotations

from jian_projection.action import load_action_map, project_action
from jian_projection.errors import E_PR_UNKNOWN_PROJECTOR, ProjectionError
from jian_projection.text import project_text
from jian_projection.trace import (
    ACTION_WHITELIST,
    PROJECTORS,
    SEGMENT_KINDS,
    Segment,
    Trace,
)

__all__ = [
    "ACTION_WHITELIST",
    "PROJECTORS",
    "ProjectionError",
    "SEGMENT_KINDS",
    "Segment",
    "Trace",
    "load_action_map",
    "project",
    "project_action",
    "project_text",
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
