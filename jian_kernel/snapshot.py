"""Derived snapshot storage for incremental kernel compilation (M12).

The snapshot never holds truth: it caches the aggregates a full compile
would recompute, and carries a digest over its own payload so a hand edit is
reported instead of trusted. It lives under ``store/kernel/snapshot.json``
and may be deleted at any time.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from jian.canonical import dumps
from jian.errors import JianError

from jian_kernel.errors import E_KN_IO, E_KN_SNAPSHOT, KernelError
from jian_kernel.kernel import (
    KERNEL_DIR,
    STYLE_SECTIONS,
    Anchor,
    GraphEdge,
    Kernel,
    Policy,
)

SNAPSHOT_FILE = "snapshot.json"
SNAPSHOT_FORMAT = 1
STATE_KEYS = ("intimacy", "stability", "trust")
DIGEST_PREFIX = "sha256:"


@dataclass(frozen=True)
class SnapshotContext:
    """Aggregates a full compile would recompute from every event."""

    content_count: int
    first_stamp: str | None
    last_stamp: str | None
    seen_days: tuple[str, ...]
    months: tuple[str, ...]
    latest_milestone: str
    accepted: tuple[str, ...]
    groups: dict[str, tuple[str, ...]]
    used: dict[str, int]
    counts: dict[str, int]
    rejected: int
    models: tuple[str, ...]


@dataclass(frozen=True)
class Snapshot:
    """One derived snapshot; ``digest`` is filled in when written."""

    head: str
    kid: str
    policy_digest: str
    state: dict[str, int]
    graph: dict[str, object]
    self_md: str
    canon_md: str
    context: SnapshotContext
    digest: str = ""


def snapshot_from(kernel: Kernel, policy: Policy, context: SnapshotContext) -> Snapshot:
    """Build the snapshot that describes one compiled head."""
    return Snapshot(
        head=kernel.head,
        kid=kernel.kid,
        policy_digest=policy_digest(policy),
        state=dict(kernel.state),
        graph=kernel.graph_payload(),
        self_md=kernel.self_md,
        canon_md=kernel.canon_md,
        context=context,
    )


def policy_digest(policy: Policy) -> str:
    """Return the digest of every declared policy field.

    ``now`` is digested as declared. When it is ``None`` the effective clock
    comes from the evidence tail and is recomputed on every call, exactly
    like a full compile, so appending evidence must not invalidate a
    snapshot.
    """
    payload = {
        "allow_fallback": policy.allow_fallback,
        "delta_limit": policy.delta_limit,
        "force_fallback": policy.force_fallback,
        "now": policy.now,
        "require_proposals": policy.require_proposals,
    }
    return DIGEST_PREFIX + hashlib.sha256(dumps(payload)).hexdigest()


def write_snapshot(store: Path, snapshot: Snapshot) -> None:
    """Write the snapshot atomically under ``store/kernel/snapshot.json``."""
    payload = snapshot_payload(snapshot)
    payload["digest"] = digest_of(payload)
    path = store / KERNEL_DIR / SNAPSHOT_FILE
    staging = path.parent / (path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        staging.write_bytes(dumps(payload))
        os.replace(staging, path)
    except OSError as exc:
        raise KernelError(E_KN_IO, f"写入快照失败：{path}") from exc
    finally:
        if staging.exists():
            staging.unlink()


def load_snapshot(store: Path) -> Snapshot | None:
    """Return the snapshot, or ``None`` when there is none to continue."""
    path = store / KERNEL_DIR / SNAPSHOT_FILE
    if not path.is_file():
        return None
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise KernelError(E_KN_IO, f"无法读取快照：{path}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise KernelError(E_KN_SNAPSHOT, f"快照不是合法 JSON：{path}") from exc
    if not isinstance(data, dict):
        raise KernelError(E_KN_SNAPSHOT, "快照顶层不是对象")
    digest = data.get("digest")
    if not isinstance(digest, str):
        raise KernelError(E_KN_SNAPSHOT, "快照缺少 digest")
    body = {key: value for key, value in data.items() if key != "digest"}
    if digest_of(body) != digest:
        raise KernelError(E_KN_SNAPSHOT, "快照 digest 不符，已被手改")
    if data.get("format") != SNAPSHOT_FORMAT:
        raise KernelError(E_KN_SNAPSHOT, f"快照 format 非法：{data.get('format')}")
    return Snapshot(
        head=_text(data, "head"),
        kid=_text(data, "kid"),
        policy_digest=_text(data, "policy_digest"),
        state=_state(data.get("state")),
        graph=_graph(data.get("graph")),
        self_md=_text(data, "self_md"),
        canon_md=_text(data, "canon_md"),
        context=_context(data.get("context")),
    )


def snapshot_payload(snapshot: Snapshot) -> dict[str, object]:
    """Return the canonical payload without its own digest."""
    return {
        "canon_md": snapshot.canon_md,
        "context": context_payload(snapshot.context),
        "format": SNAPSHOT_FORMAT,
        "graph": dict(snapshot.graph),
        "head": snapshot.head,
        "kid": snapshot.kid,
        "policy_digest": snapshot.policy_digest,
        "self_md": snapshot.self_md,
        "state": dict(snapshot.state),
    }


def context_payload(context: SnapshotContext) -> dict[str, object]:
    """Return the canonical view of a continuation context."""
    return {
        "accepted": list(context.accepted),
        "content_count": context.content_count,
        "counts": dict(context.counts),
        "first_stamp": context.first_stamp,
        "groups": {
            target: list(texts) for target, texts in context.groups.items()
        },
        "last_stamp": context.last_stamp,
        "latest_milestone": context.latest_milestone,
        "models": list(context.models),
        "months": list(context.months),
        "rejected": context.rejected,
        "seen_days": list(context.seen_days),
        "used": dict(context.used),
    }


def digest_of(payload: dict[str, object]) -> str:
    """Return the self-certifying digest of a snapshot payload."""
    try:
        raw = dumps(payload)
    except JianError as exc:
        raise KernelError(E_KN_SNAPSHOT, f"快照无法规范化：{exc.message}") from exc
    return DIGEST_PREFIX + hashlib.sha256(raw).hexdigest()


def graph_payload(edges: tuple[GraphEdge, ...], anchors: tuple[Anchor, ...]) -> dict[str, object]:
    """Return the canonical graph view of a set of edges and anchors."""
    return {
        "anchors": [anchor.to_payload() for anchor in anchors],
        "edges": [edge.to_payload() for edge in edges],
    }


def edges_from(graph: dict[str, object]) -> tuple[GraphEdge, ...]:
    """Rebuild edges from a graph payload, rejecting bad shapes."""
    items = graph.get("edges")
    if not isinstance(items, list):
        raise KernelError(E_KN_SNAPSHOT, "快照 graph.edges 不是数组")
    edges: list[GraphEdge] = []
    for item in items:
        if not isinstance(item, dict):
            raise KernelError(E_KN_SNAPSHOT, "快照 graph.edges 项不是对象")
        term = item.get("term")
        event_id = item.get("event_id")
        candidates = item.get("candidates")
        if not isinstance(term, str) or not isinstance(event_id, str):
            raise KernelError(E_KN_SNAPSHOT, "快照 graph.edges 项字段非法")
        if not isinstance(candidates, list) or not all(
            isinstance(value, str) for value in candidates
        ):
            raise KernelError(E_KN_SNAPSHOT, "快照 graph.edges.candidates 非法")
        edges.append(GraphEdge(term, tuple(candidates), event_id))
    return tuple(edges)


def anchors_from(graph: dict[str, object]) -> tuple[Anchor, ...]:
    """Rebuild anchors from a graph payload, rejecting bad shapes."""
    items = graph.get("anchors")
    if not isinstance(items, list):
        raise KernelError(E_KN_SNAPSHOT, "快照 graph.anchors 不是数组")
    anchors: list[Anchor] = []
    for item in items:
        if not isinstance(item, dict):
            raise KernelError(E_KN_SNAPSHOT, "快照 graph.anchors 项不是对象")
        expr = item.get("expr")
        granularity = item.get("granularity")
        certainty = item.get("certainty")
        event_id = item.get("event_id")
        start = item.get("start")
        end = item.get("end")
        if not isinstance(expr, str) or not isinstance(event_id, str):
            raise KernelError(E_KN_SNAPSHOT, "快照 graph.anchors 项字段非法")
        if not isinstance(granularity, str) or not isinstance(certainty, str):
            raise KernelError(E_KN_SNAPSHOT, "快照 graph.anchors 项字段非法")
        if not (start is None or isinstance(start, str)):
            raise KernelError(E_KN_SNAPSHOT, "快照 graph.anchors.start 非法")
        if not (end is None or isinstance(end, str)):
            raise KernelError(E_KN_SNAPSHOT, "快照 graph.anchors.end 非法")
        anchors.append(Anchor(expr, start, end, granularity, certainty, event_id))
    return tuple(anchors)


def _text(data: dict[str, object], name: str) -> str:
    """Return a required string field or raise ``E_KN_SNAPSHOT``."""
    value = data.get(name)
    if not isinstance(value, str):
        raise KernelError(E_KN_SNAPSHOT, f"快照字段 {name} 缺失或不是字符串")
    return value


def _state(value: object) -> dict[str, int]:
    """Validate the stored state."""
    if not isinstance(value, dict):
        raise KernelError(E_KN_SNAPSHOT, "快照 state 不是对象")
    state: dict[str, int] = {}
    for name in STATE_KEYS:
        item = value.get(name)
        if isinstance(item, bool) or not isinstance(item, int):
            raise KernelError(E_KN_SNAPSHOT, f"快照 state.{name} 非法")
        state[name] = item
    return state


def _graph(value: object) -> dict[str, object]:
    """Validate and return the stored graph payload."""
    if not isinstance(value, dict):
        raise KernelError(E_KN_SNAPSHOT, "快照 graph 不是对象")
    edges_from(value)
    anchors_from(value)
    return {key: value[key] for key in value}


def _context(value: object) -> SnapshotContext:
    """Validate the stored continuation context."""
    if not isinstance(value, dict):
        raise KernelError(E_KN_SNAPSHOT, "快照 context 不是对象")
    return SnapshotContext(
        content_count=_number(value.get("content_count"), "context.content_count"),
        first_stamp=_optional_text(value.get("first_stamp"), "context.first_stamp"),
        last_stamp=_optional_text(value.get("last_stamp"), "context.last_stamp"),
        seen_days=_strings(value.get("seen_days"), "context.seen_days"),
        months=_strings(value.get("months"), "context.months"),
        latest_milestone=_text(value, "latest_milestone"),
        accepted=_strings(value.get("accepted"), "context.accepted"),
        groups=_groups(value.get("groups")),
        used=_counts(value.get("used"), "context.used"),
        counts=_counts(value.get("counts"), "context.counts"),
        rejected=_number(value.get("rejected"), "context.rejected"),
        models=_strings(value.get("models"), "context.models"),
    )


def _strings(value: object, name: str) -> tuple[str, ...]:
    """Validate a list of strings."""
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise KernelError(E_KN_SNAPSHOT, f"快照 {name} 不是字符串数组")
    return tuple(value)


def _optional_text(value: object, name: str) -> str | None:
    """Validate an optional string field."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise KernelError(E_KN_SNAPSHOT, f"快照 {name} 非法")
    return value


def _number(value: object, name: str) -> int:
    """Validate a non-negative integer field."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise KernelError(E_KN_SNAPSHOT, f"快照 {name} 非法")
    if value < 0:
        raise KernelError(E_KN_SNAPSHOT, f"快照 {name} 不能为负")
    return value


def _groups(value: object) -> dict[str, tuple[str, ...]]:
    """Validate the per-target style sections."""
    if not isinstance(value, dict):
        raise KernelError(E_KN_SNAPSHOT, "快照 context.groups 不是对象")
    groups: dict[str, tuple[str, ...]] = {}
    for target, _ in STYLE_SECTIONS:
        groups[target] = _strings(
            value.get(target, []), f"context.groups.{target}"
        )
    return groups


def _counts(value: object, name: str) -> dict[str, int]:
    """Validate a per-target integer map."""
    if not isinstance(value, dict):
        raise KernelError(E_KN_SNAPSHOT, f"快照 {name} 不是对象")
    result: dict[str, int] = {}
    for target, _ in STYLE_SECTIONS:
        result[target] = _number(value.get(target, 0), f"{name}.{target}")
    return result
