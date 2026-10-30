"""Probe set loading and schema validation for PCS."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from jian_pcs.errors import E_PCS_IO, E_PCS_SCHEMA, PcsError

DATA_PATH = Path(__file__).resolve().parent / "data" / "probes.jsonl"
HARD_DATA_PATH = Path(__file__).resolve().parent / "data" / "probes_hard.jsonl"
CALIBRATION_PATH = Path(__file__).resolve().parent / "data" / "calibration.json"
PROBE_COUNT = 30
HARD_PROBE_COUNT = 18
HARD_KINDS = ("multi_turn", "contradiction", "pressure")
CALIBRATION_LOW = 0.50
CALIBRATION_HIGH = 0.90
RULE_MAX_CHARS = 120
OPERATORS = (
    "must_contain_any",
    "must_not_contain_any",
    "max_chars",
    "max_questions",
    "must_ask_before",
    "max_sentences",
    "must_not_apologize",
    "max_agreement_shifts",
)
PROBE_FIELDS = ("probe_id", "rule", "prompt", "expect", "accept", "violation")
HARD_FIELDS = ("probe_id", "kind", "rule", "turns", "expect_final", "accept", "violation")
TURN_MIN = 2
TURN_MAX = 6
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
    must_not_apologize: bool = False
    max_agreement_shifts: int | None = None

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
            must_not_apologize=_flag(payload, "must_not_apologize"),
            max_agreement_shifts=_limit(payload, "max_agreement_shifts"),
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
    kind: str = "single_turn"
    turns: tuple[str, ...] = ()


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


def _flag(payload: dict[str, object], name: str) -> bool:
    value = payload.get(name)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise PcsError(E_PCS_SCHEMA, f"{name} 必须是布尔值")
    return value


def _turn_list(value: object, line_no: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行 turns 必须是数组")
    if not TURN_MIN <= len(value) <= TURN_MAX:
        raise PcsError(
            E_PCS_SCHEMA, f"第 {line_no} 行 turns 必须 {TURN_MIN}-{TURN_MAX} 轮"
        )
    turns = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行 turns 含空项")
        turns.append(item)
    return tuple(turns)


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


def _parse_single_probe(data: dict[str, object], line_no: int) -> Probe:
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


def _parse_hard_probe(data: dict[str, object], line_no: int) -> Probe:
    missing = [name for name in HARD_FIELDS if name not in data]
    if missing:
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行缺字段：{', '.join(missing)}")
    extra = sorted(set(data) - set(HARD_FIELDS))
    if extra:
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行有未知字段：{', '.join(extra)}")
    probe_id = _require_text(data, "probe_id")
    kind = _require_text(data, "kind")
    if kind not in HARD_KINDS:
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行 kind 非法：{kind}")
    rule = _require_text(data, "rule")
    if len(rule) > RULE_MAX_CHARS:
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行 rule 超过 {RULE_MAX_CHARS} 字")
    turns = _turn_list(data["turns"], line_no)
    violation = _require_text(data, "violation")
    return Probe(
        probe_id=probe_id,
        rule=rule,
        prompt=turns[-1],
        expect=Expect.from_payload(data["expect_final"]),
        accept=_accept_list(data["accept"], line_no),
        violation=violation,
        kind=kind,
        turns=turns,
    )


def _parse_probe(data: object, line_no: int) -> Probe:
    if not isinstance(data, dict):
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行不是对象")
    if "turns" in data or "expect_final" in data:
        return _parse_hard_probe(data, line_no)
    return _parse_single_probe(data, line_no)


def _load_file(target: Path) -> tuple[Probe, ...]:
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


def load_probes(path: Path | None = None) -> tuple[Probe, ...]:
    """Load the M6 probe set (or an explicit file); signature stayed unchanged.

    Defaults to ``jian_pcs/data/probes.jsonl``. Duplicate ids are refused so
    the report can always address each probe by name.
    """
    return _load_file(DATA_PATH if path is None else Path(path))


def load_hard_probes(path: Path | None = None) -> tuple[Probe, ...]:
    """Load the M7 hard probe set: multi-turn, contradiction and pressure."""
    return _load_file(HARD_DATA_PATH if path is None else Path(path))


def load_all_probes() -> tuple[Probe, ...]:
    """Return the M6 and M7 probe sets merged, with ids checked across both."""
    merged = load_probes() + load_hard_probes()
    ids = [probe.probe_id for probe in merged]
    if len(set(ids)) != len(ids):
        raise PcsError(E_PCS_SCHEMA, "M6 与 M7 探针 id 冲突")
    return merged
