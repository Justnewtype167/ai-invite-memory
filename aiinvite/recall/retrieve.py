"""Lexical retrieval over the derived FTS5 index (M3)."""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aiinvite.recall.errors import E_RC_IO, E_RC_STALE, RecallError
from aiinvite.recall.index import connect_index, index_status, parse_now, parse_stamp
from aiinvite.recall.rewrite import rewrite_query
from aiinvite.recall.synonyms import expand
from aiinvite.recall.tokenizer import bigrams

WEAK_SCORE = 0.25
CLUE_SCORE = 0.2
BRIDGE_MAX_SHARE = 2

DECAY_WINDOW_DAYS = 365.0
COVERAGE_FLOOR = 400
COVERAGE_SPAN = 600
MILLI = 1000


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
    rewriter=None,
    clues=None,
) -> list[Hit]:
    """Return up to ``k`` lexical hits, most relevant first.

    The query is converted to Han bigrams and matched with FTS5 using OR
    semantics. The bm25 relevance is normalized across this round's
    candidates, then weighted by query coverage and by a time decay factor
    relative to ``now`` (defaults to the current UTC time):

    ``score = bm25_normalized * (0.4 + 0.6 * coverage) * time_decay``

    Coverage is how many of the query bigrams appear in the event text, and
    it is computed with integer arithmetic only. No matches yield an empty
    list.
    """
    status = index_status(store)
    if status.stale:
        raise RecallError(E_RC_STALE, "索引落后于证据，请先 update")
    return search_at(store, query, k, parse_now(now), rewriter, clues)


def _search(store: Path, query: str, k: int, moment: datetime) -> list[Hit]:
    terms = list(dict.fromkeys(bigrams(query).split()))
    if not terms or k <= 0:
        return []
    # Synonym terms only widen the candidate set; coverage below still counts
    # the literal query terms, so a synonym match cannot outrank a literal one.
    extra = [term for term in expand(query) if term not in terms]
    match_terms = terms + extra
    match = " OR ".join('"' + term + '"' for term in match_terms)
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
    if not rows:
        return []
    relevances = [-float(row["rank"]) for row in rows]
    best = max(relevances)
    worst = min(relevances)
    span = best - worst
    total_terms = len(terms)
    hits: list[Hit] = []
    for row, relevance in zip(rows, relevances):
        event_id = str(row["event_id"])
        text = texts.get(event_id, "")
        elapsed = moment - parse_stamp(str(row["ts"]))
        days = max(0.0, elapsed.total_seconds() / 86400.0)
        decay = 0.5 + 0.5 * math.exp(-days / DECAY_WINDOW_DAYS)
        normalized = 1.0 if span == 0 else (relevance - worst) / span
        coverage = sum(1 for term in terms if term in text)
        factor = COVERAGE_FLOOR + COVERAGE_SPAN * coverage * MILLI // total_terms
        hits.append(
            Hit(event_id, str(row["seg"]), str(row["ts"]),
                normalized * decay * factor / MILLI, text)
        )
    hits.sort(key=lambda hit: (-hit.score, hit.event_id))
    return hits


def search_at(store, query, k, moment, rewriter=None, clues=None):
    """Lexical search, plus stored clues, at a fixed moment."""
    hits = _search(store, query, k, moment)
    if clues:
        extra = _clue_hits(store, query, clues, k, moment)
        if extra:
            hits = _merge(hits, extra, k)
    if rewriter is None or not _weak(hits):
        return hits
    # Only the failure path pays for inference.
    terms = rewrite_query(query, rewriter)
    if not terms:
        return hits
    widened = _search(store, " ".join(terms), k, moment)
    return _merge(hits, widened, k)


def _clue_hits(store, query, clues, k, moment):
    """Return memories whose stored clues match the question.

    Two guards keep a wrong clue from polluting recall:

    * an **entity** match is grounded in the memory text, so it always counts;
    * a **bridge** match is an unverified label, so it only counts while few
      memories share it. A bridge that half the store carries says nothing,
      and is dropped exactly like a stopword.
    """
    terms = list(dict.fromkeys(bigrams(query).split())) + list(expand(query))
    if not terms:
        return []
    grounded = []
    bridged = []
    for entry in clues:
        if len(entry) >= 3:
            event_id, entity_text, bridge_text = entry[0], entry[1], entry[2]
        else:
            event_id, entity_text, bridge_text = entry[0], entry[1], ""
        if any(term in entity_text for term in terms):
            grounded.append(Hit(event_id, "", "", CLUE_SCORE, entity_text))
            continue
        if any(term in bridge_text for term in terms):
            bridged.append(Hit(event_id, "", "", CLUE_SCORE / 2, bridge_text))
    if len(bridged) > BRIDGE_MAX_SHARE:
        bridged = []
    found = grounded + bridged
    found.sort(key=lambda hit: (-hit.score, hit.event_id))
    return found[:k]


def _weak(hits):
    """Return whether lexical recall looks empty or unsure."""
    if not hits:
        return True
    return hits[0].score < WEAK_SCORE


def _merge(first: list[Hit], second: list[Hit], k: int) -> list[Hit]:
    """Union two hit lists by event id, keeping the better score."""
    best: dict[str, Hit] = {}
    for hit in list(first) + list(second):
        known = best.get(hit.event_id)
        if known is None or hit.score > known.score:
            best[hit.event_id] = hit
    merged = sorted(best.values(), key=lambda hit: (-hit.score, hit.event_id))
    return merged[:k]

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
