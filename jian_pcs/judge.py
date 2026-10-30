"""Deterministic probe judge: pass / fail / unknown, zero model calls."""

from __future__ import annotations

from jian_pcs.probes import Expect, Probe

PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"

SENTENCE_MARKS = "。！？!?."
QUESTION_MARKS = "?？"


def judge_reply(text: str, expect: Expect) -> str:
    """Judge one reply against one ``expect``; blank replies are ``unknown``.

    All operators are deterministic string checks. An empty or whitespace-only
    reply cannot be judged, so it is excluded from every denominator rather
    than counted as a pass (that would inflate PCS).
    """
    if not text or not text.strip():
        return UNKNOWN
    body = text.strip()
    if not _contains_any(body, expect.must_contain_any):
        return FAIL
    if _contains_forbidden(body, expect.must_not_contain_any):
        return FAIL
    if expect.max_chars is not None and len(body) > expect.max_chars:
        return FAIL
    if expect.max_questions is not None and _questions(body) > expect.max_questions:
        return FAIL
    if expect.max_sentences is not None and _sentences(body) > expect.max_sentences:
        return FAIL
    if expect.must_ask_before is not None and not _asked_first(body, expect):
        return FAIL
    return PASS


def violation_rejected(probe: Probe) -> bool:
    """Return True when the probe's known-violating reply is judged ``fail``.

    This is the guard from the spec: a judge that always returns pass would
    make PCS a constant, so every probe must prove it can reject its own
    violation before its passes count.
    """
    return judge_reply(probe.violation, probe.expect) == FAIL


def _contains_any(body: str, needles: tuple[str, ...]) -> bool:
    return not needles or any(needle in body for needle in needles)


def _contains_forbidden(body: str, needles: tuple[str, ...]) -> bool:
    return any(needle in body for needle in needles)


def _questions(body: str) -> int:
    return sum(body.count(mark) for mark in QUESTION_MARKS)


def _sentences(body: str) -> int:
    return sum(body.count(mark) for mark in SENTENCE_MARKS)


def _asked_first(body: str, expect: Expect) -> bool:
    """True unless an action fired without its required question first."""
    ask = expect.must_ask_before
    if ask is None:
        return True
    action_at = body.find(ask.action)
    if action_at < 0:
        return True
    question_at = body.find(ask.question)
    return question_at >= 0 and question_at < action_at
