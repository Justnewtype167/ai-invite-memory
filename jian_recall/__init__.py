"""Jian recall: token estimation, FTS5 retrieval and budget assembly (M3).

Zero model calls, zero network access, standard library only.
"""

from __future__ import annotations

from jian_recall.assemble import Context, ContextItem, assemble
from jian_recall.errors import RecallError
from jian_recall.index import (
    IndexStatus,
    build_index,
    index_status,
    update_index,
)
from jian_recall.retrieve import Hit, search
from jian_recall.stream import Chunk, StreamSession, StreamStats, join_chunks
from jian_recall.tokenizer import bigrams, estimate_tokens
from jian_recall.trigger import triggers

__all__ = [
    "Chunk",
    "Context",
    "ContextItem",
    "Hit",
    "IndexStatus",
    "RecallError",
    "StreamSession",
    "StreamStats",
    "assemble",
    "bigrams",
    "build_index",
    "estimate_tokens",
    "index_status",
    "join_chunks",
    "search",
    "triggers",
    "update_index",
]
