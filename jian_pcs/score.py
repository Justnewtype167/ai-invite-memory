"""PCS scoring: self-consistency C(m), agreement A(a,b) and PCS = A * min(C)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from jian_pcs.errors import E_PCS_IO, E_PCS_MODE_MIX, E_PCS_SCHEMA, PcsError
from jian_pcs.judge import FAIL, PASS, UNKNOWN, judge_reply
from jian_pcs.probes import Probe


@dataclass(frozen=True)
class Reply:
    """One model reply to one probe; multi-turn replies keep every turn."""

    probe_id: str
    model: str
    text: str
    temp_milli: int | None = None
    seed: int | None = None
    turns_replied: tuple[str, ...] = ()

    def final_text(self) -> str:
        """Return the last recorded turn, falling back to ``text``."""
        return self.turns_replied[-1] if self.turns_replied else self.text


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
class CollapseScore:
    """Collapse statistics split into a rate ``R`` and a normalized depth ``D``.

    ``R`` is the share of *replied* multi-turn probes that violated the rule at
    least once, so a run with missing replies cannot look steady. ``D`` is the
    mean of ``first_failing_turn / total_turns`` over violating probes only:
    a probe that never violates contributes nothing (it is not "steady but
    long"), a last-turn collapse scores 1.0 and is therefore distinguishable
    from no collapse, and if nothing violates ``D`` is ``None`` (reported as
    n/a) with ``R = 0``. Missing replies are excluded entirely and counted in
    ``skipped``.
    """

    probes: int
    replied: int
    violating: int
    skipped: int
    r: float
    d: float | None


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
    final_a: ModelScore | None = None
    final_b: ModelScore | None = None
    collapse_a: CollapseScore | None = None
    collapse_b: CollapseScore | None = None


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
    turns = _optional_turns(data, line_no)
    return Reply(probe_id, model, text, temp_milli, seed, turns)


def _optional_turns(data: dict[str, object], line_no: int) -> tuple[str, ...]:
    value = data.get("turns_replied")
    if value is None:
        return ()
    if not isinstance(value, list) or not value:
        raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行 turns_replied 必须是非空数组")
    items = []
    for item in value:
        if not isinstance(item, str):
            raise PcsError(E_PCS_SCHEMA, f"第 {line_no} 行 turns_replied 含非字符串")
        items.append(item)
    return tuple(items)


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
            replies[probe.probe_id].final_text() if probe.probe_id in replies else "",
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


def score_collapse(
    probes: tuple[Probe, ...], replies: dict[str, Reply]
) -> CollapseScore:
    """Return the violation rate ``R`` and normalized depth ``D``.

    Only probes that carry a turn list are considered. A probe counts toward
    ``R`` only when it has a non-blank reply; blank or missing replies are
    excluded from both ``R`` and ``D`` and reported in ``skipped``. ``D`` is
    averaged over violating probes only, each contributing
    ``first_failing_turn / total_turns``, so probe length no longer dominates
    the number. With no violations ``D`` is ``None``.
    """
    multi = tuple(probe for probe in probes if probe.kind != "single_turn")
    if not multi:
        return CollapseScore(0, 0, 0, 0, 0.0, None)
    replied = 0
    skipped = 0
    ratios: list[float] = []
    for probe in multi:
        reply = replies.get(probe.probe_id)
        texts = (
            reply.turns_replied if reply is not None and reply.turns_replied
            else (reply.text,) if reply is not None else ()
        )
        if not any(text.strip() for text in texts):
            skipped += 1
            continue
        replied += 1
        first_fail = 0
        for index, text in enumerate(texts[: len(probe.turns)], start=1):
            if judge_reply(text, probe.expect) == FAIL:
                first_fail = index
                break
        if first_fail:
            ratios.append(first_fail / len(probe.turns))
    violating = len(ratios)
    rate = violating / replied if replied else 0.0
    depth = sum(ratios) / violating if violating else None
    return CollapseScore(len(multi), replied, violating, skipped, rate, depth)


def compute_pcs(
    probes: tuple[Probe, ...],
    replies_a: dict[str, Reply],
    replies_b: dict[str, Reply],
) -> PcsReport:
    """Return C(a), C(b), A(a,b) and PCS, with the per-rule breakdown.

    ``PCS = A * min(C(a), C(b))``. If ``min(C) < 0.5`` the score is forced to
    zero and flagged ``insufficient_conformance``: two models agreeing while
    both violate the persona is "consistent, not the same person".

    Every probe must share one mode. Mixing support and consult probes raises
    ``E_PCS_MODE_MIX`` instead of averaging two rule sets into one number.
    Rules marked ``scored=False`` (the consult ``advice_allowed``) only
    declare that a restriction is lifted; they are never counted.
    """
    modes = {probe.mode for probe in probes}
    if len(modes) > 1:
        raise PcsError(
            E_PCS_MODE_MIX,
            f"跨模式混合计算：{', '.join(sorted(modes))}",
        )
    probes = tuple(probe for probe in probes if probe.scored)
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
    multi = tuple(probe for probe in probes if probe.kind != "single_turn")
    final_a = _model_score(verdicts_a, multi) if multi else None
    final_b = _model_score(verdicts_b, multi) if multi else None
    collapse_a = score_collapse(multi, replies_a) if multi else None
    collapse_b = score_collapse(multi, replies_b) if multi else None
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
        final_a=final_a,
        final_b=final_b,
        collapse_a=collapse_a,
        collapse_b=collapse_b,
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
