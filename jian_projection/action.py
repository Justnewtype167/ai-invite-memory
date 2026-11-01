"""action_v1: project a kernel's canon into an executable action sequence."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jian_projection.errors import E_PR_EMPTY, E_PR_MAP_INVALID, ProjectionError
from jian_projection.trace import Segment, Trace

PROJECTOR = "action_v1"
DATA_FILE = Path(__file__).resolve().parent / "data" / "action_map.json"


def _segment_from_map(rule: str, item: object) -> Segment:
    """Build one validated segment from one mapping entry."""
    if not isinstance(item, dict):
        raise ProjectionError(E_PR_MAP_INVALID, f"映射 {rule} 的片段必须是对象")
    kind = item.get("kind")
    value = item.get("value", "")
    dur_ms = item.get("dur_ms")
    if not isinstance(kind, str) or not isinstance(value, str):
        raise ProjectionError(E_PR_MAP_INVALID, f"映射 {rule} 的 kind/value 非法")
    try:
        return Segment(kind, value, dur_ms)
    except ProjectionError as error:
        raise ProjectionError(
            E_PR_MAP_INVALID, f"映射 {rule} 非法：{error.message}"
        ) from error


@lru_cache(maxsize=1)
def load_action_map() -> tuple[tuple[str, tuple[Segment, ...]], ...]:
    """Load the rule-to-action map, preserving the file order of the rules."""
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectionError(
            E_PR_MAP_INVALID, f"动作映射无法读取：{error}"
        ) from error
    if not isinstance(raw, dict) or not raw:
        raise ProjectionError(E_PR_MAP_INVALID, "动作映射必须是非空对象")
    entries: list[tuple[str, tuple[Segment, ...]]] = []
    for rule, body in raw.items():
        if not isinstance(rule, str) or not rule:
            raise ProjectionError(E_PR_MAP_INVALID, "动作映射的规则名必须是非空字符串")
        if not isinstance(body, dict):
            raise ProjectionError(E_PR_MAP_INVALID, f"映射 {rule} 必须是对象")
        items = body.get("segments")
        if not isinstance(items, list) or not items:
            raise ProjectionError(E_PR_MAP_INVALID, f"映射 {rule} 缺少 segments")
        entries.append(
            (rule, tuple(_segment_from_map(rule, item) for item in items))
        )
    return tuple(entries)


def project_action(kernel: object) -> Trace:
    """Project a kernel object's canon entries into action and wait segments.

    Each canon entry is matched against the rules loaded from
    ``data/action_map.json``; the first matching rule wins. Entries that match
    no rule are ignored, and a trace with no matched rule is a projection
    failure (``E_PR_EMPTY``).
    """
    mapping = load_action_map()
    segments: list[Segment] = []
    for entry in kernel.canon:
        for rule, mapped in mapping:
            if rule in entry.text:
                segments.extend(mapped)
                break
    if not segments:
        raise ProjectionError(E_PR_EMPTY, "没有 canon 规则命中动作映射")
    return Trace(
        kid=kernel.kid, projector=PROJECTOR, segments=tuple(segments)
    )
