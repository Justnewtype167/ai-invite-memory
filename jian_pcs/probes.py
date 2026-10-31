"""Probe set loading and schema validation for PCS.

Scoring rules come from a rule file: ``rules_v2.json`` for the support mode
(R1-R6) and ``rules_consult.json`` for the consult mode (Q1-Q5). Each probe
names a rule id and carries no limits of its own, except the R5 candidate
substrings that must be read from the probe's own input.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from jian_pcs.errors import E_PCS_IO, E_PCS_SCHEMA, PcsError

DATA_PATH = Path(__file__).resolve().parent / "data" / "probes.jsonl"
MORE_DATA_PATH = Path(__file__).resolve().parent / "data" / "probes_more.jsonl"
REAL_DATA_PATH = Path(__file__).resolve().parent / "data" / "probes_real.jsonl"
HARD_DATA_PATH = Path(__file__).resolve().parent / "data" / "probes_hard.jsonl"
CONSULT_DATA_PATH = Path(__file__).resolve().parent / "data" / "probes_consult.jsonl"
RULES_PATH = Path(__file__).resolve().parent / "data" / "rules_v2.json"
CONSULT_RULES_PATH = Path(__file__).resolve().parent / "data" / "rules_consult.json"
CALIBRATION_PATH = Path(__file__).resolve().parent / "data" / "calibration.json"

MODE_SUPPORT = "support"
MODE_CONSULT = "consult"
MODES = (MODE_SUPPORT, MODE_CONSULT)


def _count_probes(path: Path) -> int:
    """Count non-blank lines in a probe file, so no count is hard-coded."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PcsError(E_PCS_IO, f"无法读取探针文件：{path}") from exc
    return sum(1 for line in text.splitlines() if line.strip())


PROBE_COUNT = _count_probes(DATA_PATH)
MORE_PROBE_COUNT = _count_probes(MORE_DATA_PATH)
REAL_PROBE_COUNT = _count_probes(REAL_DATA_PATH)
CONSULT_PROBE_COUNT = _count_probes(CONSULT_DATA_PATH)
HARD_PROBE_COUNT = 18
HARD_KINDS = ("multi_turn", "contradiction", "pressure")
CALIBRATION_LOW = 0.50
CALIBRATION_HIGH = 0.90
RULE_MAX_CHARS = 120
RULE_IDS = ("R1", "R2", "R3", "R4", "R5", "R6")
CONSULT_RULE_IDS = ("Q1", "Q2", "Q3", "Q4", "Q5")
V2_OPERATORS = (
    "first_is_question",
    "none_of",
    "max_sentences_and_questions",
    "max_chars",
    "shares_two_chars_with_source",
)
CONSULT_OPERATORS = (
    "answer_directly",
    "no_evasion",
    "max_chars",
    "none_of",
    "advice_allowed",
)
PROBE_FIELDS = ("probe_id", "rule", "prompt", "expect", "accept", "violation")
PROBE_OPTIONAL_FIELDS = ("mode",)
HARD_FIELDS = ("probe_id", "kind", "rule", "turns", "expect_final", "accept", "violation")
EXPECT_FIELDS = ("op", "echo_source")
TURN_MIN = 2
TURN_MAX = 6
ACCEPT_MIN = 2
ACCEPT_MAX = 3


@dataclass(frozen=True)
class Rule:
    """One scoring rule: the short text plus its executable program.

    ``op`` and its numeric or word-list arguments are read from
    ``rules_v2.json`` and never repeated in probe files, so the rule file is
    the single scoring source. ``human`` is the plain-language definition that
    the blind review shows to the annotator.
    """

    rule_id: str
    text: str
    op: str
    human: str
    words: tuple[str, ...] = ()
    phrases: tuple[str, ...] = ()
    sentences: int | None = None
    questions: int | None = None
    questions_exact: bool = False
    chars: int | None = None
    scored: bool = True
    mode: str = MODE_SUPPORT


