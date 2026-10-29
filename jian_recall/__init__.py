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
from jian_recall.tokenizer import bigrams, estimate_tokens
from jian_recall.trigger import triggers

__all__ = [
    "Context",
    "ContextItem",
    "Hit",
    "IndexStatus",
    "RecallError",
    "assemble",
    "bigrams",
    "build_index",
    "estimate_tokens",
    "index_status",
    "search",
    "triggers",
    "update_index",
]
