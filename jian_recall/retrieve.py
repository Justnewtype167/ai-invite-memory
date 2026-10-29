"""Lexical retrieval over the derived FTS5 index (M3)."""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jian_recall.errors import E_RC_IO, E_RC_STALE, RecallError
from jian_recall.index import connect_index, index_status, parse_now, parse_stamp
from jian_recall.tokenizer import bigrams

DECAY_WINDOW_DAYS = 365.0


@dataclass(frozen=True)
class Hit:
    """One retrieval or trigger hit."""

    event_id: str
    seg: str
    ts: str
    score: float
    text: str


def search(
    store: Path,
    query: str,
    k: int = 50,
    now: str | None = None,
) -> list[Hit]:
    """Return up to ``k`` lexical hits, most relevant first.

    The query is converted to Han bigrams and matched with FTS5 using OR
    semantics. Each bm25 relevance is multiplied by a time decay factor
    relative to ``now`` (defaults to the current UTC time). No matches yield
    an empty list.
    """
    status = index_status(store)
    if status.stale:
        raise RecallError(E_RC_STALE, "索引落后于证据，请先 update")
    return _search(store, query, k, parse_now(now))


def _search(store: Path, query: str, k: int, moment: datetime) -> list[Hit]:
    terms = list(dict.fromkeys(bigrams(query).split()))
    if not terms or k <= 0:
        return []
    match = " OR ".join('"' + term + '"' for term in terms)
    connection = connect_index(store)
    try:
        rows = connection.execute(
            "SELECT event_id, seg, ts, bm25(fts_ev) AS rank FROM fts_ev "
            "WHERE fts_ev MATCH ? ORDER BY rank ASC LIMIT ?",
            (match, k),
        ).fetchall()
        texts = _texts_for(connection, [str(row["event_id"]) for row in rows])
    except sqlite3.DatabaseError as exc:
        raise RecallError(E_RC_IO, f"检索失败：{exc}") from exc
    finally:
        connection.close()
    hits: list[Hit] = []
    for row in rows:
        event_id = str(row["event_id"])
        elapsed = moment - parse_stamp(str(row["ts"]))
        days = max(0.0, elapsed.total_seconds() / 86400.0)
        relevance = -float(row["rank"])
        decay = 0.5 + 0.5 * math.exp(-days / DECAY_WINDOW_DAYS)
        hits.append(
            Hit(event_id, str(row["seg"]), str(row["ts"]),
                relevance * decay, texts.get(event_id, ""))
        )
    hits.sort(key=lambda hit: (-hit.score, hit.event_id))
    return hits


def _texts_for(connection: sqlite3.Connection, event_ids: list[str]) -> dict[str, str]:
    if not event_ids:
        return {}
    marks = ",".join("?" for _ in event_ids)
    result: dict[str, str] = {}
    for row in connection.execute(
        f"SELECT event_id, text FROM ev_data WHERE event_id IN ({marks})",
        event_ids,
    ):
        result[str(row["event_id"])] = str(row["text"])
    return result
