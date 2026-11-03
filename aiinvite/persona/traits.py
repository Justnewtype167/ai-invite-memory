"""Trait vocabulary and resolution (M16).

Traits are written by a human, never extracted from model output. The two
authorized shapes are a direct ``directive(kind=trait|trait_off)`` and a
``proposal(target=self.trait)`` approved by a later directive whose ``target``
is the proposal id and whose text is identical to the proposal text.

Resolution is deterministic: an active trait is removed by a later
``trait_off``; two active traits that conflict are resolved by risk (lower
wins, later activation breaks a tie); a high-risk trait is dropped outside
its allowed modes and the reason is reported instead of raised.
"""

from __future__ import annotations

import json
from pathlib import Path

from aiinvite.kernel.kernel import EvidenceEvent

from aiinvite.persona.errors import (
    E_PERSONA_INPUT,
    E_PERSONA_IO,
    E_PERSONA_TRAIT_CAP,
    E_PERSONA_TRAIT_CONFLICT,
    E_PERSONA_TRAIT_MODE,
    E_PERSONA_TRAIT_SCHEMA,
    E_PERSONA_UNAPPROVED,
    PersonaError,
)
from aiinvite.persona.model import (
    MODE_VALUES,
    ORIGIN_APPROVED_PROPOSAL,
    ORIGIN_USER,
    RISK_VALUES,
    TRAIT_CAP,
    TRAIT_OFF,
    TRAIT_ON,
    TRAIT_TARGET,
    ActiveTrait,
    Conflict,
    TraitActivation,
    TraitDef,
    TraitResolution,
)

DEFAULT_VOCAB_PATH = (
    Path(__file__).resolve().parent.parent / "kernel" / "data" / "traits.json"
)
ENTRY_KEYS = ("guidance", "conflicts", "modes", "risk")
RISK_RANK = {"low": 0, "medium": 1, "high": 2}


def load_vocabulary(path: Path | None = None) -> dict[str, TraitDef]:
    """Load and validate the trait vocabulary.

    Every conflict must be symmetric: if ``A`` lists ``B``, ``B`` must list
    ``A``. Otherwise the vocabulary is internally inconsistent and cannot
    resolve conflicts deterministically.
    """
    target = path if path is not None else DEFAULT_VOCAB_PATH
    data = _read_json(target, "特质词表")
    if not isinstance(data, dict) or not data:
        raise PersonaError(E_PERSONA_TRAIT_SCHEMA, "特质词表必须是非空对象")
    vocabulary: dict[str, TraitDef] = {}
    for name, entry in data.items():
        if not isinstance(name, str) or not name:
            raise PersonaError(E_PERSONA_TRAIT_SCHEMA, "特质名必须是非空字符串")
        vocabulary[name] = _parse_entry(name, entry)
    for name, definition in vocabulary.items():
        for other in definition.conflicts:
            if other not in vocabulary:
                raise PersonaError(
                    E_PERSONA_TRAIT_CONFLICT,
                    f"特质 {name} 引用了不存在的冲突名：{other}",
                )
            if name not in vocabulary[other].conflicts:
                raise PersonaError(
                    E_PERSONA_TRAIT_CONFLICT,
                    f"冲突引用不闭合：{name} -> {other}",
                )
    return vocabulary


