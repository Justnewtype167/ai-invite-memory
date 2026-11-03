"""Session-level streaming assembly (M14 / M14.1).

``StreamSession`` answers queries one turn at a time while keeping the bytes
identical to the batch path. ``context`` shares the pool-to-context code with
:func:`assemble`, so there is exactly one assembly semantics; the session only
adds chunking, a trigger cache and work accounting.

Retrieval is deliberately **not** incremental. bm25 depends on whole-store
statistics (N, avgdl, idf), so appending one event changes every score; any
implementation that skipped scoring would quietly change the bytes. Therefore
``retrieve_scored`` always equals ``Context.candidates`` and is reported, never
reduced.

Only the two time-trigger sub-queries are cached. Their real query keys differ:

* ``same_day`` depends on the month-day and year of ``now``;
* ``promises`` depends on the latest promise events, independent of the date.

Each cache entry is a ``(key, generation)`` pair. An unrelated append bumps
neither generation (the real saving); a matching append bumps exactly one.

Work is counted in entries, never in seconds (C14):

* ``trigger_scanned``  new evidence events inspected for invalidation;
* ``trigger_loaded``   rows actually fetched by trigger queries;
* ``trigger_reused``   sub-queries served from cache (0..2, not days);
* ``retrieve_scored``  bm25 entries, unchanged this round.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from aiinvite.recall.assemble import (
    Context,
    ContextItem,
    MAX_BUDGET,
    MIN_BUDGET,
    _assemble_pools,
)
from aiinvite.recall.errors import E_RC_BAD_BUDGET, E_RC_STREAM, RecallError
from aiinvite.recall.index import (
    INDEX_DIR,
    INDEX_FILE,
    IndexStatus,
    StoredEvent,
    index_status,
    is_promise,
    parse_now,
    read_tail_events,
    update_index,
)
from aiinvite.recall.retrieve import Hit
from aiinvite.recall.trigger import _combine, _promises, _same_day

CHUNK_SLOTS = ("recent", "recall", "longterm", "history")
RECENT_CHUNK_LIMIT = 5
SAME_DAY_CACHE = "same_day"
PROMISE_CACHE = "promises"


@dataclass(frozen=True)
class StreamStats:
    """Entry counts describing the work of one context call."""

    trigger_scanned: int
    trigger_loaded: int
    trigger_reused: int
    retrieve_scored: int

    def to_dict(self) -> dict[str, int]:
        """Return a deterministic JSON-ready view of these counts."""
        return {
            "trigger_scanned": self.trigger_scanned,
            "trigger_loaded": self.trigger_loaded,
            "trigger_reused": self.trigger_reused,
            "retrieve_scored": self.retrieve_scored,
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
        self._epoch = {SAME_DAY_CACHE: 0, PROMISE_CACHE: 0}
        self._cache: dict[str, tuple[tuple[object, ...], int, list[Hit]]] = {}
        self._seq: int | None = None
        self._identity: tuple[int, int] | None = None
        self._stats = StreamStats(0, 0, 0, 0)

    def context(self, query: str) -> Context:
        """Return the same bytes as the batch assembler, with work counts.

        A stale derived index is brought up to date first; the evidence chain
        is never sealed, rewritten or skipped. The trigger sub-queries are
        served from the cache when their key and generation still match.
        """
        status = index_status(self.store)
        if status.stale:
            status = update_index(self.store)
        moment = parse_now(self.now)
        key = (moment.strftime("%m-%d"), moment.year)
        scanned = self._apply_changes(status, key)
        same_day, same_reused, same_loaded = self._fetch(
            SAME_DAY_CACHE, key, lambda: _same_day(self.store, moment)
        )
        promises, promise_reused, promise_loaded = self._fetch(
            PROMISE_CACHE, (), lambda: _promises(self.store)
        )
        trigger_pool = _combine(same_day, promises)
        context = _assemble_pools(
            self.store, query, self.budget, moment, trigger_pool
        )
        self._stats = StreamStats(
            scanned,
            same_loaded + promise_loaded,
            same_reused + promise_reused,
            context.candidates,
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

    def _apply_changes(self, status: IndexStatus, key: tuple[str, int]) -> int:
        """Invalidate caches for new evidence and report how many were inspected.

        ``scanned`` counts the new events examined in this call: zero on a cold
        start, one after a single append, independent of the store size.
        """
        sequence = _sequence(status.lsn)
        identity = _index_identity(self.store)
        scanned = 0
        if self._seq is None:
            self._seq = sequence
            self._identity = identity
            return 0
        rebuilt = self._identity is not None and _was_rebuilt(identity, self._identity)
        if sequence < self._seq or rebuilt:
            self._invalidate()
        elif sequence > self._seq:
            events = read_tail_events(self.store, sequence - self._seq)
            scanned = len(events)
            self._scan_events(events, key)
        self._seq = sequence
        self._identity = identity
        return scanned

    def _scan_events(self, events: list[StoredEvent], key: tuple[str, int]) -> None:
        """Invalidate exactly the sub-query touched by these new events."""
        target_md, target_year = key
        same_day_hit = False
        promise_hit = False
        for event in events:
            if event.ts[5:10] == target_md and int(event.ts[:4]) < target_year:
                same_day_hit = True
            if is_promise(event.text):
                promise_hit = True
        if same_day_hit:
            self._epoch[SAME_DAY_CACHE] += 1
        if promise_hit:
            self._epoch[PROMISE_CACHE] += 1

    def _invalidate(self) -> None:
        """Invalidate both trigger caches, e.g. after a rollback or rebuild."""
        self._epoch[SAME_DAY_CACHE] += 1
        self._epoch[PROMISE_CACHE] += 1

    def _fetch(
        self,
        name: str,
        key: tuple[object, ...],
        producer: Callable[[], list[Hit]],
    ) -> tuple[list[Hit], int, int]:
        """Return ``(hits, reused, loaded)`` for one trigger sub-query."""
        entry = self._cache.get(name)
        if entry is not None and entry[0] == key and entry[1] == self._epoch[name]:
            return entry[2], 1, 0
        hits = producer()
        self._cache[name] = (key, self._epoch[name], hits)
        return hits, 0, len(hits)


def _sequence(event_id: str) -> int:
    try:
        return int(event_id[3:])
    except ValueError as exc:
        raise RecallError(E_RC_STREAM, f"非法事件 id：{event_id}") from exc


def _index_identity(store: Path) -> tuple[int, int]:
    """Return ``(inode, creation time)`` used to detect a full index rebuild.

    An incremental update writes into the same file, so the inode stays put;
    ``build_index`` removes the directory and creates a new file, so its inode
    changes. The creation time is the fallback for filesystems that report a
    zero inode.
    """
    database = store / INDEX_DIR / INDEX_FILE
    try:
        stat = database.stat()
    except OSError as exc:
        raise RecallError(E_RC_STREAM, f"无法读取索引：{database}") from exc
    return stat.st_ino, stat.st_ctime_ns


def _was_rebuilt(current: tuple[int, int], previous: tuple[int, int]) -> bool:
    """Return whether the index file was recreated rather than updated."""
    if current[0] != previous[0]:
        return True
    return current[0] == 0 and current[1] != previous[1]


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
