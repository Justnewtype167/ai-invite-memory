"""Session-level streaming assembly (M14).

``StreamSession`` answers queries one turn at a time while keeping the bytes
identical to the batch path. ``context`` delegates to :func:`assemble`, so
there is exactly one assembly semantics; the session only adds chunking and
work accounting.

Work is counted in entries, never in seconds (C14). Each turn the session
enumerates the same three candidate pools the batch assembler uses (recent
tail, triggers, retrieved hits) and compares the candidate ids with the ids it
has already scored:

* ``scored``  entries that needed scoring for the first time in this session;
* ``reused``  entries whose score and token estimate were already cached;
* ``evicted`` candidates that the caps or text deduplication dropped.

``scored + reused`` therefore always equals ``Context.candidates``. The
number of candidates is bounded by ``RECENT_LIMIT``, the trigger caps and
``RETRIEVE_K``, so it never grows with the size of the evidence store.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from jian_recall.assemble import (
    Context,
    ContextItem,
    MAX_BUDGET,
    MIN_BUDGET,
    RECENT_LIMIT,
    RETRIEVE_K,
    assemble,
)
from jian_recall.errors import E_RC_BAD_BUDGET, E_RC_STREAM, RecallError
from jian_recall.index import (
    index_status,
    load_meta,
    parse_now,
    read_tail_events,
    update_index,
)
from jian_recall.retrieve import search
from jian_recall.trigger import triggers

CHUNK_SLOTS = ("recent", "recall", "longterm", "history")
RECENT_CHUNK_LIMIT = 5


@dataclass(frozen=True)
class StreamStats:
    """Entry counts describing the work of one context call."""

    scored: int
    reused: int
    evicted: int

    def to_dict(self) -> dict[str, int]:
        """Return a deterministic JSON-ready view of these counts."""
        return {
            "scored": self.scored,
            "reused": self.reused,
            "evicted": self.evicted,
        }


@dataclass(frozen=True)
class Chunk:
    """One streaming chunk: a contiguous slice of the final context.

    ``start`` is the position of this chunk's first item in the full context,
    so chunks can be emitted in priority order and still be joined back byte
    for byte.
    """

    index: int
    slot: str
    start: int
    items: tuple[ContextItem, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-ready view of this chunk."""
        return {
            "index": self.index,
            "slot": self.slot,
            "start": self.start,
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
        """Serialize this chunk deterministically, without spaces."""
        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )


def join_chunks(chunks: list[Chunk]) -> tuple[ContextItem, ...]:
    """Join priority-ordered chunks back into the context's item order.

    Chunks arrive in emission order, which is recent, recall, longterm,
    history. Their ``start`` positions are the only authority on the final
    order; a gap or overlap is a contract violation, not something to paper
    over.
    """
    ordered = sorted(chunks, key=lambda chunk: chunk.start)
    cursor = 0
    items: list[ContextItem] = []
    for chunk in ordered:
        if chunk.start != cursor:
            raise RecallError(
                E_RC_STREAM,
                f"块边界不连续：期望 {cursor}，实际 {chunk.start}",
            )
        items.extend(chunk.items)
        cursor += len(chunk.items)
    return tuple(items)


class StreamSession:
    """A session that assembles context incrementally across turns."""

    def __init__(
        self, store: Path, budget: int = 4096, now: str | None = None
    ) -> None:
        """Open a session over ``store``.

        ``now`` pins the reference time so trigger selection and time decay do
        not drift between turns; when omitted, each turn uses the current UTC
        time. Both ``context`` and the batch assembler resolve the same value.
        """
        if isinstance(budget, bool) or not isinstance(budget, int):
            raise RecallError(E_RC_BAD_BUDGET, "budget 必须是整数")
        if budget < MIN_BUDGET or budget > MAX_BUDGET:
            raise RecallError(E_RC_BAD_BUDGET, "budget 必须在 256-200000 之间")
        self.store = Path(store)
        self.budget = budget
        self.now = now
        self._scored: set[str] = set()
        self._stats = StreamStats(0, 0, 0)

    def context(self, query: str) -> Context:
        """Return the same bytes as the batch assembler, with work counts.

        A stale derived index is brought up to date first; the evidence chain
        is never sealed, rewritten or skipped. Assembly itself is delegated to
        :func:`assemble`, so there is a single source of truth.
        """
        status = index_status(self.store)
        if status.stale:
            update_index(self.store)
        stamp = parse_now(self.now).isoformat()
        context = assemble(self.store, query, self.budget, stamp)
        pool = self._pool_ids(query, stamp)
        fresh = len(pool - self._scored)
        reused = len(pool & self._scored)
        self._scored |= pool
        self._stats = StreamStats(
            fresh, reused, context.candidates - len(context.items)
        )
        return context

    def iter_context(self, query: str) -> Iterator[Chunk]:
        """Yield chunks in fixed priority order.

        The first chunk is the five most recent turns, then query hits, then
        long-term triggers, then the remaining history. Empty chunks are
        skipped, so the sequence is stable for a given context.
        """
        context = self.context(query)
        return _chunks(context)

    def stats(self) -> StreamStats:
        """Return the entry counts of the most recent context call."""
        return self._stats

    def _pool_ids(self, query: str, stamp: str) -> set[str]:
        """Return the ids of the three candidate pools for this turn."""
        meta = load_meta(self.store)
        recent = read_tail_events(self.store, RECENT_LIMIT, meta.get("last_seg"))
        longterm = triggers(self.store, stamp)
        retrieved = search(self.store, query, RETRIEVE_K, stamp)
        return (
            {event.event_id for event in recent}
            | {hit.event_id for hit in longterm}
            | {hit.event_id for hit in retrieved}
        )


def _chunks(context: Context) -> Iterator[Chunk]:
    """Split a context into the fixed four priority slices."""
    recent: list[tuple[int, ContextItem]] = []
    recall: list[tuple[int, ContextItem]] = []
    longterm: list[tuple[int, ContextItem]] = []
    for position, item in enumerate(context.items):
        if item.slot == "recent":
            recent.append((position, item))
        elif item.slot == "retrieved":
            recall.append((position, item))
        elif item.slot == "trigger":
            longterm.append((position, item))
    pieces = (
        ("recent", recent[:RECENT_CHUNK_LIMIT]),
        ("recall", recall),
        ("longterm", longterm),
        ("history", recent[RECENT_CHUNK_LIMIT:]),
    )
    index = 0
    for slot, pairs in pieces:
        if not pairs:
            continue
        yield Chunk(index, slot, pairs[0][0], tuple(item for _, item in pairs))
        index += 1
