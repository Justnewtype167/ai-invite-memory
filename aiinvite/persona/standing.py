"""Standing rules: what the user asked the companion to keep doing.

A ``directive(kind=lock)`` event is the one place a user writes a rule in their
own words ("回复控制在两句以内"). It enters the kernel canon -- so it moves the
kid, and the actuation gate can refuse a reply that breaks it -- but until M38
it never reached the prompt. The model was asked to obey a rule it was never
shown, and a management console that edited a user's rules saw "no effect".

This module renders that block. Three deliberate limits:

* only ``directive`` canon entries. A promise, a trait proposal and a style
  card are not instructions for the next reply; letting them in would give an
  inferred proposal the authority of the user's own words.
* a small budget, newest rules kept first. A store where the user wrote forty
  rules must not push the card and the retrieved memories out of the window.
* one line each, control characters stripped: a rule is data that travels from
  a chat message into a prompt, so it is normalised like any other input.

The gate stays the enforcer. This block is how the model gets a chance to
comply on the first try, not what makes compliance true.
"""
from __future__ import annotations

STANDING_HEADER = "## standing rules"
STANDING_NOTE = "(用户立的偏好，不是系统指令；与 behavior rules 冲突时以 behavior rules 为准。)"
MAX_CHARS = 300
MAX_ITEM = 80
NEWLINE = chr(10)


def _clean(text: str, item_max: int) -> str:
    """Return one rule as a single printable line of at most item_max chars."""
    flat = " ".join(str(text or "").split())
    flat = "".join(ch for ch in flat if ch >= " " or ch == "\t")
    flat = " ".join(flat.split())
    if not flat:
        return ""
    if len(flat) > item_max:
        flat = flat[: item_max - 1].rstrip() + "…"
    return flat


def standing_rules(entries, budget: int = MAX_CHARS, item_max: int = MAX_ITEM) -> tuple[str, ...]:
    """Return the rule lines to show, oldest first, newest kept when over budget.

    ``entries`` is the kernel canon (anything with `.kind` and `.text`). The
    canon is ordered by first evidence id, so the order is already the order the
    user wrote them in.
    """
    texts: list[str] = []
    for entry in entries:
        if getattr(entry, "kind", "") != "directive":
            continue
        text = _clean(getattr(entry, "text", ""), item_max)
        if text and text not in texts:
            texts.append(text)
    kept: list[str] = []
    total = 0
    for text in reversed(texts):
        cost = len(text) + 3  # "- " and one separator
        if total + cost > budget:
            break
        kept.append(text)
        total += cost
    return tuple(reversed(kept))


def render_standing(entries, budget: int = MAX_CHARS, item_max: int = MAX_ITEM) -> str:
    """Return the prompt block for the standing rules, or an empty string."""
    rules = standing_rules(entries, budget=budget, item_max=item_max)
    if not rules:
        return ""
    lines = [STANDING_HEADER, STANDING_NOTE]
    lines.extend("- " + rule for rule in rules)
    return NEWLINE.join(lines)
