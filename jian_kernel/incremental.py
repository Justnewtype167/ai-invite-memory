"""Incremental compilation and reconciliation for the persona kernel (M12).

A snapshot under ``store/kernel/snapshot.json`` lets the compiler continue
from the last digested event instead of replaying the whole evidence chain.
The snapshot is a derived artifact: deleting it must change nothing, and
``reconcile`` proves the incremental result equals a full compile byte for
byte. ``compile_kernel`` stays the single definition of truth; this module
never changes its semantics and mirrors its private helpers.

Only the default (replay) proposer is supported here, matching
``compile_kernel(store, policy)``: canonical entries come from directives and
promises, and style proposals come from ``proposal`` evidence events.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jian.canonical import dumps
from jian_recall.index import is_promise

from jian_kernel.compiler import (
    FEEDBACK_TRUST,
    FIRST_DAY_INTIMACY,
    GAP_DAYS,
    GAP_DENOMINATOR,
    GAP_NUMERATOR,
    PROMISE_DONE,
    _build_graph,
    _cancelled,
    _canon_order,
    _clamp,
    _model_ids,
    _resolve_origin,
    _select_style,
    _top_kinship,
    compile_kernel,
    read_evidence,
)
from jian_kernel.errors import (
    E_KN_DRIFT,
    E_KN_IO,
    E_KN_SNAPSHOT,
    E_KN_STALE,
    KernelError,
)
from jian_kernel.gate import check_proposals
from jian_kernel.kernel import (
    STYLE_MAX_PER_TARGET,
    STYLE_SECTIONS,
    STYLE_TEXT_MAX,
    STYLE_TOTAL_MAX,
    Anchor,
    CanonEntry,
    EvidenceEvent,
    GraphEdge,
    Kernel,
    Policy,
    kernel_kid,
    parse_canon,
    parse_stamp,
    render_canon,
)
from jian_kernel.proposer import ReplayProposer
from jian_kernel.snapshot import (
    Snapshot,
    SnapshotContext,
    anchors_from,
    edges_from,
    graph_payload,
    load_snapshot,
    policy_digest,
    snapshot_from,
    write_snapshot,
)


@dataclass(frozen=True)
class ReconcileReport:
    """Outcome of one successful ``reconcile`` call."""

    kid: str
    head: str
    events: int

    def to_payload(self) -> dict[str, object]:
        """Return the JSON-ready view of this report."""
        return {
            "events": self.events,
            "head": self.head,
            "kid": self.kid,
            "status": "ok",
        }


def compile_kernel_incremental(
    store: Path,
    policy: Policy | None = None,
    counter: list[int] | None = None,
) -> Kernel:
    """Compile from a snapshot when possible, otherwise from all evidence.

    A missing snapshot or a policy whose digest changed falls back to the
    full compile. A snapshot whose ``head`` is absent from evidence raises
    ``E_KN_STALE``: evidence was truncated or rolled back, and continuing
    from it would invent history.

    ``counter``, when given, receives one integer per call: the number of
    evidence events this call actually consumed. A full compile consumes
    every event; a continuation consumes only ``id > head``. Work is always
    measured in events, never in wall-clock time (C14).
    """
    chosen = policy if policy is not None else Policy()
    events = read_evidence(store)
    snapshot = load_snapshot(store)
    if snapshot is None:
        return _compile_full(store, chosen, events, counter)
    if not any(event.event_id == snapshot.head for event in events):
        raise KernelError(
            E_KN_STALE, f"快照 head 不在证据中（证据被截断或回滚）：{snapshot.head}"
        )
    if policy_digest(chosen) != snapshot.policy_digest:
        return _compile_full(store, chosen, events, counter)
    head = _sequence(snapshot.head)
    delta = [event for event in events if _sequence(event.event_id) > head]
    if not delta:
        _record(counter, 0)
        return _kernel_from_snapshot(snapshot, chosen, events)
    kernel, context = _apply_delta(snapshot, delta, chosen, events)
    write_snapshot(store, snapshot_from(kernel, chosen, context))
    _record(counter, len(delta))
    return kernel


def reconcile(store: Path, policy: Policy | None = None) -> ReconcileReport:
    """Recompute from scratch and compare the snapshot byte for byte.

    Drift in ``kid``, ``canon.md``, ``self.md``, ``state.json`` or
    ``graph.json`` raises ``E_KN_DRIFT``. A missing snapshot raises
    ``E_KN_SNAPSHOT``: there is nothing to reconcile against. A snapshot
    whose ``head`` is not the current evidence head raises ``E_KN_DRIFT``:
    the derivation no longer describes the store.
    """
    chosen = policy if policy is not None else Policy()
    snapshot = load_snapshot(store)
    if snapshot is None:
        raise KernelError(E_KN_SNAPSHOT, "没有快照可对账，请先跑一次增量编译")
    events = read_evidence(store)
    if not any(event.event_id == snapshot.head for event in events):
        raise KernelError(E_KN_STALE, f"快照 head 不在证据中：{snapshot.head}")
    kernel = compile_kernel(store, chosen)
    if snapshot.head != kernel.head:
        raise KernelError(
            E_KN_DRIFT, f"快照 head 落后于证据：{snapshot.head} != {kernel.head}"
        )
    _compare(snapshot, kernel)
    return ReconcileReport(kernel.kid, kernel.head, len(events))


def _compare(snapshot: Snapshot, kernel: Kernel) -> None:
    """Raise ``E_KN_DRIFT`` on the first artifact that differs."""
    if kernel.kid != snapshot.kid:
        raise KernelError(
            E_KN_DRIFT, f"kid 不一致：全量 {kernel.kid} != 快照 {snapshot.kid}"
        )
    if kernel.canon_md != snapshot.canon_md:
        raise KernelError(E_KN_DRIFT, "canon.md 不一致")
    if kernel.self_md != snapshot.self_md:
        raise KernelError(E_KN_DRIFT, "self.md 不一致")
    if dumps(dict(kernel.state)) != dumps(dict(snapshot.state)):
        raise KernelError(E_KN_DRIFT, "state.json 不一致")
    if dumps(kernel.graph_payload()) != dumps(dict(snapshot.graph)):
        raise KernelError(E_KN_DRIFT, "graph.json 不一致")


def _compile_full(
    store: Path, policy: Policy, events: list[EvidenceEvent], counter: list[int] | None
) -> Kernel:
    """Compile every event, then seed the snapshot from the result."""
    kernel = compile_kernel(store, policy)
    write_snapshot(store, snapshot_from(kernel, policy, _build_context(events)))
    _record(counter, len(events))
    return kernel


def _record(counter: list[int] | None, processed: int) -> None:
    """Append one work measurement when a counter was supplied."""
    if counter is not None:
        counter.append(processed)


def _apply_delta(
    snapshot: Snapshot,
    delta: list[EvidenceEvent],
    policy: Policy,
    events: list[EvidenceEvent],
) -> tuple[Kernel, SnapshotContext]:
    """Continue the snapshot aggregates with only the new events."""
    content = [event for event in delta if event.type != "proposal"]
    check_proposals(delta)
    accepted, rejected, groups, used, counts = _continue_style(snapshot.context, delta)
    state, seen_days = _continue_state(snapshot.state, snapshot.context, content)
    edges, anchors = _merge_graph(snapshot, content)
    canon = _merge_canon(snapshot, content)
    context = _extend_context(
        snapshot.context, content, delta, seen_days, accepted, rejected,
        groups, used, counts,
    )
    moment = policy.resolved_now(events[-1].stamp)
    origin = _resolve_origin(policy, accepted)
    self_md = _render_self_stats(context, moment, edges)
    canon_md = render_canon(canon)
    graph = graph_payload(edges, anchors)
    kernel = Kernel(
        kid=kernel_kid(self_md, canon_md, state, graph, origin, context.models),
        head=events[-1].event_id,
        canon=canon,
        edges=edges,
        anchors=anchors,
        state=state,
        self_md=self_md,
        canon_md=canon_md,
        policy_hash=policy.hash(moment),
        origin=origin,
        style=accepted,
        rejected=rejected,
        models=context.models,
    )
    return kernel, context


def _continue_style(
    context: SnapshotContext, delta: list[EvidenceEvent]
) -> tuple[tuple[str, ...], int, dict[str, tuple[str, ...]],
           dict[str, int], dict[str, int]]:
    """Apply the delta proposals to the stored quotas and budgets."""
    accepted = list(context.accepted)
    rejected = context.rejected
    used = dict(context.used)
    counts = dict(context.counts)
    groups = {
        target: list(context.groups.get(target, ())) for target, _ in STYLE_SECTIONS
    }
    for proposal in ReplayProposer().style(delta):
        count = counts.get(proposal.target, 0)
        if count >= STYLE_MAX_PER_TARGET:
            rejected += 1
            continue
        text = proposal.text[:STYLE_TEXT_MAX]
        cost = len(text) + (1 if groups[proposal.target] else 0)
        if used.get(proposal.target, 0) + cost > STYLE_TOTAL_MAX:
            rejected += 1
            continue
        used[proposal.target] = used.get(proposal.target, 0) + cost
        counts[proposal.target] = count + 1
        accepted.append(text)
        groups[proposal.target].append(text)
    sections = {target: tuple(texts) for target, texts in groups.items()}
    return tuple(accepted), rejected, sections, used, counts


def _continue_state(
    state: dict[str, int], context: SnapshotContext, delta: list[EvidenceEvent]
) -> tuple[dict[str, int], set[str]]:
    """Accumulate the delta content events onto the stored state."""
    trust = state["trust"]
    intimacy = state["intimacy"]
    stability = state["stability"]
    seen_days = set(context.seen_days)
    previous = parse_stamp(context.last_stamp) if context.last_stamp else None
    for event in delta:
        moment = parse_stamp(event.stamp)
        if previous is not None:
            gap = max(0, (moment.date() - previous.date()).days)
            for _ in range(gap // GAP_DAYS):
                trust = trust * GAP_NUMERATOR // GAP_DENOMINATOR
                intimacy = intimacy * GAP_NUMERATOR // GAP_DENOMINATOR
                stability = stability * GAP_NUMERATOR // GAP_DENOMINATOR
        day = event.stamp[:10]
        if day not in seen_days:
            seen_days.add(day)
            intimacy += FIRST_DAY_INTIMACY
        if event.type == "feedback" and event.kind in FEEDBACK_TRUST:
            trust += FEEDBACK_TRUST[event.kind]
        trust = _clamp(trust)
        intimacy = _clamp(intimacy)
        stability = _clamp(stability)
        previous = moment
    return {"intimacy": intimacy, "stability": stability, "trust": trust}, seen_days


def _merge_graph(
    snapshot: Snapshot, delta: list[EvidenceEvent]
) -> tuple[tuple[GraphEdge, ...], tuple[Anchor, ...]]:
    """Merge stored graph payloads with the delta graph."""
    new_edges, new_anchors = _build_graph(delta)
    edges = list(edges_from(snapshot.graph)) + list(new_edges)
    anchors = list(anchors_from(snapshot.graph)) + list(new_anchors)
    unique_edges: dict[tuple[str, str, tuple[str, ...]], GraphEdge] = {}
    for edge in edges:
        unique_edges.setdefault((edge.event_id, edge.term, edge.candidates), edge)
    merged_edges = tuple(
        sorted(unique_edges.values(), key=lambda item: (item.event_id, item.term))
    )
    unique_anchors: dict[
        tuple[str, str, str | None, str | None, str, str], Anchor
    ] = {}
    for anchor in anchors:
        key = (anchor.event_id, anchor.expr, anchor.start, anchor.end,
               anchor.granularity, anchor.certainty)
        unique_anchors.setdefault(key, anchor)
    merged_anchors = tuple(
        sorted(unique_anchors.values(), key=lambda item: (item.event_id, item.expr))
    )
    return merged_edges, merged_anchors


def _merge_canon(
    snapshot: Snapshot, delta: list[EvidenceEvent]
) -> tuple[CanonEntry, ...]:
    """Keep stored entries except cancelled promises, then add delta entries."""
    done = any(marker in event.text for event in delta for marker in PROMISE_DONE)
    kept = [
        entry for entry in parse_canon(snapshot.canon_md)
        if not (done and entry.kind == "promise")
    ]
    for event in delta:
        if event.type == "directive" and event.kind == "lock":
            kept.append(CanonEntry("directive", event.text, (event.event_id,)))
        elif is_promise(event.text) and not _cancelled(event, delta):
            kept.append(CanonEntry("promise", event.text, (event.event_id,)))
    unique: dict[tuple[str, str, tuple[str, ...]], CanonEntry] = {}
    for entry in kept:
        unique.setdefault(entry.identity(), entry)
    return tuple(sorted(unique.values(), key=_canon_order))


def _extend_context(
    context: SnapshotContext,
    content: list[EvidenceEvent],
    delta: list[EvidenceEvent],
    seen_days: set[str],
    accepted: tuple[str, ...],
    rejected: int,
    groups: dict[str, tuple[str, ...]],
    used: dict[str, int],
    counts: dict[str, int],
) -> SnapshotContext:
    """Return the context describing the new head."""
    milestones = [event.text for event in content if event.type == "milestone"]
    first_stamp = context.first_stamp
    if first_stamp is None and content:
        first_stamp = content[0].stamp
    last_stamp = content[-1].stamp if content else context.last_stamp
    months = tuple(
        sorted(set(context.months) | {event.stamp[:7] for event in content})
    )
    models = tuple(sorted(set(context.models) | set(_model_ids(delta))))
    return SnapshotContext(
        content_count=context.content_count + len(content),
        first_stamp=first_stamp,
        last_stamp=last_stamp,
        seen_days=tuple(sorted(seen_days)),
        months=months,
        latest_milestone=milestones[-1] if milestones else context.latest_milestone,
        accepted=accepted,
        groups=groups,
        used=used,
        counts=counts,
        rejected=rejected,
        models=models,
    )


def _render_self_stats(
    context: SnapshotContext, moment: datetime, edges: tuple[GraphEdge, ...]
) -> str:
    """Render ``self.md`` exactly like the full compiler does."""
    known = 0
    if context.first_stamp is not None:
        first = parse_stamp(context.first_stamp)
        known = max(0, (moment.date() - first.date()).days)
    lines = [
        "# Self",
        "",
        f"- known_days: {known}",
        f"- events: {context.content_count}",
        f"- active_months: {len(context.months)}",
        f"- top_kinship: {_top_kinship(edges)}",
        f"- latest_milestone: {context.latest_milestone}",
    ]
    for target, title in STYLE_SECTIONS:
        texts = context.groups.get(target, ())
        if not texts:
            continue
        lines.extend(["", f"## {title}", ""])
        lines.extend(f"- {text}" for text in texts)
    return "\n".join(lines) + "\n"


def _kernel_from_snapshot(
    snapshot: Snapshot, policy: Policy, events: list[EvidenceEvent]
) -> Kernel:
    """Rebuild an unchanged kernel from snapshot bytes; verify its kid."""
    moment = policy.resolved_now(events[-1].stamp)
    canon = parse_canon(snapshot.canon_md)
    edges = edges_from(snapshot.graph)
    anchors = anchors_from(snapshot.graph)
    graph = graph_payload(edges, anchors)
    if dumps(graph) != dumps(dict(snapshot.graph)):
        raise KernelError(E_KN_SNAPSHOT, "快照 graph 字段自相矛盾")
    origin = _resolve_origin(policy, snapshot.context.accepted)
    kid = kernel_kid(
        snapshot.self_md, snapshot.canon_md, dict(snapshot.state),
        graph, origin, snapshot.context.models,
    )
    if kid != snapshot.kid:
        raise KernelError(
            E_KN_DRIFT, f"快照 kid 与其产物不一致：{kid} != {snapshot.kid}"
        )
    return Kernel(
        kid=kid,
        head=snapshot.head,
        canon=canon,
        edges=edges,
        anchors=anchors,
        state=dict(snapshot.state),
        self_md=snapshot.self_md,
        canon_md=snapshot.canon_md,
        policy_hash=policy.hash(moment),
        origin=origin,
        style=snapshot.context.accepted,
        rejected=snapshot.context.rejected,
        models=snapshot.context.models,
    )


def _build_context(events: list[EvidenceEvent]) -> SnapshotContext:
    """Derive the continuation context from a full compile."""
    content = [event for event in events if event.type != "proposal"]
    accepted, rejected, sections = _select_style(events)
    groups = {
        target: tuple(sections.get(target, ())) for target, _ in STYLE_SECTIONS
    }
    used = {
        target: sum(len(text) for text in texts) + max(len(texts) - 1, 0)
        for target, texts in groups.items()
    }
    counts = {target: len(texts) for target, texts in groups.items()}
    milestones = [event.text for event in content if event.type == "milestone"]
    return SnapshotContext(
        content_count=len(content),
        first_stamp=content[0].stamp if content else None,
        last_stamp=content[-1].stamp if content else None,
        seen_days=tuple(sorted({event.stamp[:10] for event in content})),
        months=tuple(sorted({event.stamp[:7] for event in content})),
        latest_milestone=milestones[-1] if milestones else "-",
        accepted=tuple(accepted),
        groups=groups,
        used=used,
        counts=counts,
        rejected=rejected,
        models=_model_ids(events),
    )


def _sequence(event_id: str) -> int:
    """Return the numeric part of an event id."""
    try:
        return int(event_id.split("_")[1])
    except (IndexError, ValueError) as exc:
        raise KernelError(E_KN_IO, f"非法事件 id：{event_id}") from exc