def _parse_entry(name: str, entry: object) -> TraitDef:
    if not isinstance(entry, dict):
        raise PersonaError(E_PERSONA_TRAIT_SCHEMA, f"特质 {name} 不是对象")
    if tuple(sorted(entry)) != tuple(sorted(ENTRY_KEYS)):
        raise PersonaError(
            E_PERSONA_TRAIT_SCHEMA, f"特质 {name} 字段必须恰好是 {ENTRY_KEYS}"
        )
    guidance = entry.get("guidance")
    if not isinstance(guidance, str) or not guidance:
        raise PersonaError(E_PERSONA_TRAIT_SCHEMA, f"特质 {name} 缺少 guidance")
    conflicts = entry.get("conflicts")
    if not isinstance(conflicts, list) or not all(
        isinstance(item, str) and item for item in conflicts
    ):
        raise PersonaError(E_PERSONA_TRAIT_SCHEMA, f"特质 {name} 的 conflicts 非法")
    modes = entry.get("modes")
    if not isinstance(modes, list) or not modes or not all(
        isinstance(item, str) for item in modes
    ):
        raise PersonaError(E_PERSONA_TRAIT_SCHEMA, f"特质 {name} 的 modes 非法")
    for mode in modes:
        if mode not in MODE_VALUES:
            raise PersonaError(
                E_PERSONA_TRAIT_MODE, f"特质 {name} 含未知模式：{mode}"
            )
    risk = entry.get("risk")
    if not isinstance(risk, str) or risk not in RISK_VALUES:
        raise PersonaError(
            E_PERSONA_TRAIT_SCHEMA, f"特质 {name} 的 risk 非法：{risk}"
        )
    return TraitDef(
        name=name,
        guidance=guidance,
        conflicts=tuple(conflicts),
        modes=tuple(modes),
        risk=risk,
    )


