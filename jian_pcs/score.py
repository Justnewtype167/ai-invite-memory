"""PCS scoring: self-consistency C(m), agreement A(a,b) and PCS = A * min(C)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from jian_pcs.errors import E_PCS_IO, E_PCS_SCHEMA, PcsError
from jian_pcs.judge import FAIL, PASS, UNKNOWN, judge_reply
from jian_pcs.probes import Probe


@dataclass(frozen=True)
class Reply:
    """One model reply to one probe."""

    probe_id: str
    model: str
    text: str
    temp_milli: int | None = None
    seed: int | None = None


@dataclass(frozen=True)
class ModelScore:
    """Self-consistency of one model; unknown probes are not in the counts."""

    judged: int
    passed: int
    failed: int
    skipped: int
    c: float


@dataclass(frozen=True)
class RuleScore:
    """Per-rule detail so a low PCS can be located, not just reported."""

    rule: str
    probes: int
    c_a: float
    c_b: float
    a: float
    skipped: int


@dataclass(frozen=True)
class PcsReport:
    """All four numbers plus the skip count and per-rule breakdown."""

    probes: int
    skipped: int
    model_a: ModelScore
    model_b: ModelScore
    agreement: float
    pcs: float
    insufficient: bool
    per_rule: tuple[RuleScore, ...]


def load_replies(path: Path) -> dict[str, Reply]:
    """Load a JSONL reply file keyed by ``probe_id``; duplicates are refused."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise PcsError(E_PCS_IO, f"无法读取回复文件：{path}") from exc
    replies: dict[str, Reply] = {}
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PcsError(E_PCS_IO, f"第 {line_no} 行不是 JSON") from exc
        reply = _parse_reply(data, line_no)
        if reply.probe_id in replies:
            raise PcsError(E_PCS_SCHEMA, f"重复回复：{reply.probe_id}")
        replies[reply.probe_id] = reply
    return replies


def _parse_reply(data: object, line_no: int) -> Reply:
    if not isinstance(data, dict):
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行不是对象")
    for name in ("probe_id", "model", "text"):
        if name not in data:
            raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行缺 {name}")
    probe_id = data["probe_id"]
    model = data["model"]
    text = data["text"]
    if not isinstance(probe_id, str) or not probe_id:
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行 probe_id 非法")
    if not isinstance(model, str) or not model:
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行 model 非法")
    if not isinstance(text, str):
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行 text 非法")
    temp_milli = _optional_int(data, "temp_milli", 0, 2000, line_no)
    seed = _optional_int(data, "seed", 0, 2 ** 31 - 1, line_no)
    return Reply(probe_id, model, text, temp_milli, seed)


def _optional_int(
    data: dict[str, object], name: str, low: int, high: int, line_no: int
) -> int | None:
    value = data.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行 {name} 必须是整数")
    if not low <= value <= high:
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行 {name} 越界")
    return value


def _verdicts(probes: tuple[Probe, ...], replies: dict[str, Reply]) -> dict[str, str]:
    return {
        probe.probe_id: judge_reply(
            replies[probe.probe_id].text if probe.probe_id in replies else "",
            probe.expect,
        )
        for probe in probes
    }


def _model_score(verdicts: dict[str, str], probes: tuple[Probe, ...]) -> ModelScore:
    judged = passed = failed = skipped = 0
    for probe in probes:
        verdict = verdicts[probe.probe_id]
        if verdict == UNKNOWN:
            skipped += 1
        elif verdict == PASS:
            judged += 1
            passed += 1
        else:
            judged += 1
            failed += 1
    c = passed / judged if judged else 0.0
    return ModelScore(judged, passed, failed, skipped, c)


def score_model(probes: tuple[Probe, ...], replies: dict[str, Reply]) -> ModelScore:
    """Return C(m) for one reply set; unknown probes are excluded."""
    return _model_score(_verdicts(probes, replies), probes)


def compute_pcs(
    probes: tuple[Probe, ...],
    replies_a: dict[str, Reply],
    replies_b: dict[str, Reply],
) -> PcsReport:
    """Return C(a), C(b), A(a,b) and PCS, with the per-rule breakdown.

    ``PCS = A * min(C(a), C(b))``. If ``min(C) < 0.5`` the score is forced to
    zero and flagged ``insufficient_conformance``: two models agreeing while
    both violate the persona is "consistent, not the same person".
    """
    verdicts_a = _verdicts(probes, replies_a)
    verdicts_b = _verdicts(probes, replies_b)
    score_a = _model_score(verdicts_a, probes)
    score_b = _model_score(verdicts_b, probes)
    both = [
        probe for probe in probes
        if verdicts_a[probe.probe_id] != UNKNOWN
        and verdicts_b[probe.probe_id] != UNKNOWN
    ]
    same = sum(
        1 for probe in both
        if verdicts_a[probe.probe_id] == verdicts_b[probe.probe_id]
    )
    agreement = same / len(both) if both else 0.0
    pcs = agreement * min(score_a.c, score_b.c)
    insufficient = min(score_a.c, score_b.c) < 0.5
    if insufficient:
        pcs = 0.0
    rules: dict[str, list[Probe]] = {}
    for probe in probes:
        rules.setdefault(probe.rule, []).append(probe)
    per_rule = tuple(
        _rule_score(rule, group, verdicts_a, verdicts_b)
        for rule, group in rules.items()
    )
    return PcsReport(
        probes=len(probes),
        skipped=len(probes) - len(both),
        model_a=score_a,
        model_b=score_b,
        agreement=agreement,
        pcs=pcs,
        insufficient=insufficient,
        per_rule=per_rule,
    )


def _rule_score(
    rule: str,
    group: list[Probe],
    verdicts_a: dict[str, str],
    verdicts_b: dict[str, str],
) -> RuleScore:
    probes = tuple(group)
    score_a = _model_score(verdicts_a, probes)
    score_b = _model_score(verdicts_b, probes)
    both = [
        probe for probe in probes
        if verdicts_a[probe.probe_id] != UNKNOWN
        and verdicts_b[probe.probe_id] != UNKNOWN
    ]
    same = sum(
        1 for probe in both
        if verdicts_a[probe.probe_id] == verdicts_b[probe.probe_id]
    )
    agreement = same / len(both) if both else 0.0
    return RuleScore(
        rule, len(probes), score_a.c, score_b.c, agreement,
        len(probes) - len(both),
    )
