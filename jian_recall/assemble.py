"""Budget-aware context assembly (M3).

Percentages are caps, not shares: an unused slot is never refilled from
another slot, because padding a context with irrelevant memories is worse
than sending fewer of them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from jian_recall.errors import E_RC_BAD_BUDGET, E_RC_STALE, RecallError
from jian_recall.index import index_status, load_meta, parse_now, read_tail_events
from jian_recall.retrieve import _search
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

    chosen: dict[str, ContextItem] = {}
    recent_items: list[ContextItem] = []
    trigger_items: list[ContextItem] = []
    retrieved_items: list[ContextItem] = []
    used_recent = 0
    used_trigger = 0
    used_retrieved = 0
    for event in recent_pool:
        tokens = estimate_tokens(event.text)
        if used_recent + tokens <= cap_recent:
            item = ContextItem(event.event_id, "recent", tokens, event.text)
            chosen[event.event_id] = item
            recent_items.append(item)
            used_recent += tokens
    for hit in trigger_pool:
        if hit.event_id in chosen:
            continue
        tokens = estimate_tokens(hit.text)
        if used_trigger + tokens <= cap_trigger:
            item = ContextItem(hit.event_id, "trigger", tokens, hit.text)
            chosen[hit.event_id] = item
            trigger_items.append(item)
            used_trigger += tokens
    for hit in retrieved_pool:
        if hit.event_id in chosen:
            continue
        tokens = estimate_tokens(hit.text)
        if used_retrieved + tokens <= cap_retrieved:
            item = ContextItem(hit.event_id, "retrieved", tokens, hit.text)
            chosen[hit.event_id] = item
            retrieved_items.append(item)
            used_retrieved += tokens

    ordered = trigger_items + retrieved_items + recent_items
    total = used_recent + used_trigger + used_retrieved
    candidates = len(
        {event.event_id for event in recent_pool}
        | {hit.event_id for hit in trigger_pool}
        | {hit.event_id for hit in retrieved_pool}
    )
    return Context(total, tuple(ordered), candidates)
