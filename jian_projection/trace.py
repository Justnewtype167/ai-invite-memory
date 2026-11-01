"""Trace contract: ordered typed segments produced by a projector (M11).

A ``Trace`` carries only the producing kernel's identity and the projected
segments. It never carries timestamps, paths or evidence fields, so the same
kernel always projects to the same bytes.
"""

from __future__ import annotations

from dataclasses import dataclass

from jian.canonical import dumps

from jian_projection.errors import (
    E_PR_BAD_DURATION,
    E_PR_EMPTY,
    E_PR_MISSING_KID,
    E_PR_SCHEMA,
    E_PR_UNKNOWN_ACTION,
    E_PR_UNKNOWN_PROJECTOR,
    ProjectionError,
)

SEGMENT_KINDS = ("text", "action", "wait")
ACTION_WHITELIST = ("hold", "idle", "neutral_face", "nod", "step_back")
PROJECTORS = ("action_v1", "text_v1")
DUR_MIN = 1
DUR_MAX = 60000


def _check_duration(kind: str, dur_ms: int | None) -> None:
    """Reject a missing or out-of-range duration for action and wait segments."""
    if dur_ms is None:
        raise ProjectionError(E_PR_BAD_DURATION, f"{kind} 片段必须带 dur_ms")
    if isinstance(dur_ms, bool) or not isinstance(dur_ms, int):
        raise ProjectionError(E_PR_BAD_DURATION, f"{kind} 的 dur_ms 必须是整数")
    if not DUR_MIN <= dur_ms <= DUR_MAX:
        raise ProjectionError(
            E_PR_BAD_DURATION, f"dur_ms 必须在 {DUR_MIN}..{DUR_MAX} 之间"
        )


@dataclass(frozen=True)
class Segment:
    """One typed fragment of a trace."""

    kind: str
    value: str
    dur_ms: int | None

    def __post_init__(self) -> None:
        """Validate the segment against the trace contract."""
        if self.kind not in SEGMENT_KINDS:
            raise ProjectionError(
                E_PR_SCHEMA, f"未知片段类型：{self.kind}"
            )
        if not isinstance(self.value, str):
            raise ProjectionError(E_PR_SCHEMA, "片段 value 必须是字符串")
        if self.kind == "action":
            if self.value not in ACTION_WHITELIST:
                raise ProjectionError(
                    E_PR_UNKNOWN_ACTION, f"未知动作原语：{self.value}"
                )
            _check_duration(self.kind, self.dur_ms)
        elif self.kind == "wait":
            _check_duration(self.kind, self.dur_ms)
        elif self.dur_ms is not None:
            raise ProjectionError(E_PR_SCHEMA, "text 片段不得带 dur_ms")

    def to_payload(self) -> dict[str, object]:
        """Return the canonical JSON-ready view of this segment."""
        return {"dur_ms": self.dur_ms, "kind": self.kind, "value": self.value}


@dataclass(frozen=True)
class Trace:
    """The deterministic output of one projector applied to one kernel."""

    kid: str
    projector: str
    segments: tuple[Segment, ...]

    def __post_init__(self) -> None:
        """Validate the trace identity and segment list."""
        if not isinstance(self.kid, str) or not self.kid:
            raise ProjectionError(E_PR_MISSING_KID, "轨迹必须带上内核 kid")
        if self.projector not in PROJECTORS:
            raise ProjectionError(
                E_PR_UNKNOWN_PROJECTOR, f"未知投影器：{self.projector}"
            )
        if not isinstance(self.segments, tuple):
            raise ProjectionError(E_PR_SCHEMA, "segments 必须是元组")
        if not self.segments:
            raise ProjectionError(E_PR_EMPTY, "空轨迹视为投影失败")
        for segment in self.segments:
            if not isinstance(segment, Segment):
                raise ProjectionError(E_PR_SCHEMA, "segments 只能包含 Segment")

    def to_payload(self) -> dict[str, object]:
        """Return the canonical JSON-ready view of this trace."""
        return {
            "kid": self.kid,
            "projector": self.projector,
            "segments": [segment.to_payload() for segment in self.segments],
        }

    def to_bytes(self) -> bytes:
        """Return this trace as canonical UTF-8 JSON bytes."""
        return dumps(self.to_payload())
