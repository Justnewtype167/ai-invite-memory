"""Kinship graph: lexicon lookup plus algorithmically parsed 的-composites."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from aiinvite.cn.errors import CnError, E_CN_DATA, E_CN_UNKNOWN_TERM
from aiinvite.cn.normalize import normalize

_DATA_DIR = Path(__file__).resolve().parent / "data"
_EDGE_NAMES = frozenset(
    {"F", "M", "H", "W", "OB", "YB", "OS", "YS", "S", "B", "s", "d"}
)
_KINDS = frozenset({"kin", "fictive", "social"})


@dataclass(frozen=True)
class Kinship:
    """Parsed kinship term with normalized edge candidates."""

    term: str
    candidates: tuple[str, ...]
    age: str | None
    ambiguous: bool
    kind: str
    role: str | None = None
    may_be_social: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly view; optional fields appear only when set."""
        out: dict[str, object] = {
            "term": self.term,
            "candidates": list(self.candidates),
            "age": self.age,
            "ambiguous": self.ambiguous,
            "kind": self.kind,
        }
        if self.role is not None:
            out["role"] = self.role
        if self.may_be_social:
            out["may_be_social"] = True
        return out


def _load_lexicon() -> dict[str, dict[str, object]]:
    path = _DATA_DIR / "kinship.json"
    try:
        payload = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise CnError(E_CN_DATA, f"无法读取 kinship.json：{exc}") from exc
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise CnError(E_CN_DATA, "kinship.json 缺少 entries 数组")
    table: dict[str, dict[str, object]] = {}
    for row in entries:
        if not isinstance(row, dict):
            raise CnError(E_CN_DATA, "kinship.json 条目不是对象")
        term = row.get("term")
        kind = row.get("kind")
        candidates = row.get("candidates")
        if not isinstance(term, str) or not isinstance(candidates, list):
            raise CnError(E_CN_DATA, "kinship.json 条目缺少 term/candidates")
        if kind not in _KINDS:
            raise CnError(E_CN_DATA, f"未知 kind：{kind}")
        if kind != "kin" and candidates:
            raise CnError(E_CN_DATA, f"非 kin 条目不得有候选：{term}")
        for cand in candidates:
            if not isinstance(cand, str):
                raise CnError(E_CN_DATA, f"候选不是字符串：{term}")
            if not all(edge in _EDGE_NAMES for edge in cand.split(".")):
                raise CnError(E_CN_DATA, f"候选边名非法：{term} -> {cand}")
        table[term] = row
    return table


_LEXICON = _load_lexicon()


def _as_kinship(term: str, row: dict[str, object]) -> Kinship:
    candidates = tuple(row["candidates"])  # type: ignore[arg-type]
    return Kinship(
        term=term,
        candidates=candidates,
        age=row.get("age"),  # type: ignore[arg-type]
        ambiguous=bool(row.get("ambiguous")),
        kind=str(row["kind"]),
        role=row.get("role"),  # type: ignore[arg-type]
        may_be_social=bool(row.get("may_be_social")),
    )


def _drop_pronoun(segment: str) -> str:
    if segment.startswith("我") and len(segment) > 1:
        stripped = segment[1:]
        if stripped in _LEXICON:
            return stripped
    return segment


def _parse_composite(term: str) -> Kinship:
    segments = term.split("的")
    if len(segments) < 2 or any(not seg for seg in segments):
        raise CnError(E_CN_UNKNOWN_TERM, f"未收录称谓：{term}")
    edges: list[tuple[str, ...]] = []
    kind = "kin"
    role: str | None = None
    for index, segment in enumerate(segments):
        key = _drop_pronoun(segment) if index == 0 else segment
        row = _LEXICON.get(key)
        if row is None:
            raise CnError(E_CN_UNKNOWN_TERM, f"未收录称谓：{term}（无法解析「{segment}」）")
        if row["kind"] != "kin":
            kind = str(row["kind"])
            role = row.get("role")  # type: ignore[assignment]
            edges = []
            break
        edges.append(tuple(row["candidates"]))  # type: ignore[arg-type]
    if kind != "kin":
        return Kinship(term=term, candidates=(), age=None, ambiguous=False,
                       kind=kind, role=role)
    combined: list[str] = [""]
    for candidates in edges:
        combined = [
            (prefix + "." + cand) if prefix else cand
            for prefix in combined
            for cand in candidates
        ]
    unique = tuple(dict.fromkeys(combined))
    return Kinship(term=term, candidates=unique, age=None,
                   ambiguous=len(unique) > 1, kind="kin")


def parse_kinship(text: str) -> Kinship:
    """Parse one kinship term; raise E_CN_UNKNOWN_TERM for anything not in data."""
    term = normalize(text).replace(" ", "")
    if not term:
        raise CnError(E_CN_UNKNOWN_TERM, "空称谓无法解析")
    row = _LEXICON.get(term)
    if row is not None:
        return _as_kinship(term, row)
    if "的" in term:
        return _parse_composite(term)
    raise CnError(E_CN_UNKNOWN_TERM, f"未收录称谓：{term}")


def lexicon_terms() -> tuple[str, ...]:
    """Return every term in the implementation lexicon."""
    return tuple(_LEXICON)
