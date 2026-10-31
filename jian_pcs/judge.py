"""Deterministic probe judge: pass / fail / unknown, zero model calls.

Only the five v2 operators exist. There is no fuzzy or semantic matching:
``none_of`` is a closed word list, ``max_chars`` / ``max_sentences_and_questions``
are counts, ``first_is_question`` reads the first sentence-final mark, and
``shares_two_chars_with_source`` checks a two-character common substring with
the probe's own source sentence.
"""

from __future__ import annotations

from jian_pcs.errors import E_PCS_SCHEMA, PcsError
from jian_pcs.probes import Expect, Probe

PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"

FINAL_MARKS = "。！？"
QUESTION_MARKS = "？"
ALLOWED_OPERATORS = (
    "first_is_question",
    "none_of",
    "max_sentences_and_questions",
    "max_chars",
    "shares_two_chars_with_source",
)


def judge_reply(text: str, expect: Expect) -> str:
    """Judge one reply against one ``expect``; blank replies are ``unknown``.

    An empty or whitespace-only reply cannot be judged, so it is excluded from
    every denominator rather than counted as a pass (that would inflate PCS).
    R5 without a source sentence is also ``unknown``.
    """
    if not text or not text.strip():
        return UNKNOWN
    body = text.strip()
    if expect.op == "first_is_question":
        return PASS if _first_is_question(body) else FAIL
    if expect.op == "none_of":
        return FAIL if any(word in body for word in expect.words) else PASS
    if expect.op == "max_sentences_and_questions":
        if expect.sentences is None or expect.questions is None:
            raise PcsError(E_PCS_SCHEMA, "max_sentences_and_questions 缺参数")
        if _sentences(body) > expect.sentences:
            return FAIL
        if _questions(body) > expect.questions:
            return FAIL
        return PASS
    if expect.op == "max_chars":
        if expect.chars is None:
            raise PcsError(E_PCS_SCHEMA, "max_chars 缺参数")
        return PASS if _chars(body) <= expect.chars else FAIL
    if expect.op == "shares_two_chars_with_source":
        if not expect.echo_source.strip():
            return UNKNOWN
        return PASS if _shares_two_chars(expect.echo_source, body) else FAIL
    raise PcsError(E_PCS_SCHEMA, f"未知算子：{expect.op}")


def violation_rejected(probe: Probe) -> bool:
    """Return True when the probe's known-violating reply is judged ``fail``.

    This is the guard from the spec: a judge that always returns pass would
    make PCS a constant, so every probe must prove it can reject its own
    violation before its passes count.
    """
    return judge_reply(probe.violation, probe.expect) == FAIL


def accepts_pass(probe: Probe) -> bool:
    """Return True when every legal wording of the probe is judged ``pass``.

    The violation alone only proves the judge can reject; a judge tuned to
    a handful of fixed phrases also rejects correct paraphrases and shrinks C
    for free. Both directions must hold or the probe is not usable.
    """
    return all(
        judge_reply(text, probe.expect) == PASS for text in probe.accept
    )


def _first_is_question(body: str) -> bool:
    """True when the first sentence-final mark is a question mark."""
    for char in body:
        if char in FINAL_MARKS:
            return char == QUESTION_MARKS
    return False


def _shares_two_chars(source: str, body: str) -> bool:
    """True when normalized source and reply share a 2-character substring.

    Both sides drop every non-alphanumeric character first, so punctuation and
    whitespace never affect the comparison. Any common substring of length
    two or more necessarily contains a common two-character window, so checking
    adjacent pairs is exact.
    """
    left = _normalize(source)
    right = _normalize(body)
    if len(left) < 2 or len(right) < 2:
        return False
    pairs = {left[index:index + 2] for index in range(len(left) - 1)}
    return any(
        right[index:index + 2] in pairs
        for index in range(len(right) - 1)
    )


def _normalize(text: str) -> str:
    """Keep CJK characters, letters and digits; drop punctuation and spaces."""
    return "".join(char for char in text if char.isalnum())


def _questions(body: str) -> int:
    return sum(body.count(mark) for mark in QUESTION_MARKS)


def _sentences(body: str) -> int:
    """Count non-empty fragments after splitting on ``。！？``."""
    count = 0
    current = False
    for char in body:
        if char in FINAL_MARKS:
            if current:
                count += 1
                current = False
        elif not char.isspace():
            current = True
    return count + (1 if current else 0)


def _chars(body: str) -> int:
    """Character count after removing every whitespace character."""
    return len("".join(body.split()))
