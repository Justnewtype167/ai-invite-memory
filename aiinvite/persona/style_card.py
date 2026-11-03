"""Style card: distill once, write as evidence, guard against echo (M16).

The card is produced outside this process (a model sees ``style_input`` once)
and is then frozen as a ``proposal(self.style_card)`` event. Later reads use
the last such proposal, so re-distilling is a new event rather than an edit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from aiinvite.canonical import dumps
from aiinvite.capsule import append_payload_event
from aiinvite.event import Event
from aiinvite.kernel.compiler import core_events, read_evidence
from aiinvite.kernel.kernel import STYLE_CARD_TARGET, EvidenceEvent
from aiinvite.succession.model import REASONS

from aiinvite.persona.errors import (
    E_PERSONA_INPUT,
    E_PERSONA_REDACTION,
    E_PERSONA_STYLE_CARD,
    PersonaError,
)

CARD_LIMIT = 800
EXAMPLES_LIMIT = 15
COUNTER_LIMIT = 3
STYLE_INPUT_LIMIT = 500
CARD_KEYS = (
    "source", "distilled_at", "model", "prompt_sha", "rhythm", "address",
    "tics", "examples", "counter_examples", "forbidden",
)
SOURCE_KEYS = ("from_event", "to_event", "count")
ECHO_LIMIT = 12


@dataclass(frozen=True)
class StyleInput:
    """The once-only distillation window and the text it produced."""

    text: str
    from_event: str
    to_event: str
    count: int


@dataclass(frozen=True)
class StyleCard:
    """A validated, frozen style card."""

    source: dict[str, object]
    distilled_at: str
    model: str
    prompt_sha: str
    rhythm: str
    address: str
    tics: tuple[str, ...]
    examples: tuple[str, ...]
    counter_examples: tuple[str, ...]
    forbidden: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        """Return the JSON-ready card."""
        return {
            "source": dict(self.source),
            "distilled_at": self.distilled_at,
            "model": self.model,
            "prompt_sha": self.prompt_sha,
            "rhythm": self.rhythm,
            "address": self.address,
            "tics": list(self.tics),
            "examples": list(self.examples),
            "counter_examples": list(self.counter_examples),
            "forbidden": list(self.forbidden),
        }

    def text(self) -> str:
        """Return the canonical JSON text; this is also the size that is capped."""
        return dumps(self.to_payload()).decode("utf-8")


@dataclass(frozen=True)
class EchoResult:
    """Longest common substring between a reply and one example."""

    lcs: int
    ok: bool
    example: str


def parse_style_card(text: str) -> StyleCard:
    """Parse and validate one style card from its canonical JSON text."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PersonaError(E_PERSONA_STYLE_CARD, "风格卡不是合法 JSON") from exc
    return _card_from(payload)


def _card_from(payload: object) -> StyleCard:
    if not isinstance(payload, dict) or tuple(sorted(payload)) != tuple(
        sorted(CARD_KEYS)
    ):
        raise PersonaError(
            E_PERSONA_STYLE_CARD, f"风格卡字段必须恰好是 {CARD_KEYS}"
        )
    source = payload.get("source")
    if not isinstance(source, dict) or tuple(sorted(source)) != tuple(
        sorted(SOURCE_KEYS)
    ):
        raise PersonaError(E_PERSONA_STYLE_CARD, f"source 字段必须恰好是 {SOURCE_KEYS}")
    for key in ("from_event", "to_event"):
        value = source.get(key)
        if not isinstance(value, str) or not value:
            raise PersonaError(E_PERSONA_STYLE_CARD, f"source.{key} 非法")
    count = source.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise PersonaError(E_PERSONA_STYLE_CARD, "source.count 非法")
    for key in ("distilled_at", "model", "prompt_sha", "rhythm", "address"):
        value = payload.get(key)
        if not isinstance(value, str):
            raise PersonaError(E_PERSONA_STYLE_CARD, f"{key} 必须是字符串")
    card = StyleCard(
        source={"from_event": str(source["from_event"]),
                "to_event": str(source["to_event"]),
                "count": int(count)},
        distilled_at=str(payload["distilled_at"]),
        model=str(payload["model"]),
        prompt_sha=str(payload["prompt_sha"]),
        rhythm=str(payload["rhythm"]),
        address=str(payload["address"]),
        tics=_string_list(payload, "tics"),
        examples=_string_list(payload, "examples"),
        counter_examples=_string_list(payload, "counter_examples"),
        forbidden=_string_list(payload, "forbidden"),
    )
    if len(card.examples) > EXAMPLES_LIMIT:
        raise PersonaError(
            E_PERSONA_STYLE_CARD, f"examples 超过 {EXAMPLES_LIMIT} 条"
        )
    if len(card.counter_examples) > COUNTER_LIMIT:
        raise PersonaError(
            E_PERSONA_STYLE_CARD, f"counter_examples 超过 {COUNTER_LIMIT} 条"
        )
    if len(card.text()) > CARD_LIMIT:
        raise PersonaError(
            E_PERSONA_STYLE_CARD, f"风格卡超过 {CARD_LIMIT} 字符"
        )
    return card