def _read_json(path: Path, label: str) -> object:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PersonaError(E_PERSONA_IO, f"无法读取{label}：{path}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PersonaError(E_PERSONA_IO, f"{label}不是合法 JSON：{path}") from exc


def trait_activations(
    events: list[EvidenceEvent], vocabulary: dict[str, TraitDef]
) -> tuple[TraitActivation, ...]:
    """Return every authorized enable/disable in evidence order.

    An unapproved trait proposal, an approval that points at nothing, and an
    approval whose text differs from the proposal are all hard failures:
    the trait layer never guesses that a model proposal was accepted.
    """
    known = {event.event_id: event for event in events}
    proposals = [
        event for event in events
        if event.type == "proposal" and event.target == TRAIT_TARGET
    ]
    approvals = _collect_approvals(events, known)
    for proposal in proposals:
        if proposal.event_id not in approvals:
            raise PersonaError(
                E_PERSONA_UNAPPROVED,
                f"提案没有批准记录：{proposal.event_id}",
            )
    activations: list[TraitActivation] = []
    seen: set[tuple[str, str]] = set()
    for event in events:
        if event.type != "directive" or event.kind not in (TRAIT_ON, TRAIT_OFF):
            continue
        if event.target:
            proposal = known[event.target]
            if (proposal.event_id, TRAIT_ON) in seen:
                continue
            seen.add((proposal.event_id, TRAIT_ON))
            activations.append(TraitActivation(
                name=_trait_name(proposal.text, vocabulary),
                event_id=proposal.event_id,
                order_id=event.event_id,
                origin=ORIGIN_APPROVED_PROPOSAL,
                enabled=True,
            ))
            continue
        activations.append(TraitActivation(
            name=_trait_name(event.text, vocabulary),
            event_id=event.event_id,
            order_id=event.event_id,
            origin=ORIGIN_USER,
            enabled=event.kind == TRAIT_ON,
        ))
    return tuple(sorted(activations, key=lambda item: item.order_id))


def _collect_approvals(
    events: list[EvidenceEvent], known: dict[str, EvidenceEvent]
) -> dict[str, EvidenceEvent]:
    approvals: dict[str, EvidenceEvent] = {}
    for event in events:
        if event.type != "directive" or not event.target:
            continue
        if event.kind not in (TRAIT_ON, TRAIT_OFF):
            continue
        proposal = known.get(event.target)
        if proposal is None:
            raise PersonaError(
                E_PERSONA_UNAPPROVED,
                f"批准指向不存在的提案：{event.target}",
            )
        if proposal.type != "proposal" or proposal.target != TRAIT_TARGET:
            raise PersonaError(
                E_PERSONA_UNAPPROVED,
                f"批准指向的不是特质提案：{event.target}",
            )
        if event.kind != TRAIT_ON:
            raise PersonaError(
                E_PERSONA_UNAPPROVED, f"trait_off 不能批准提案：{event.target}"
            )
        if event.text != proposal.text:
            raise PersonaError(
                E_PERSONA_UNAPPROVED,
                f"批准文本与提案不一致：{event.target}",
            )
        if event.event_id <= proposal.event_id:
            raise PersonaError(
                E_PERSONA_UNAPPROVED,
                f"批准必须先于提案之后：{event.target}",
            )
        approvals[proposal.event_id] = event
    return approvals


def _trait_name(text: str, vocabulary: dict[str, TraitDef]) -> str:
    hits = [name for name in vocabulary if name in text]
    if len(hits) != 1:
        raise PersonaError(
            E_PERSONA_INPUT, f"事件文本必须恰好包含一个特质名：{text}"
        )
    return hits[0]


def resolve_traits(
    events: list[EvidenceEvent],
    vocabulary: dict[str, TraitDef],
    mode: str = "support",
) -> TraitResolution:
    """Return the active traits for ``mode`` after cap, conflict and gate.

    The cap is checked on the enabled set before conflict resolution, so
    authorizing a sixth trait is rejected even if conflicts would later
    remove one. High-risk traits outside their modes are dropped with a
    readable reason; they never raise.
    """
    if mode not in MODE_VALUES:
        raise PersonaError(E_PERSONA_TRAIT_MODE, f"未知模式：{mode}")
    activations = trait_activations(events, vocabulary)
    enabled: dict[str, TraitActivation] = {}
    for item in activations:
        if item.enabled:
            enabled[item.name] = item
        else:
            enabled.pop(item.name, None)
    if len(enabled) > TRAIT_CAP:
        raise PersonaError(
            E_PERSONA_TRAIT_CAP,
            f"同时生效的特质超过 {TRAIT_CAP} 条：{len(enabled)}",
        )
    active = dict(enabled)
    conflicts: list[Conflict] = []
    for left, right in _conflict_pairs(vocabulary):
        if left not in active or right not in active:
            continue
        winner, loser, reason = _resolve_pair(
            vocabulary[left], vocabulary[right], active[left], active[right]
        )
        del active[loser]
        conflicts.append(Conflict(
            winner=winner,
            loser=loser,
            reason=reason,
            winner_event=enabled[winner].event_id,
            loser_event=enabled[loser].event_id,
        ))
    reasons: list[str] = []
    final: list[ActiveTrait] = []
    for name in sorted(active):
        definition = vocabulary[name]
        if definition.risk == "high" and mode not in definition.modes:
            reasons.append(
                f"{name} 在 {mode} 模式不生效（高风险，仅允许 "
                f"{', '.join(definition.modes)}）"
            )
            continue
        item = active[name]
        final.append(ActiveTrait(
            name=name,
            guidance=definition.guidance,
            risk=definition.risk,
            event_id=item.event_id,
            origin=item.origin,
        ))
    return TraitResolution(tuple(final), tuple(conflicts), tuple(reasons))


def _conflict_pairs(
    vocabulary: dict[str, TraitDef]
) -> list[tuple[str, str]]:
    pairs = {
        tuple(sorted((name, other)))
        for name, definition in vocabulary.items()
        for other in definition.conflicts
    }
    return sorted(pairs)


def _resolve_pair(
    left: TraitDef,
    right: TraitDef,
    left_use: TraitActivation,
    right_use: TraitActivation,
) -> tuple[str, str, str]:
    if RISK_RANK[left.risk] != RISK_RANK[right.risk]:
        if RISK_RANK[left.risk] < RISK_RANK[right.risk]:
            winner, loser = left_use, right_use
        else:
            winner, loser = right_use, left_use
        return (
            winner.name,
            loser.name,
            f"risk {_risk_of(winner, left, right)} beats "
            f"{_risk_of(loser, left, right)}",
        )
    winner, loser = (
        (left_use, right_use)
        if left_use.order_id > right_use.order_id
        else (right_use, left_use)
    )
    return (
        winner.name,
        loser.name,
        f"same risk, later activation wins {winner.order_id} > {loser.order_id}",
    )


def _risk_of(
    use: TraitActivation, left: TraitDef, right: TraitDef
) -> str:
    return left.risk if use.name == left.name else right.risk
