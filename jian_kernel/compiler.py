"""Deterministic kernel compilation (M4).

The compiler reads evidence only. It never looks inside ``kernel/``, never
asks for the wall clock, never uses randomness or floats.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from jian_cn.errors import CnError
from jian_cn.kinship import Kinship, lexicon_terms, parse_kinship
from jian_cn.timex import parse_time
from jian_recall.index import is_promise

from jian_kernel.errors import E_KN_IO, E_KN_NO_PROPOSAL, E_KN_UNSOURCED, KernelError
from jian_kernel.gate import check_proposals
from jian_kernel.kernel import (
    INITIAL_STATE,
    ORIGIN_RULE_FALLBACK,
    ORIGIN_RULE_ONLY,
    ORIGIN_WITH_PROPOSALS,
    STATE_MAX,
    STATE_MIN,
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
    parse_stamp,
    render_canon,
    stamp_text,
)
from jian_kernel.proposer import Proposal, Proposer, ReplayProposer

EVENT_TYPES = ("turn", "directive", "milestone", "feedback", "proposal")
PROMISE_DONE = ("已完成", "已办", "做到了")
FEEDBACK_TRUST = {"correction": -50, "praise": 20}
FIRST_DAY_INTIMACY = 5
GAP_DAYS = 30
GAP_NUMERATOR = 9
GAP_DENOMINATOR = 10

_TERMS = tuple(sorted(lexicon_terms(), key=lambda term: (-len(term), term)))
_CUE = re.compile(
    r"(?:大前|大后|上上|下下|今|明|去|前|昨|后|上|下|这)"
    r"(?:年|个月|月|个季度|季度|个季|季|星期|礼拜|周|天|日|晚|早)"
    r"|(?:[0-9]{1,2}|[一二三四五六七八九十]+|两|半)"
    r"(?:个月|月|个季度|季度|个季|季|星期|礼拜|周|天|日|晚|早|年)(?:前|后)"
    r"|周末|周初|周中|周末|月末|月初|月中|月底|年末|年初|年中|年底"
    r"|季度末|季末|季度初|季初"
)


def compile_kernel(
    store: Path, policy: Policy | None = None, proposer: Proposer | None = None
) -> Kernel:
    """Compile a kernel from all evidence, policy and proposer proposals.

    ``store/kernel`` is never read, so deleting it changes nothing.
    """
    return _compile(store, read_evidence(store), policy, proposer)


def _compile_prefix(
    store: Path, policy: Policy | None, head: str, proposer: Proposer | None = None
) -> Kernel:
    """Compile the evidence prefix ending at ``head`` (used by restore)."""
    events = [event for event in read_evidence(store) if event.event_id <= head]
    if not events:
        raise KernelError(E_KN_STALE, f"历史 head 不在证据中：{head}")
    return _compile(store, events, policy, proposer)


def _compile(
    store: Path,
    events: list[EvidenceEvent],
    policy: Policy | None,
    proposer: Proposer | None,
) -> Kernel:
    chosen = policy if policy is not None else Policy()
    source = proposer if proposer is not None else ReplayProposer()
    if not events:
        raise KernelError(E_KN_IO, "证据目录为空")
    moment = chosen.resolved_now(events[-1].stamp)
    check_proposals(events)
    style, rejected, groups = _select_style(events)
    origin = _resolve_origin(chosen, style)
    models = _model_ids(events)
    proposals = source.propose(store, chosen)
    content = [event for event in events if event.type != "proposal"]
    canon = _build_canon(content, proposals)
    state = _compute_state(content)
    edges, anchors = _build_graph(content)
    self_md = _render_self(content, moment, edges, groups)
    canon_md = render_canon(canon)
    graph = {
        "anchors": [anchor.to_payload() for anchor in anchors],
        "edges": [edge.to_payload() for edge in edges],
    }
    kid = kernel_kid(self_md, canon_md, state, graph, origin, models)
    return Kernel(
        kid=kid,
        head=events[-1].event_id,
        canon=canon,
        edges=edges,
        anchors=anchors,
        state=state,
        self_md=self_md,
        canon_md=canon_md,
        policy_hash=chosen.hash(moment),
        origin=origin,
        style=style,
        rejected=rejected,
        models=models,
    )


def read_evidence(store: Path) -> list[EvidenceEvent]:
    """Read every evidence line, ordered by numeric event id."""
    folder = store / "evidence"
    if not folder.is_dir():
        raise KernelError(E_KN_IO, f"缺少证据目录：{folder}")
    try:
        paths = sorted(folder.glob("seg-*.jsonl"))
    except OSError as exc:
        raise KernelError(E_KN_IO, f"无法读取证据目录：{folder}") from exc
    events: list[EvidenceEvent] = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise KernelError(E_KN_IO, f"无法读取证据段：{path}") from exc
        for line in lines:
            if line:
                events.append(_parse_event(line, path))
    if not events:
        raise KernelError(E_KN_IO, f"证据目录为空：{folder}")
    events.sort(key=lambda event: int(event.event_id.split("_")[1]))
    return events


def _parse_event(line: str, path: Path) -> EvidenceEvent:
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        raise KernelError(E_KN_IO, f"证据行无法解析：{path}") from exc
    if not isinstance(data, dict):
        raise KernelError(E_KN_IO, f"证据行不是对象：{path}")
    event_id = data.get("id")
    stamp = data.get("t")
    text = __import__("jian.event", fromlist=("event_text",)).event_text(data)
    event_type = data.get("type", "turn")
    kind = data.get("kind")
    target = data.get("target")
    model = data.get("model")
    prompt_sha = data.get("prompt_sha")
    quant = data.get("quant")
    weights_sha = data.get("weights_sha")
    temp_milli = data.get("temp_milli")
    seed = data.get("seed")
    if not isinstance(event_id, str) or not isinstance(stamp, str) \
            or not isinstance(text, str):
        raise KernelError(E_KN_IO, f"证据字段缺失：{path}")
    if event_type not in EVENT_TYPES:
        raise KernelError(E_KN_IO, f"未知事件类型 {event_type}：{path}")
    if kind is not None and not isinstance(kind, str):
        raise KernelError(E_KN_IO, f"证据 kind 不是字符串：{path}")
    if target is not None and not isinstance(target, str):
        raise KernelError(E_KN_IO, f"证据 target 不是字符串：{path}")
    for name, value in (("model", model), ("prompt_sha", prompt_sha),
                        ("quant", quant), ("weights_sha", weights_sha)):
        if value is not None and not isinstance(value, str):
            raise KernelError(E_KN_IO, f"证据 {name} 不是字符串：{path}")
    for name, value in (("temp_milli", temp_milli), ("seed", seed)):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int)
        ):
            raise KernelError(E_KN_IO, f"证据 {name} 不是整数：{path}")
    return EvidenceEvent(
        event_id, stamp_text(parse_stamp(stamp)), str(event_type), kind, text,
        target, model, prompt_sha, quant, weights_sha, temp_milli, seed,
    )


def _select_style(
    events: list[EvidenceEvent],
) -> tuple[tuple[str, ...], int, dict[str, tuple[str, ...]]]:
    """Return accepted lines, reject count and per-target sections.

    Every target has its own quota (``STYLE_MAX_PER_TARGET``) and its own
    character budget (``STYLE_TOTAL_MAX``). Lines follow numeric event order,
    each is cut to ``STYLE_TEXT_MAX``; anything that does not fit is counted
    as rejected instead of silently dropped.
    """
    proposals = ReplayProposer().style(events)
    accepted: list[str] = []
    rejected = 0
    used: dict[str, int] = {}
    counts: dict[str, int] = {}
    groups: dict[str, list[str]] = {target: [] for target, _ in STYLE_SECTIONS}
    for proposal in proposals:
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
    sections = {
        target: tuple(texts) for target, texts in groups.items() if texts
    }
    return tuple(accepted), rejected, sections


def _model_ids(events: list[EvidenceEvent]) -> tuple[str, ...]:
    """Return the sorted unique ``model/quant/weights_sha`` ids of proposers."""
    found: set[str] = set()
    for event in events:
        if event.type != "proposal" or not event.model:
            continue
        parts = [event.model]
        if event.quant:
            parts.append(event.quant)
        if event.weights_sha:
            parts.append(event.weights_sha)
        found.add("/".join(parts))
    return tuple(sorted(found))


def _resolve_origin(policy: Policy, style: tuple[str, ...]) -> str:
    """Return ``rule_only`` / ``with_proposals`` / ``rule_fallback``.

    A policy that requires proposals must not fall back silently: without
    ``allow_fallback`` the compile fails with ``E_KN_NO_PROPOSAL``. A live
    proposer failure sets ``force_fallback``, so even a partially successful
    round is marked as a rule fallback and the kid necessarily changes.
    """
    if policy.force_fallback:
        return ORIGIN_RULE_FALLBACK
    if style:
        return ORIGIN_WITH_PROPOSALS
    if policy.require_proposals:
        if policy.allow_fallback:
            return ORIGIN_RULE_FALLBACK
        raise KernelError(
            E_KN_NO_PROPOSAL,
            "策略要求提案但证据里没有；确认允许规则兜底请加 --allow-fallback",
        )
    return ORIGIN_RULE_ONLY


def _build_canon(
    events: list[EvidenceEvent], proposals: list[Proposal]
) -> tuple[CanonEntry, ...]:
    """Return canonical entries from directives, promises and proposals."""
    known = {event.event_id for event in events}
    entries: list[CanonEntry] = []
    for event in events:
        if event.type == "directive" and event.kind == "lock":
            entries.append(CanonEntry("directive", event.text, (event.event_id,)))
        elif is_promise(event.text) and not _cancelled(event, events):
            entries.append(CanonEntry("promise", event.text, (event.event_id,)))
    for proposal in proposals:
        if not proposal.evidence:
            raise KernelError(
                E_KN_UNSOURCED, f"提案缺少证据：{proposal.text}"
            )
        missing = [item for item in proposal.evidence if item not in known]
        if missing:
            raise KernelError(
                E_KN_UNSOURCED,
                f"提案引用了不存在的事件：{proposal.text} -> {missing[0]}",
            )
        entries.append(CanonEntry(proposal.kind, proposal.text, proposal.evidence))
    unique: dict[tuple[str, str, tuple[str, ...]], CanonEntry] = {}
    for entry in entries:
        unique.setdefault(entry.identity(), entry)
    return tuple(sorted(unique.values(), key=_canon_order))


def _canon_order(entry: CanonEntry) -> tuple[str, str, str]:
    first = entry.evidence[0] if entry.evidence else ""
    return (entry.kind, first, entry.text)


def _cancelled(event: EvidenceEvent, events: list[EvidenceEvent]) -> bool:
    later = [item for item in events if item.event_id > event.event_id]
    return any(
        marker in item.text for item in later for marker in PROMISE_DONE
    )


def _compute_state(events: list[EvidenceEvent]) -> dict[str, int]:
    """Accumulate integer-only state along the evidence sequence."""
    trust = INITIAL_STATE["trust"]
    intimacy = INITIAL_STATE["intimacy"]
    stability = INITIAL_STATE["stability"]
    seen_days: set[str] = set()
    previous: datetime | None = None
    for event in events:
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
    return {"intimacy": intimacy, "stability": stability, "trust": trust}


def _clamp(value: int) -> int:
    if value < STATE_MIN:
        return STATE_MIN
    if value > STATE_MAX:
        return STATE_MAX
    return value


def _build_graph(
    events: list[EvidenceEvent],
) -> tuple[tuple[GraphEdge, ...], tuple[Anchor, ...]]:
    """Return kinship edges and resolved time anchors, all with evidence ids."""
    edges: list[GraphEdge] = []
    anchors: list[Anchor] = []
    seen_edges: set[tuple[str, str, tuple[str, ...]]] = set()
    seen_anchors: set[tuple[str, str, str | None, str | None, str, str]] = set()
    for event in events:
        for term in _terms_in(event.text):
            parsed = parse_kinship(term)
            if parsed.kind != "kin" or not parsed.candidates:
                continue
            key = (event.event_id, term, parsed.candidates)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edges.append(GraphEdge(term, parsed.candidates, event.event_id))
        for expr in _cues_in(event.text):
            try:
                span = parse_time(expr, event.stamp)
            except CnError:
                continue
            key = (event.event_id, expr, span.start, span.end,
                   span.granularity, span.certainty)
            if key in seen_anchors:
                continue
            seen_anchors.add(key)
            anchors.append(Anchor(expr, span.start, span.end,
                                  span.granularity, span.certainty, event.event_id))
    edges.sort(key=lambda edge: (edge.event_id, edge.term))
    anchors.sort(key=lambda anchor: (anchor.event_id, anchor.expr))
    return tuple(edges), tuple(anchors)


def _terms_in(text: str) -> list[str]:
    found: list[str] = []
    index = 0
    while index < len(text):
        for term in _TERMS:
            if text.startswith(term, index):
                found.append(term)
                index += len(term)
                break
        else:
            index += 1
    return found


def _cues_in(text: str) -> list[str]:
    return [match.group(0) for match in _CUE.finditer(text)]


def _render_self(
    events: list[EvidenceEvent],
    moment: datetime,
    edges: tuple[GraphEdge, ...],
    groups: dict[str, tuple[str, ...]],
) -> str:
    """Render ``self.md`` from a fixed template plus statistics and sections."""
    lines = [
        "# Self",
        "",
        f"- known_days: {_known_days(events, moment)}",
        f"- events: {len(events)}",
        f"- active_months: {len({event.stamp[:7] for event in events})}",
        f"- top_kinship: {_top_kinship(edges)}",
        f"- latest_milestone: {_latest_milestone(events)}",
    ]
    for target, title in STYLE_SECTIONS:
        texts = groups.get(target, ())
        if not texts:
            continue
        lines.extend(["", f"## {title}", ""])
        lines.extend(f"- {text}" for text in texts)
    return "\n".join(lines) + "\n"


def _known_days(events: list[EvidenceEvent], moment: datetime) -> int:
    """Return the integer days between the first event and the policy clock."""
    if not events:
        return 0
    first = parse_stamp(events[0].stamp)
    return max(0, (moment.date() - first.date()).days)


def _top_kinship(edges: tuple[GraphEdge, ...]) -> str:
    """Return the most frequent kinship term, or ``-`` when there is none."""
    counts: dict[str, int] = {}
    for edge in edges:
        counts[edge.term] = counts.get(edge.term, 0) + 1
    if not counts:
        return "-"
    return sorted(counts, key=lambda term: (-counts[term], term))[0]


def _latest_milestone(events: list[EvidenceEvent]) -> str:
    """Return the text of the last milestone, or ``-`` when there is none."""
    milestones = [event for event in events if event.type == "milestone"]
    return milestones[-1].text if milestones else "-"