def _string_list(payload: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PersonaError(E_PERSONA_STYLE_CARD, f"{key} 必须是字符串数组")
    return tuple(str(item) for item in value)


def style_input(
    events: list[EvidenceEvent],
    exclude: Mapping[str, str] | None = None,
    limit: int = STYLE_INPUT_LIMIT,
) -> StyleInput:
    """Return the last ``limit`` core texts, redacted by event id.

    ``exclude`` maps an event id to a reason from the M15 table. Excluded
    events never appear in the returned text, so a distiller cannot copy
    third-party speech even if it tries.
    """
    excluded = dict(exclude or {})
    for reason in excluded.values():
        if reason not in REASONS:
            raise PersonaError(E_PERSONA_INPUT, f"未知脱敏原因：{reason}")
    kept = [
        event for event in core_events(events) if event.event_id not in excluded
    ]
    window = kept[-limit:] if limit > 0 else []
    if not window:
        return StyleInput("", "", "", 0)
    return StyleInput(
        text="\n".join(event.text for event in window),
        from_event=window[0].event_id,
        to_event=window[-1].event_id,
        count=len(window),
    )


def assert_redacted(
    card: StyleCard, excluded_texts: Iterable[str]
) -> None:
    """Raise when any excluded source text leaked into a card field."""
    haystack = card.text()
    for text in excluded_texts:
        needle = text.strip()
        if len(needle) < 2:
            continue
        if needle in haystack:
            raise PersonaError(
                E_PERSONA_REDACTION, f"风格卡含被排除的原文：{needle}"
            )


def record_style_card(
    store: Path,
    card: StyleCard,
    *,
    t: str | None = None,
    quant: str | None = None,
    weights_sha: str | None = None,
    temp_milli: int | None = None,
    seed: int | None = None,
) -> Event:
    """Write a style card as one v2 ``proposal(self.style_card)`` event."""
    payload = dumps(card.to_payload())
    source = card.source
    summary = f"style card {source['count']} events"
    return append_payload_event(
        store, "text", summary, payload, t=t,
        type="proposal", target=STYLE_CARD_TARGET,
        model=card.model, prompt_sha=card.prompt_sha,
        quant=quant, weights_sha=weights_sha,
        temp_milli=temp_milli, seed=seed,
    )


def load_style_card(
    store: Path, exclude: Mapping[str, str] | None = None
) -> StyleCard | None:
    """Return the last recorded style card, or None when there is none."""
    events = read_evidence(store)
    found: EvidenceEvent | None = None
    for event in events:
        if event.type == "proposal" and event.target == STYLE_CARD_TARGET:
            found = event
    if found is None:
        return None
    card = parse_style_card(found.text)
    if exclude:
        excluded_ids = set(exclude)
        texts = [
            event.text for event in core_events(events)
            if event.event_id in excluded_ids
        ]
        assert_redacted(card, texts)
    return card


def longest_common_substring(left: str, right: str) -> int:
    """Return the length of the longest common substring."""
    if not left or not right:
        return 0
    previous = [0] * (len(right) + 1)
    best = 0
    for char in left:
        current = [0] * (len(right) + 1)
        for index, other in enumerate(right, start=1):
            if char == other:
                current[index] = previous[index - 1] + 1
                if current[index] > best:
                    best = current[index]
        previous = current
    return best


def echo_guard(
    reply: str, examples: Iterable[str], limit: int = ECHO_LIMIT
) -> EchoResult:
    """Return the worst overlap between ``reply`` and any example.

    A longest common substring longer than ``limit`` means the reply copied
    a template; exactly ``limit`` characters is still allowed.
    """
    worst = 0
    worst_example = ""
    for example in examples:
        score = longest_common_substring(reply, example)
        if score > worst:
            worst = score
            worst_example = example
    return EchoResult(worst, worst <= limit, worst_example)
