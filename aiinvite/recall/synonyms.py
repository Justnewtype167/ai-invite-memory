"""Query-side synonym expansion: find the memory even when the words differ.

The index is lexical (Han bigrams), so "我养的小动物" cannot reach "我的狗叫阿黄"
on its own. A small curated group table bridges the vocabulary gap without
adding a dependency, a vector store, or any model call.

Expansion is append-only in effect: the original query terms still decide the
coverage score, so a synonym hit can surface a memory but cannot outrank a
literal one.
"""
from __future__ import annotations

import json
import pathlib

from aiinvite.recall.tokenizer import bigrams

DATA = pathlib.Path(__file__).resolve().parent / "data" / "synonyms.json"
MAX_EXPANSION_TERMS = 12


def load_groups(path: pathlib.Path | None = None) -> tuple[tuple[str, ...], ...]:
    """Return the synonym groups as tuples of terms."""
    target = path if path is not None else DATA
    raw = json.loads(target.read_text(encoding="utf-8"))
    groups = []
    for item in raw:
        if not isinstance(item, list):
            continue
        terms = tuple(str(term) for term in item if str(term).strip())
        if len(terms) >= 2:
            groups.append(terms)
    return tuple(groups)


def expand(
    query: str,
    groups: tuple[tuple[str, ...], ...] | None = None,
    limit: int = MAX_EXPANSION_TERMS,
) -> tuple[str, ...]:
    """Return extra bigram terms implied by the query, never the query itself."""
    table = groups if groups is not None else load_groups()
    base = set(bigrams(query).split())
    extra: list[str] = []
    seen = set(base)
    for group in table:
        if not any(term in query for term in group):
            continue
        for term in group:
            for piece in bigrams(term).split():
                if piece in seen:
                    continue
                seen.add(piece)
                extra.append(piece)
                if len(extra) >= limit:
                    return tuple(extra)
    return tuple(extra)
