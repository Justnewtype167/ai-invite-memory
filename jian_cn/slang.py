"""Slang availability curve: born, peak, cringe, and a 0-1000 score."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from jian_cn.errors import CnError, E_CN_DATA

_DATA_DIR = Path(__file__).resolve().parent / "data"
_THRESHOLD = 600


@dataclass(frozen=True)
class SlangEntry:
    """One slang term with its three anchor years and evidence strength."""

    term: str
    born: int
    peak: int
    cringe: int
    tags: tuple[str, ...]
    source: str
    confidence: int


def _load_entries() -> dict[str, SlangEntry]:
    path = _DATA_DIR / "slang.json"
    try:
        payload = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise CnError(E_CN_DATA, f"无法读取 slang.json：{exc}") from exc
    rows = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise CnError(E_CN_DATA, "slang.json 缺少 entries 数组")
    table: dict[str, SlangEntry] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise CnError(E_CN_DATA, "slang.json 条目不是对象")
        try:
            entry = SlangEntry(
                term=str(row["term"]),
                born=int(row["born"]),
                peak=int(row["peak"]),
                cringe=int(row["cringe"]),
                tags=tuple(row.get("tags", [])),
                source=str(row["source"]),
                confidence=int(row["confidence"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CnError(E_CN_DATA, f"slang.json 条目字段错误：{exc}") from exc
        if not entry.born <= entry.peak <= entry.cringe:
            raise CnError(E_CN_DATA, f"年份顺序错误：{entry.term}")
        if not 0 <= entry.confidence <= 100:
            raise CnError(E_CN_DATA, f"confidence 越界：{entry.term}")
        table[entry.term] = entry
    return table


_ENTRIES = _load_entries()


def availability(term: str, on: date) -> int | None:
    """Return 0-1000 availability for ``term`` in ``on.year``; None if unknown."""
    entry = _ENTRIES.get(term)
    if entry is None:
        return None
    year = on.year
    if year < entry.born:
        return 0
    if year <= entry.peak:
        span = entry.peak - entry.born
        if span == 0:
            return 1000
        return 300 + (700 * (year - entry.born)) // span
    if year <= entry.cringe:
        span = entry.cringe - entry.peak
        if span == 0:
            return 400
        return 1000 - (600 * (year - entry.peak)) // span
    return 200


def usable(term: str, on: date, threshold: int = _THRESHOLD) -> bool:
    """Return True when the term scores at least ``threshold``."""
    score = availability(term, on)
    if score is None:
        return False
    return score >= threshold


def explain(term: str, on: date) -> str:
    """Return one plain-language sentence for ``term`` at ``on``."""
    entry = _ENTRIES.get(term)
    if entry is None:
        return "未收录"
    year = on.year
    if year < entry.born:
        return f"{entry.born} 年才开始流行，{year} 年尚未出现"
    if year <= entry.peak:
        return f"{entry.peak} 年峰值，{year} 年仍在流行"
    return f"{entry.peak} 年峰值，已过时 {year - entry.peak} 年"


def lifespan(term: str) -> dict[str, object] | None:
    """Return born/peak/cringe for ``term``; None when the term is unknown."""
    entry = _ENTRIES.get(term)
    if entry is None:
        return None
    return {
        "term": entry.term,
        "born": entry.born,
        "peak": entry.peak,
        "cringe": entry.cringe,
        "tags": list(entry.tags),
        "source": entry.source,
        "confidence": entry.confidence,
    }
