"""Budget-aware context assembly (M3).

Percentages are caps, not shares: an unused slot is never refilled from
another slot, because padding a context with irrelevant memories is worse
than sending fewer of them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from jian.canonical import dumps
from jian_cn.normalize import normalize

from jian_recall.errors import E_RC_BAD_BUDGET, E_RC_STALE, RecallError
from jian_recall.index import (
    StoredEvent,
    index_status,
    load_meta,
    parse_now,
    read_tail_events,
)
from jian_recall.retrieve import Hit, _search
from jian_recall.tokenizer import estimate_tokens
from jian_recall.trigger import _triggers

RECENT_LIMIT = 8
MIN_BUDGET = 256
MAX_BUDGET = 200000
RETRIEVE_K = 50


@dataclass(frozen=True)
class ContextItem:
    """One assembled context item."""

    event_id: str
    slot: str
    tokens: int
    text: str
    merged: tuple[str, ...] = ()


@dataclass(frozen=True)
class Context:
    """An assembled context and its token accounting."""

    total_tokens: int
    items: tuple[ContextItem, ...]
    candidates: int

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-ready view of this context."""
        return {
            "total_tokens": self.total_tokens,
            "candidates": self.candidates,
            "items": [
                {
                    "event_id": item.event_id,
                    "slot": item.slot,
                    "tokens": item.tokens,
                    "text": item.text,
                    "merged": list(item.merged),
                }
                for item in self.items
            ],
        }

    def to_json(self) -> str:
        """Serialize this context deterministically, without spaces."""
        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )


def assemble(
    store: Path,
    query: str,
    budget: int = 4096,
    now: str | None = None,
) -> Context:
    """Assemble a context within ``budget`` tokens.

    Slot caps are 25% for recent events, 10% for triggers, and the rest for
    retrieved hits. The three slots never borrow from each other, so the
    total can stay below the budget when candidates are scarce. Output order
    is fixed: trigger, retrieved by score, recent by time. When candidates
    overflow their caps, retrieved hits are dropped from the tail first.

    Items are deduplicated by ``sha256(normalize(text))``. The surviving
    item keeps the highest priority (trigger > retrieved > recent), then the
    highest score; merged event ids are recorded in ``item.merged`` and the
    output order is unchanged.
    """
    if isinstance(budget, bool) or not isinstance(budget, int):
        raise RecallError(E_RC_BAD_BUDGET, "budget 必须是整数")
    if budget < MIN_BUDGET or budget > MAX_BUDGET:
        raise RecallError(E_RC_BAD_BUDGET, "budget 必须在 256-200000 之间")
    moment = parse_now(now)
    status = index_status(store)
    if status.stale:
        raise RecallError(E_RC_STALE, "索引落后于证据，请先 update")
    cap_recent = budget * 25 // 100
    cap_trigger = budget * 10 // 100
    cap_retrieved = budget - cap_recent - cap_trigger

    meta = load_meta(store)
    recent_pool = list(
        reversed(read_tail_events(store, RECENT_LIMIT, meta.get("last_seg")))
    )
    trigger_pool = _triggers(store, moment)
    retrieved_pool = _search(store, query, RETRIEVE_K, moment)

    rows = _candidates(recent_pool, trigger_pool, retrieved_pool)
    groups: dict[str, list[_Candidate]] = {}
    for candidate in rows:
        groups.setdefault(candidate.key, []).append(candidate)
    leaders = {
        key: min(group, key=lambda row: (row.priority, -row.score, row.order))
        for key, group in groups.items()
    }
    merged = {
        leader.event_id: tuple(sorted({
            row.event_id for row in group if row.event_id != leader.event_id
        }))
        for key, group in groups.items()
        for leader in (leaders[key],)
    }

    recent_items: list[ContextItem] = []
    trigger_items: list[ContextItem] = []
    retrieved_items: list[ContextItem] = []
    chosen_ids: set[str] = set()
    used_keys: set[str] = set()
    used = {"recent": 0, "trigger": 0, "retrieved": 0}
    caps = {"recent": cap_recent, "trigger": cap_trigger,
            "retrieved": cap_retrieved}
    for candidate in rows:
        leader = leaders[candidate.key]
        if candidate.event_id != leader.event_id or candidate.key in used_keys:
            continue
        if candidate.event_id in chosen_ids:
            continue
        if used[candidate.slot] + candidate.tokens > caps[candidate.slot]:
            continue
        items = {
            "recent": recent_items,
            "trigger": trigger_items,
            "retrieved": retrieved_items,
        }[candidate.slot]
        items.append(ContextItem(
            candidate.event_id, candidate.slot, candidate.tokens,
            candidate.text, merged.get(candidate.event_id, ()),
        ))
        chosen_ids.add(candidate.event_id)
        used_keys.add(candidate.key)
        used[candidate.slot] += candidate.tokens

    ordered = trigger_items + retrieved_items + recent_items
    used_recent = used["recent"]
    used_trigger = used["trigger"]
    used_retrieved = used["retrieved"]
    total = used_recent + used_trigger + used_retrieved
    candidates = len(
        {event.event_id for event in recent_pool}
        | {hit.event_id for hit in trigger_pool}
        | {hit.event_id for hit in retrieved_pool}
    )
    return Context(total, tuple(ordered), candidates)


@dataclass(frozen=True)
class _Candidate:
    """One pool entry before text-level deduplication."""

    event_id: str
    slot: str
    priority: int
    order: int
    score: float
    tokens: int
    text: str
    key: str


def _candidates(
    recent_pool: list[StoredEvent],
    trigger_pool: list[Hit],
    retrieved_pool: list[Hit],
) -> list[_Candidate]:
    """Flatten the three pools with their dedupe key and priority."""
    rows: list[_Candidate] = []
    for order, event in enumerate(recent_pool):
        rows.append(_Candidate(
            event.event_id, "recent", 2, order, 0.0,
            estimate_tokens(event.text), event.text, _dedupe_key(event.text),
        ))
    for order, hit in enumerate(trigger_pool):
        rows.append(_Candidate(
            hit.event_id, "trigger", 0, order, hit.score,
            estimate_tokens(hit.text), hit.text, _dedupe_key(hit.text),
        ))
    for order, hit in enumerate(retrieved_pool):
        rows.append(_Candidate(
            hit.event_id, "retrieved", 1, order, hit.score,
            estimate_tokens(hit.text), hit.text, _dedupe_key(hit.text),
        ))
    return rows


def _dedupe_key(text: str) -> str:
    """Return ``sha256`` over the canonical view of the normalized text."""
    return hashlib.sha256(dumps({"t": normalize(text)})).hexdigest()
