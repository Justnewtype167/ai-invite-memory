"""The unforgettable layer: a small set of memories that always reach the prompt.

Principle: normal memory competes for the context budget; a pinned memory takes
its seat first and the retrieval gets what is left. Pinning is evidence, not
configuration: a directive(kind=pin, target=<event id>) records the decision, so
the list is append-only, auditable and recomputable like everything else.

A pin never enters the kid: it says what the companion should remember now, not
who it is.
"""
from __future__ import annotations

from dataclasses import dataclass

from aiinvite.kernel.compiler import core_events
from aiinvite.kernel.kernel import EvidenceEvent

PIN_KINDS = ("pin", "unpin")
MAX_PINS = 12
MAX_CHARS = 600


@dataclass(frozen=True)
class Pin:
    """One unforgettable memory, pointing at the event it came from."""

    event_id: str
    text: str
    pinned_by: str


def _sequence(event_id: str) -> int:
    try:
        return int(event_id[3:])
    except (TypeError, ValueError):
        return 0


def derive_pins(
    events: list[EvidenceEvent],
    limit: int = MAX_PINS,
    max_chars: int = MAX_CHARS,
) -> tuple[Pin, ...]:
    """Return the pinned memories in pin order, newest pin last.

    Pins are resolved against core events only: a pin cannot resurrect a
    persona event, and a target that does not exist is ignored (it may have
    been written before the event, or the id may be a typo).
    """
    core = core_events(events)
    by_id = {event.event_id: event for event in core}
    order: list[str] = []
    pinned_by: dict[str, str] = {}
    for event in events:
        if event.type != "directive" or event.kind not in PIN_KINDS:
            continue
        target = (event.target or "").strip()
        if not target:
            continue
        if event.kind == "pin":
            if target not in pinned_by:
                order.append(target)
            pinned_by[target] = event.event_id
        else:
            if target in pinned_by:
                order.remove(target)
                del pinned_by[target]
    pins: list[Pin] = []
    total = 0
    for event_id in order:
        source = by_id.get(event_id)
        if source is None:
            continue
        text = source.text.strip()
        if not text:
            continue
        if total + len(text) > max_chars:
            break
        pins.append(Pin(event_id, text, pinned_by[event_id]))
        total += len(text)
    return tuple(pins[:limit])


def render_pins(pins: tuple[Pin, ...]) -> str:
    """Return the prompt block for the pins, or an empty string."""
    if not pins:
        return ""
    return "\n".join("- " + pin.text for pin in pins)
