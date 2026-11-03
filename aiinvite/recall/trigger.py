"""Rule-based triggers: same-day history and unfinished promises (M3)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from aiinvite.recall.errors import E_RC_IO, E_RC_STALE, RecallError
from aiinvite.recall.index import connect_index, index_status, parse_now
from aiinvite.recall.retrieve import Hit

SAME_DAY_LIMIT = 3
PROMISE_LIMIT = 2
SAME_DAY_SCORE = 1.0
PROMISE_SCORE = 0.8


def triggers(store: Path, now: str) -> list[Hit]:
    """Return same-day anniversary hits and unfinished promise hits.

    Same-day history is selected from earlier years with the same month and
    day, newest first, at most three. Unfinished promises are events marked
    as promises at index time, newest first, at most two. Same-day hits are
    ordered before promise hits and duplicate ids appear once.
    """
    status = index_status(store)
    if status.stale:
        raise RecallError(E_RC_STALE, "索引落后于证据，请先 update")
    return _triggers(store, parse_now(now))


def trigger_parts(store: Path, now: str) -> tuple[list[Hit], list[Hit]]:
    """Return the same-day and promise sub-query results separately.

    The two triggers have different query keys: ``same_day`` depends on the
    month-day and year of ``now``, while ``promises`` depends only on the
    latest promise events. Callers that cache them must invalidate them
    independently, so this function never merges the two lists.
    """
    status = index_status(store)
    if status.stale:
        raise RecallError(E_RC_STALE, "索引落后于证据，请先 update")
    return _parts(store, parse_now(now))


def _parts(store: Path, moment: datetime) -> tuple[list[Hit], list[Hit]]:
    return _same_day(store, moment), _promises(store)


def _triggers(store: Path, moment: datetime) -> list[Hit]:
    same_day, promises = _parts(store, moment)
    return _combine(same_day, promises)


def _same_day(store: Path, moment: datetime) -> list[Hit]:
    """Return the same-day anniversary rows for ``moment`` only."""
    rows = _rows(
        store,
        "SELECT t.event_id, t.seg, t.ts, d.text FROM ev_time AS t "
        "JOIN ev_data AS d ON d.event_id = t.event_id "
        "WHERE t.md = ? AND t.year < ? ORDER BY t.ts DESC LIMIT ?",
        (moment.strftime("%m-%d"), moment.year, SAME_DAY_LIMIT),
    )
    return _hits(rows, SAME_DAY_SCORE)


def _promises(store: Path) -> list[Hit]:
    """Return the latest promise rows only."""
    rows = _rows(
        store,
        "SELECT t.event_id, t.seg, t.ts, d.text FROM ev_time AS t "
        "JOIN ev_data AS d ON d.event_id = t.event_id "
        "WHERE d.is_promise = 1 ORDER BY t.ts DESC LIMIT ?",
        (PROMISE_LIMIT,),
    )
    return _hits(rows, PROMISE_SCORE)


def _rows(
    store: Path, statement: str, parameters: tuple[object, ...]
) -> list[sqlite3.Row]:
    connection = connect_index(store)
    try:
        rows = connection.execute(statement, parameters).fetchall()
    except sqlite3.DatabaseError as exc:
        raise RecallError(E_RC_IO, f"触发器查询失败：{exc}") from exc
    finally:
        connection.close()
    return rows


def _hits(rows: list[sqlite3.Row], score: float) -> list[Hit]:
    return [
        Hit(
            str(row["event_id"]),
            str(row["seg"]),
            str(row["ts"]),
            score,
            str(row["text"]),
        )
        for row in rows
    ]


def _combine(same_day: list[Hit], promises: list[Hit]) -> list[Hit]:
    """Merge two sub-query results in order, keeping the first of each id."""
    seen: set[str] = set()
    hits: list[Hit] = []
    for hit in list(same_day) + list(promises):
        if hit.event_id in seen:
            continue
        seen.add(hit.event_id)
        hits.append(hit)
    return hits
