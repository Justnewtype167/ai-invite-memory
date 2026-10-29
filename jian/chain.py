"""Hash chain construction and verification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from .errors import E_CHAIN_MISSING, E_SCHEMA, E_TAMPER, JianError
from .event import (
    GENESIS_PREV,
    SEGMENT_MAX_EVENTS,
    Event,
    event_digest,
    format_id,
)

_SEG_NAME_RE = re.compile(r"^seg-([0-9]{4})$")


@dataclass(frozen=True)
class Segment:
    """Summary of one evidence segment."""

    seg: str
    count: int
    first: str
    last: str
    prev_seg: str | None

    def as_dict(self) -> dict[str, object]:
        """Return the chain.json representation of this segment."""
        return {
            "seg": self.seg,
            "count": self.count,
            "first": self.first,
            "last": self.last,
            "prev_seg": self.prev_seg,
        }


def segment_number(name: str) -> int:
    """Return the numeric index of a ``seg-NNNN`` name."""
    match = _SEG_NAME_RE.match(name)
    if not match:
        raise JianError(E_CHAIN_MISSING, f"非法段名：{name}")
    return int(match.group(1))


def summarize(evidence: Sequence[tuple[str, Sequence[Event]]]) -> list[Segment]:
    """Build segment summaries from parsed evidence in order."""
    segments: list[Segment] = []
    previous: str | None = None
    for name, events in evidence:
        if not events:
            raise JianError(E_CHAIN_MISSING, f"段 {name} 没有事件")
        segments.append(Segment(name, len(events), events[0].hash, events[-1].hash, previous))
        previous = name
    return segments


def verify_evidence(evidence: Sequence[tuple[str, Sequence[Event]]]) -> tuple[int, str]:
    """Verify ids, links and hashes across all segments.

    Returns ``(event_count, head_hash)``. Raises ``E_CHAIN_MISSING`` for a
    broken or missing link and ``E_TAMPER`` (with the event id) for content
    that no longer matches its hash.
    """
    if not evidence:
        raise JianError(E_CHAIN_MISSING, "没有证据段")
    expected_prev = GENESIS_PREV
    expected_seq = 1
    expected_index = 1
    for name, events in evidence:
        index = segment_number(name)
        if index != expected_index:
            raise JianError(E_CHAIN_MISSING, f"缺少段：期望 seg-{expected_index:04d}")
        if not events:
            raise JianError(E_CHAIN_MISSING, f"段 {name} 是空的")
        if len(events) > SEGMENT_MAX_EVENTS:
            raise JianError(E_SCHEMA, f"段 {name} 超过 {SEGMENT_MAX_EVENTS} 条事件")
        for event in events:
            if event.ep != name:
                raise JianError(E_SCHEMA, f"事件 {event.id} 的段名与文件不符", event.id)
            if event.id != format_id(expected_seq):
                raise JianError(E_CHAIN_MISSING, f"事件 {event.id} 序号不连续", event.id)
            if event.prev != expected_prev:
                raise JianError(E_CHAIN_MISSING, f"事件 {event.id} 的 prev 不接上一条", event.id)
            if event_digest(event) != event.hash:
                raise JianError(E_TAMPER, f"事件 {event.id} 内容与 hash 不符", event.id)
            expected_prev = event.hash
            expected_seq += 1
        expected_index += 1
    return expected_seq - 1, expected_prev


def chain_document(sealed_at: str | None, segments: Sequence[Segment]) -> dict[str, object]:
    """Build the chain.json document for the given segments."""
    return {
        "v": 1,
        "sealed_at": sealed_at,
        "segments": [segment.as_dict() for segment in segments],
    }


def chain_matches(document: Mapping[str, object], sealed_at: str | None,
                  segments: Sequence[Segment]) -> bool:
    """Return whether a decoded chain.json equals the recomputed chain."""
    return dict(document) == chain_document(sealed_at, segments)


def parse_chain(data: object) -> dict[str, object]:
    """Validate a decoded chain.json document and return it."""
    if not isinstance(data, dict):
        raise JianError(E_SCHEMA, "chain.json 必须是对象")
    if set(data) != {"v", "sealed_at", "segments"}:
        raise JianError(E_SCHEMA, "chain.json 字段缺失或多余")
    if isinstance(data["v"], bool) or not isinstance(data["v"], int) or data["v"] != 1:
        raise JianError(E_SCHEMA, "chain.json 的 v 必须为 1")
    sealed_at = data["sealed_at"]
    if sealed_at is not None and not isinstance(sealed_at, str):
        raise JianError(E_SCHEMA, "chain.json 的 sealed_at 必须是字符串或 null")
    rows = data["segments"]
    if not isinstance(rows, list):
        raise JianError(E_SCHEMA, "chain.json 的 segments 必须是数组")
    for row in rows:
        _validate_segment_row(row)
    return data


def _validate_segment_row(row: object) -> None:
    if not isinstance(row, dict):
        raise JianError(E_SCHEMA, "chain.json 的段条目必须是对象")
    if set(row) != {"seg", "count", "first", "last", "prev_seg"}:
        raise JianError(E_SCHEMA, "chain.json 的段条目字段缺失或多余")
    if not isinstance(row["seg"], str) or not _SEG_NAME_RE.match(row["seg"]):
        raise JianError(E_SCHEMA, "chain.json 的段名非法")
    count = row["count"]
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 100:
        raise JianError(E_SCHEMA, "chain.json 的 count 越界")
    for key in ("first", "last"):
        value = row[key]
        if not isinstance(value, str) or len(value) != 64:
            raise JianError(E_SCHEMA, f"chain.json 的 {key} 非法")
    prev_seg = row["prev_seg"]
    if prev_seg is not None and (
        not isinstance(prev_seg, str) or not _SEG_NAME_RE.match(prev_seg)
    ):
        raise JianError(E_SCHEMA, "chain.json 的 prev_seg 非法")
