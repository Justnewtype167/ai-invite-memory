"""action_v1: project a kernel's canon into an executable action sequence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from jian_projection.errors import E_PR_EMPTY, E_PR_MAP_INVALID, ProjectionError
from jian_projection.trace import Segment, Trace

PROJECTOR = "action_v1"
DEFAULT_KEY = "_default"
DATA_FILE = Path(__file__).resolve().parent / "data" / "action_map.json"


@dataclass(frozen=True)
class ActionRule:
    """One keyword rule: any keyword contained in a canon entry selects it."""

    name: str
    keywords: tuple[str, ...]
    segments: tuple[Segment, ...]


@dataclass(frozen=True)
class ActionMap:
    """The loaded map: ordered keyword rules plus the fallback segments."""

    rules: tuple[ActionRule, ...]
    default: tuple[Segment, ...]


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


def _parse_segments(rule: str, body: object) -> tuple[Segment, ...]:
    """Validate one map body and return its non-empty segment tuple."""
    if not isinstance(body, dict):
        raise ProjectionError(E_PR_MAP_INVALID, f"映射 {rule} 必须是对象")
    items = body.get("segments")
    if not isinstance(items, list) or not items:
        raise ProjectionError(E_PR_MAP_INVALID, f"映射 {rule} 缺少 segments")
    return tuple(_segment_from_map(rule, item) for item in items)


@lru_cache(maxsize=1)
def load_action_map() -> ActionMap:
    """Load the keyword rule map, preserving file order, plus the fallback."""
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectionError(
            E_PR_MAP_INVALID, f"动作映射无法读取：{error}"
        ) from error
    if not isinstance(raw, dict) or not raw:
        raise ProjectionError(E_PR_MAP_INVALID, "动作映射必须是非空对象")
    if DEFAULT_KEY not in raw:
        raise ProjectionError(
            E_PR_MAP_INVALID, f"动作映射缺少 {DEFAULT_KEY} 兜底规则"
        )
    default = _parse_segments(DEFAULT_KEY, raw[DEFAULT_KEY])
    rules: list[ActionRule] = []
    for name, body in raw.items():
        if name == DEFAULT_KEY:
            continue
        if not isinstance(name, str) or not name:
            raise ProjectionError(E_PR_MAP_INVALID, "动作映射的规则名必须是非空字符串")
        if not isinstance(body, dict):
            raise ProjectionError(E_PR_MAP_INVALID, f"映射 {name} 必须是对象")
        keywords = body.get("keywords")
        if (
            not isinstance(keywords, list)
            or not keywords
            or not all(isinstance(item, str) and item for item in keywords)
        ):
            raise ProjectionError(
                E_PR_MAP_INVALID, f"映射 {name} 缺少合法的 keywords"
            )
        rules.append(
            ActionRule(name, tuple(keywords), _parse_segments(name, body))
        )
    if not rules:
        raise ProjectionError(E_PR_MAP_INVALID, "动作映射没有关键词规则")
    return ActionMap(tuple(rules), default)


def _rule_for(text: str, mapping: ActionMap) -> tuple[Segment, ...]:
    """Return the first rule whose keyword appears in ``text``, else the default."""
    for rule in mapping.rules:
        if any(keyword in text for keyword in rule.keywords):
            return rule.segments
    return mapping.default


def project_action(kernel: object) -> Trace:
    """Project a kernel object's canon entries into action and wait segments.

    Matching is keyword containment against ``data/action_map.json``; the
    first matching rule wins, and ``_default`` covers every unmapped entry.
    An empty canon is the only projection failure (``E_PR_EMPTY``).
    """
    canon = tuple(kernel.canon)
    if not canon:
        raise ProjectionError(E_PR_EMPTY, "canon 为空，无法投影动作序列")
    mapping = load_action_map()
    segments: list[Segment] = []
    for entry in canon:
        text = entry.text
        for segment in _rule_for(text, mapping):
            segments.append(
                Segment(segment.kind, segment.value, segment.dur_ms, text, segment.role)
            )
    return Trace(
        kid=kernel.kid, projector=PROJECTOR, segments=tuple(segments)
    )
