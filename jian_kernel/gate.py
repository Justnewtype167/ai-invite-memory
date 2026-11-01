"""Drift gates that guard every kernel write (M4)."""

from __future__ import annotations

from dataclasses import dataclass

from jian_kernel.errors import (
    E_KN_BAD_PROPOSAL,
    E_KN_BAD_TARGET,
    E_KN_GATE_CANON,
    E_KN_GATE_DELTA,
    E_KN_GATE_STATE,
    E_KN_UNSOURCED,
    KernelError,
)
from jian_kernel.kernel import (
    PERSONA_TARGETS,
    STATE_STEP_LIMIT,
    STYLE_TARGETS,
    CanonEntry,
    Diff,
    EvidenceEvent,
    Kernel,
    Policy,
)

MAX_DELTA_DENOMINATOR = 1000


@dataclass(frozen=True)
class PreviousState:
    """What the last recorded version looked like, as found on disk."""

    head: str
    canon: tuple[CanonEntry, ...]
    state: dict[str, int]


def diff_canon(
    previous: tuple[CanonEntry, ...], current: tuple[CanonEntry, ...]
) -> Diff:
    """Return added, changed and removed entries between two canon sets."""
    previous_by_source = {entry.source(): entry for entry in previous}
    current_by_source = {entry.source(): entry for entry in current}
    added = tuple(
        entry for source, entry in sorted(
            current_by_source.items(), key=lambda item: _order(item[1])
        ) if source not in previous_by_source
    )
    removed = tuple(
        entry for source, entry in sorted(
            previous_by_source.items(), key=lambda item: _order(item[1])
        ) if source not in current_by_source
    )
    changed = tuple(
        current_entry for source, current_entry in sorted(
            current_by_source.items(), key=lambda item: _order(item[1])
        )
        if source in previous_by_source
        and previous_by_source[source].text != current_entry.text
    )
    return Diff(added, changed, removed)


def _order(entry: CanonEntry) -> tuple[str, str, str]:
    first = entry.evidence[0] if entry.evidence else ""
    return (entry.kind, first, entry.text)


def check_proposals(events: list[EvidenceEvent]) -> None:
    """Apply G5a and G5b: a proposal must name an allowed target and a source.

    G5a and G5b are hard failures, not silent rejections: a bad target or a
    missing model means the writer is buggy or probing, so compilation stops.

    Persona targets are allowed for direct callers, but the compiler only
    passes ``core_events`` here, so persona proposals never reach G5 and can
    never influence ``origin``, ``models`` or the kid.
    """
    allowed = STYLE_TARGETS + PERSONA_TARGETS
    for event in events:
        if event.type != "proposal":
            continue
        if event.target not in allowed:
            raise KernelError(
                E_KN_BAD_TARGET,
                f"提案 target 不在白名单：{event.target}（允许 {allowed}）",
            )
        if not event.model or not event.prompt_sha:
            raise KernelError(
                E_KN_BAD_PROPOSAL,
                f"提案缺少 model 或 prompt_sha：{event.event_id}",
            )


def check_gates(
    previous: PreviousState | None,
    current: Kernel,
    events: list[EvidenceEvent],
    policy: Policy,
) -> None:
    """Apply G1-G4 and raise on the first violation."""
    if previous is not None:
        new_directives = any(
            event.type == "directive" and event.kind == "lock"
            and event.event_id > previous.head
            for event in events
        )
        _check_canon(previous, current, new_directives)
        _check_delta(previous, current, policy)
    _check_sources(current, events)
    if previous is not None:
        _check_state(previous, current)


def _check_canon(
    previous: PreviousState, current: Kernel, new_directives: bool
) -> None:
    old = {entry.identity() for entry in previous.canon}
    new = {entry.identity() for entry in current.canon}
    if old != new and not new_directives:
        raise KernelError(
            E_KN_GATE_CANON,
            "canon 与上一版不一致且本次证据没有新增 directive 事件",
        )


def _check_delta(previous: PreviousState, current: Kernel, policy: Policy) -> None:
    diff = diff_canon(previous.canon, current.canon)
    baseline = max(1, len(previous.canon))
    if diff.delta().total() * MAX_DELTA_DENOMINATOR > policy.delta_limit * baseline:
        raise KernelError(
            E_KN_GATE_DELTA,
            f"变更率超限：{diff.delta().total()}/{baseline} > "
            f"{policy.delta_limit}/{MAX_DELTA_DENOMINATOR}",
        )


def _check_state(previous: PreviousState, current: Kernel) -> None:
    for name in sorted(current.state):
        old = previous.state.get(name)
        if old is None:
            continue
        if abs(current.state[name] - old) > STATE_STEP_LIMIT:
            raise KernelError(
                E_KN_GATE_STATE,
                f"状态 {name} 单次跳变 {abs(current.state[name] - old)} > "
                f"{STATE_STEP_LIMIT}",
            )


def _check_sources(current: Kernel, events: list[EvidenceEvent]) -> None:
    known = {event.event_id for event in events}
    for entry in current.canon:
        if not entry.evidence:
            raise KernelError(E_KN_UNSOURCED, f"条目缺少证据：{entry.text}")
        for event_id in entry.evidence:
            if event_id not in known:
                raise KernelError(
                    E_KN_UNSOURCED, f"条目引用了不存在的事件：{event_id}"
                )
    for edge in current.edges:
        if edge.event_id not in known:
            raise KernelError(
                E_KN_UNSOURCED, f"称谓边引用了不存在的事件：{edge.event_id}"
            )
    for anchor in current.anchors:
        if anchor.event_id not in known:
            raise KernelError(
                E_KN_UNSOURCED, f"时间锚点引用了不存在的事件：{anchor.event_id}"
            )
