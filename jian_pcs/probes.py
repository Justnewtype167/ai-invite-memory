"""Probe set loading and schema validation for PCS."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from jian_pcs.errors import E_PCS_IO, E_PCS_SCHEMA, PcsError

DATA_PATH = Path(__file__).resolve().parent / "data" / "probes.jsonl"
PROBE_COUNT = 30
RULE_MAX_CHARS = 120
OPERATORS = (
    "must_contain_any",
    "must_not_contain_any",
    "max_chars",
    "max_questions",
    "must_ask_before",
    "max_sentences",
)
PROBE_FIELDS = ("probe_id", "rule", "prompt", "expect", "accept", "violation")
ACCEPT_MIN = 2
ACCEPT_MAX = 3


@dataclass(frozen=True)
class AskBefore:
    """Ordering check: the ``question`` must appear before the ``action``."""

    action: str
    question: str


@dataclass(frozen=True)
class Expect:
    """Deterministic pass conditions for one probe (all present must hold)."""

    must_contain_any: tuple[str, ...] = ()
    must_not_contain_any: tuple[str, ...] = ()
    max_chars: int | None = None
    max_questions: int | None = None
    must_ask_before: AskBefore | None = None
    max_sentences: int | None = None

    @classmethod
    def from_payload(cls, payload: object) -> "Expect":
        """Parse and validate an ``expect`` object from probe JSON."""
        if not isinstance(payload, dict):
            raise PcsError(E_PCS_SCHEMA, "expect 必须是对象")
        unknown = sorted(set(payload) - set(OPERATORS))
        if unknown:
            raise PcsError(E_PCS_SCHEMA, f"expect 含未知算子：{', '.join(unknown)}")
        ask = payload.get("must_ask_before")
        parsed_ask = None
        if ask is not None:
            parsed_ask = _parse_ask_before(ask)
        return cls(
            must_contain_any=_string_list(payload, "must_contain_any"),
            must_not_contain_any=_string_list(payload, "must_not_contain_any"),
            max_chars=_limit(payload, "max_chars"),
            max_questions=_limit(payload, "max_questions"),
            must_ask_before=parsed_ask,
            max_sentences=_limit(payload, "max_sentences"),
        )


@dataclass(frozen=True)
class Probe:
    """One probe: a rule, a prompt, its pass conditions and both fences.

    ``accept`` holds 2-3 legal replies in different wordings, including at
    least one paraphrase. ``violation`` holds one known-bad reply. The judge
    must pass every ``accept`` and fail the ``violation``; one direction alone
    cannot tell a strict judge from a broken one.
    """

    probe_id: str
    rule: str
    prompt: str
    expect: Expect
    accept: tuple[str, ...]
    violation: str


def validate_expect(payload: object) -> None:
    """Raise ``E_PCS_SCHEMA`` when an ``expect`` payload is not usable."""
    Expect.from_payload(payload)


def _parse_ask_before(value: object) -> AskBefore:
    if not isinstance(value, dict):
        raise PcsError(E_PCS_SCHEMA, "must_ask_before 必须是对象")
    if set(value) != {"action", "question"}:
        raise PcsError(E_PCS_SCHEMA, "must_ask_before 只允许 action / question")
    action = value["action"]
    question = value["question"]
    if not isinstance(action, str) or not action.strip():
        raise PcsError(E_PCS_SCHEMA, "must_ask_before.action 必须非空")
    if not isinstance(question, str) or not question.strip():
        raise PcsError(E_PCS_SCHEMA, "must_ask_before.question 必须非空")
    return AskBefore(action, question)


def _string_list(payload: dict[str, object], name: str) -> tuple[str, ...]:
    value = payload.get(name)
    if value is None:
        return ()
    if not isinstance(value, list) or not value:
        raise PcsError(E_PCS_SCHEMA, f"{name} 必须是非空数组")
    items = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise PcsError(E_PCS_SCHEMA, f"{name} 必须只含非空字符串")
        items.append(item)
    return tuple(items)


def _limit(payload: dict[str, object], name: str) -> int | None:
    value = payload.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PcsError(E_PCS_SCHEMA, f"{name} 必须是非负整数")
    return value


def _require_text(data: dict[str, object], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise PcsError(E_PCS_SCHEMA, f"探针字段 {name} 必须非空")
    return value


def _accept_list(value: object, line_no: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行 accept 必须是数组")
    if not ACCEPT_MIN <= len(value) <= ACCEPT_MAX:
        raise PcsError(
            E_PCS_SCHEMA,
            f"第 {line_no} 行 accept 必须 {ACCEPT_MIN}-{ACCEPT_MAX} 条",
        )
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行 accept 含空项")
        items.append(item)
    if len(set(items)) != len(items):
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行 accept 有重复")
    return tuple(items)


def _parse_probe(data: object, line_no: int) -> Probe:
    if not isinstance(data, dict):
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行不是对象")
    missing = [name for name in PROBE_FIELDS if name not in data]
    if missing:
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行缺字段：{', '.join(missing)}")
    extra = sorted(set(data) - set(PROBE_FIELDS))
    if extra:
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行有未知字段：{', '.join(extra)}")
    probe_id = _require_text(data, "probe_id")
    rule = _require_text(data, "rule")
    if len(rule) > RULE_MAX_CHARS:
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行 rule 超过 {RULE_MAX_CHARS} 字")
    prompt = _require_text(data, "prompt")
    violation = _require_text(data, "violation")
    return Probe(
        probe_id=probe_id,
        rule=rule,
        prompt=prompt,
        expect=Expect.from_payload(data["expect"]),
        accept=_accept_list(data["accept"], line_no),
        violation=violation,
    )


def load_probes(path: Path | None = None) -> tuple[Probe, ...]:
    """Load a probe JSONL file and validate every row.

    Defaults to ``jian_pcs/data/probes.jsonl``. Duplicate ids are refused so
    the report can always address each probe by name.
    """
    target = DATA_PATH if path is None else Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise PcsError(E_PCS_IO, f"无法读取探针文件：{target}") from exc
    probes: list[Probe] = []
    seen: set[str] = set()
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PcsError(E_PCS_IO, f"第 {line_no} 行不是 JSON") from exc
        probe = _parse_probe(data, line_no)
        if probe.probe_id in seen:
            raise PcsError(E_PCS_SCHEMA, f"重复探针 id：{probe.probe_id}")
        seen.add(probe.probe_id)
        probes.append(probe)
    if not probes:
        raise PcsError(E_PCS_SCHEMA, "探针文件为空")
    return tuple(probes)
