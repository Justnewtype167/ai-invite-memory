"""Rule-based triggers: same-day history and unfinished promises (M3)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from jian_recall.errors import E_RC_IO, E_RC_STALE, RecallError
from jian_recall.index import connect_index, index_status, parse_now
from jian_recall.retrieve import Hit

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


def _triggers(store: Path, moment: datetime) -> list[Hit]:
    month_day = moment.strftime("%m-%d")
    year = moment.year
    connection = connect_index(store)
    try:
        same_day = connection.execute(
            "SELECT t.event_id, t.seg, t.ts, d.text FROM ev_time AS t "
            "JOIN ev_data AS d ON d.event_id = t.event_id "
            "WHERE t.md = ? AND t.year < ? ORDER BY t.ts DESC LIMIT ?",
            (month_day, year, SAME_DAY_LIMIT),
        ).fetchall()
        promises = connection.execute(
            "SELECT t.event_id, t.seg, t.ts, d.text FROM ev_time AS t "
            "JOIN ev_data AS d ON d.event_id = t.event_id "
            "WHERE d.is_promise = 1 ORDER BY t.ts DESC LIMIT ?",
            (PROMISE_LIMIT,),
        ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise RecallError(E_RC_IO, f"触发器查询失败：{exc}") from exc
    finally:
        connection.close()
    seen: set[str] = set()
    hits: list[Hit] = []
    for row, score in _tagged(same_day, SAME_DAY_SCORE) + _tagged(
        promises, PROMISE_SCORE
    ):
        event_id = str(row["event_id"])
        if event_id in seen:
            continue
        seen.add(event_id)
        hits.append(
            Hit(event_id, str(row["seg"]), str(row["ts"]), score, str(row["text"]))
        )
    return hits


def _tagged(rows: list[sqlite3.Row], score: float) -> list[tuple[sqlite3.Row, float]]:
    return [(row, score) for row in rows]
