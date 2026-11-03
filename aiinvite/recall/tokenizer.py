"""Token estimation and Chinese bigram tokenization (M3).

The estimator is deliberately conservative: Han characters cost 1.0 token
each, so a 4096 budget stays inside the safe zone of real tokenizers.
"""

from __future__ import annotations

import math

MESSAGE_OVERHEAD = 8.0
HAN_FIRST = 0x4E00
HAN_LAST = 0x9FFF


def _is_han(char: str) -> bool:
    return HAN_FIRST <= ord(char) <= HAN_LAST


def estimate_tokens(text: str) -> int:
    """Estimate the token cost of one message.

    Han characters cost 1.0 each, ASCII words cost 0.25 per character with a
    minimum of 1.0 per word, digits cost 0.5 each, punctuation and symbols
    cost 1.0 each, whitespace is free, and every message adds 8 tokens.
    The result is rounded up.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a str")
    cost = MESSAGE_OVERHEAD
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if _is_han(char):
            cost += 1.0
            index += 1
        elif char.isascii() and char.isalpha():
            end = index
            while end < length and text[end].isascii() and text[end].isalpha():
                end += 1
            cost += max(1.0, 0.25 * (end - index))
            index = end
        elif char.isascii() and char.isdigit():
            cost += 0.5
            index += 1
        elif char.isspace():
            index += 1
        else:
            cost += 1.0
            index += 1
    return int(math.ceil(cost))


def bigrams(text: str) -> str:
    """Return overlapping Han bigrams joined by single spaces.

    Only characters in U+4E00-U+9FFF are kept; every other character splits
    the text into separate Han runs. A run of one character yields that
    character itself, and an empty input yields an empty string.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a str")
    parts: list[str] = []
    run: list[str] = []
    for char in text:
        if _is_han(char):
            run.append(char)
            continue
        _flush_run(run, parts)
        run = []
    _flush_run(run, parts)
    return " ".join(parts)


def _flush_run(run: list[str], parts: list[str]) -> None:
    if len(run) == 1:
        parts.append(run[0])
    elif len(run) > 1:
        for index in range(len(run) - 1):
            parts.append(run[index] + run[index + 1])