@dataclass(frozen=True)
class Expect:
    """One probe's pass condition: a v2 operator plus its static arguments.

    ``echo_source`` is the user's last message; R5 compares it with the reply
    by shared character substrings. ``questions_exact`` switches the question
    limit from "at most" to "exactly". ``must_contain_any`` is kept only for
    older callers and is never read by the judge.
    """

    op: str
    words: tuple[str, ...] = ()
    phrases: tuple[str, ...] = ()
    sentences: int | None = None
    questions: int | None = None
    questions_exact: bool = False
    chars: int | None = None
    echo_source: str = ""
    must_contain_any: tuple[str, ...] = ()

    @classmethod
    def from_payload(cls, payload: object, rule: Rule) -> "Expect":
        """Bind one probe's ``expect`` object to its rule program.

        The probe may only echo the operator name and, for R5, the source
        sentence it must share characters with. Limits and word lists always
        come from the rule file, so a probe cannot silently loosen a rule.
        """
        if not isinstance(payload, dict):
            raise PcsError(E_PCS_SCHEMA, "expect 必须是对象")
        unknown = sorted(set(payload) - set(EXPECT_FIELDS))
        if unknown:
            raise PcsError(E_PCS_SCHEMA, f"expect 含未知字段：{', '.join(unknown)}")
        op = payload.get("op")
        if op != rule.op:
            raise PcsError(
                E_PCS_SCHEMA, f"{rule.rule_id} 的算子必须是 {rule.op}，收到 {op}"
            )
        source = payload.get("echo_source", "")
        if not isinstance(source, str):
            raise PcsError(E_PCS_SCHEMA, "echo_source 必须是字符串")
        if rule.op == "shares_two_chars_with_source":
            if not source.strip():
                raise PcsError(
                    E_PCS_SCHEMA, f"{rule.rule_id} 必须填写 echo_source"
                )
        elif source.strip():
            raise PcsError(
                E_PCS_SCHEMA, f"{rule.rule_id} 不接受 echo_source"
            )
        return cls(
            op=rule.op,
            words=rule.words,
            phrases=rule.phrases,
            sentences=rule.sentences,
            questions=rule.questions,
            questions_exact=rule.questions_exact,
            chars=rule.chars,
            echo_source=source,
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
    mode: str = MODE_SUPPORT
    scored: bool = True


def validate_expect(payload: object, rule: Rule) -> None:
    """Raise ``E_PCS_SCHEMA`` when an ``expect`` payload is not usable."""
    Expect.from_payload(payload, rule)


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
    if len(set(items)) != len(items):
        raise PcsError(E_PCS_SCHEMA, f"{name} 有重复")
    return tuple(items)


def _rule_arg(payload: dict[str, object], name: str, minimum: int) -> int:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PcsError(E_PCS_SCHEMA, f"规则参数 {name} 必须是不小于 {minimum} 的整数")
    return value


def _parse_rule(data: object, index: int, mode: str) -> Rule:
    if not isinstance(data, dict):
        raise PcsError(E_PCS_SCHEMA, f"第 {index} 条规则不是对象")
    rule_id = _require_text(data, "id")
    text = _require_text(data, "text")
    human = _require_text(data, "human")
    op = _require_text(data, "op")
    allowed_ops = CONSULT_OPERATORS if mode == MODE_CONSULT else V2_OPERATORS
    if op not in allowed_ops:
        raise PcsError(E_PCS_SCHEMA, f"{rule_id} 的算子不在 {mode} 清单：{op}")
    scored = data.get("scored", True)
    if not isinstance(scored, bool):
        raise PcsError(E_PCS_SCHEMA, f"{rule_id} 的 scored 必须是布尔")
    args = data.get("args")
    if not isinstance(args, dict):
        raise PcsError(E_PCS_SCHEMA, f"{rule_id} 的 args 必须是对象")
    if op == "none_of":
        if set(args) != {"words"}:
            raise PcsError(E_PCS_SCHEMA, f"{rule_id} 的 args 只允许 words")
        words = _string_list(args, "words")
        return Rule(rule_id, text, op, human, words=words, scored=scored, mode=mode)
    if op == "answer_directly":
        if set(args) != {"phrases"}:
            raise PcsError(E_PCS_SCHEMA, f"{rule_id} 的 args 只允许 phrases")
        phrases = _string_list(args, "phrases")
        return Rule(
            rule_id, text, op, human,
            phrases=phrases, scored=scored, mode=mode,
        )
    if op == "no_evasion":
        if set(args) != {"phrases"}:
            raise PcsError(E_PCS_SCHEMA, f"{rule_id} 的 args 只允许 phrases")
        phrases = _string_list(args, "phrases")
        return Rule(
            rule_id, text, op, human,
            phrases=phrases, scored=scored, mode=mode,
        )
    if op == "max_sentences_and_questions":
        allowed = {"sentences", "questions", "questions_exact"}
        if set(args) - allowed or not {"sentences", "questions"} <= set(args):
            raise PcsError(
                E_PCS_SCHEMA,
                f"{rule_id} 的 args 只允许 sentences / questions / questions_exact",
            )
        exact = args.get("questions_exact", False)
        if not isinstance(exact, bool):
            raise PcsError(E_PCS_SCHEMA, f"{rule_id} 的 questions_exact 必须是布尔")
        return Rule(
            rule_id, text, op, human,
            sentences=_rule_arg(args, "sentences", 1),
            questions=_rule_arg(args, "questions", 0),
            questions_exact=exact,
            scored=scored,
            mode=mode,
        )
    if op == "max_chars":
        if set(args) != {"chars"}:
            raise PcsError(E_PCS_SCHEMA, f"{rule_id} 的 args 只允许 chars")
        return Rule(
            rule_id, text, op, human,
            chars=_rule_arg(args, "chars", 1),
            scored=scored,
            mode=mode,
        )
    if args:
        raise PcsError(E_PCS_SCHEMA, f"{rule_id} 不接受参数")
    return Rule(rule_id, text, op, human, scored=scored, mode=mode)


def _parse_rules(path: Path, mode: str) -> tuple[Rule, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PcsError(E_PCS_IO, f"无法读取规则文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise PcsError(E_PCS_IO, f"规则文件不是 JSON：{path}") from exc
    if not isinstance(payload, dict):
        raise PcsError(E_PCS_SCHEMA, "规则文件必须是对象")
    if payload.get("version") != 2:
        raise PcsError(E_PCS_SCHEMA, "规则文件 version 必须是 2")
    declared = payload.get("mode")
    if declared is not None and declared != mode:
        raise PcsError(E_PCS_SCHEMA, f"规则文件 mode 必须是 {mode}，收到 {declared}")
    expected = CONSULT_RULE_IDS if mode == MODE_CONSULT else RULE_IDS
    raw = payload.get("rules")
    if not isinstance(raw, list) or len(raw) != len(expected):
        raise PcsError(E_PCS_SCHEMA, f"规则必须是 {len(expected)} 条")
    rules = tuple(
        _parse_rule(item, index, mode) for index, item in enumerate(raw, start=1)
    )
    ids = tuple(rule.rule_id for rule in rules)
    if ids != expected:
        raise PcsError(E_PCS_SCHEMA, f"规则 id 必须依次是 {', '.join(expected)}")
    return rules


@lru_cache(maxsize=1)
def _default_rules() -> tuple[Rule, ...]:
    return _parse_rules(RULES_PATH, MODE_SUPPORT)


@lru_cache(maxsize=1)
def _default_consult_rules() -> tuple[Rule, ...]:
    return _parse_rules(CONSULT_RULES_PATH, MODE_CONSULT)


def load_rules_v2(path: Path | None = None) -> tuple[Rule, ...]:
    """Return the six support-mode rules; ``rules_v2.json`` is the only source."""
    if path is None:
        return _default_rules()
    return _parse_rules(Path(path), MODE_SUPPORT)


def load_consult_rules(path: Path | None = None) -> tuple[Rule, ...]:
    """Return the five consult-mode rules from ``rules_consult.json``."""
    if path is None:
        return _default_consult_rules()
    return _parse_rules(Path(path), MODE_CONSULT)


def _rule_index(mode: str) -> dict[str, Rule]:
    rules = load_consult_rules() if mode == MODE_CONSULT else load_rules_v2()
    return {rule.rule_id: rule for rule in rules}


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


def _resolve_rule(rule_id: str, line_no: int, mode: str) -> Rule:
    rule = _rule_index(mode).get(rule_id)
    if rule is None:
        expected = CONSULT_RULE_IDS if mode == MODE_CONSULT else RULE_IDS
        raise PcsError(
            E_PCS_SCHEMA,
            f"第 {line_no} 行 rule 必须是 {expected[0]}-{expected[-1]}，收到 {rule_id}",
        )
    return rule


def _probe_mode(data: dict[str, object], line_no: int) -> str:
    """Read the optional ``mode`` field; probes default to the support mode."""
    value = data.get("mode")
    if value is None:
        return MODE_SUPPORT
    if not isinstance(value, str) or value not in MODES:
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行 mode 非法：{value}")
    return value


def _parse_single_probe(data: dict[str, object], line_no: int) -> Probe:
    missing = [name for name in PROBE_FIELDS if name not in data]
    if missing:
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行缺字段：{', '.join(missing)}")
    extra = sorted(set(data) - set(PROBE_FIELDS) - set(PROBE_OPTIONAL_FIELDS))
    if extra:
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行有未知字段：{', '.join(extra)}")
    probe_id = _require_text(data, "probe_id")
    rule_id = _require_text(data, "rule")
    mode = _probe_mode(data, line_no)
    rule = _resolve_rule(rule_id, line_no, mode)
    prompt = _require_text(data, "prompt")
    violation = _require_text(data, "violation")
    return Probe(
        probe_id=probe_id,
        rule=rule_id,
        prompt=prompt,
        expect=Expect.from_payload(data["expect"], rule),
        accept=_accept_list(data["accept"], line_no),
        violation=violation,
        mode=mode,
        scored=rule.scored,
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
    rule_id = _require_text(data, "rule")
    rule = _resolve_rule(rule_id, line_no, MODE_SUPPORT)
    turns = _turn_list(data["turns"], line_no)
    violation = _require_text(data, "violation")
    return Probe(
        probe_id=probe_id,
        rule=rule_id,
        prompt=turns[-1],
        expect=Expect.from_payload(data["expect_final"], rule),
        accept=_accept_list(data["accept"], line_no),
        violation=violation,
        kind=kind,
        turns=turns,
        mode=MODE_SUPPORT,
        scored=rule.scored,
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


def load_more_probes(path: Path | None = None) -> tuple[Probe, ...]:
    """Load the 30 M8.3 expansion probes; one more sample per M6 rule."""
    return _load_file(MORE_DATA_PATH if path is None else Path(path))


def load_real_probes(path: Path | None = None) -> tuple[Probe, ...]:
    """Load the 20 probes shaped after real conversational input."""
    return _load_file(REAL_DATA_PATH if path is None else Path(path))


def load_consult_probes(path: Path | None = None) -> tuple[Probe, ...]:
    """Load the 20 consult-mode probes (Q1-Q4, five each)."""
    return _load_file(CONSULT_DATA_PATH if path is None else Path(path))


def load_hard_probes(path: Path | None = None) -> tuple[Probe, ...]:
    """Load the M7 hard probe set: multi-turn, contradiction and pressure."""
    return _load_file(HARD_DATA_PATH if path is None else Path(path))


def load_all_probes() -> tuple[Probe, ...]:
    """Return the 80 scored probes (base + more + real), ids checked.

    The 18 hard probes stay out on purpose: they drive ``C_final`` / ``R`` /
    ``D`` and are scored as their own set, never mixed into ``C``.
    """
    merged = load_probes() + load_more_probes() + load_real_probes()
    ids = [probe.probe_id for probe in merged]
    if len(set(ids)) != len(ids):
        raise PcsError(E_PCS_SCHEMA, "base / more / real 探针 id 冲突")
    return merged
