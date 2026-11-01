"""gate: the actuation gate that stops a trace from being emitted (M13).

``check`` is a pure function of a trace and a kernel. It never sees a store,
a path, a clock or a random source, so the same kernel and the same trace
always produce the same verdict.

Every rule lives in ``data/gate_rules.json``; the code only knows how to
interpret the fields. A rule is enabled only when one of its
``canon_keywords`` appears in the kernel's canon, which keeps "the kernel
has no such constraint" distinct from "the constraint was violated".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from jian_projection.errors import (
    E_PR_GATE_RULES,
    E_PR_GATE_SCOPE,
    ProjectionError,
)
from jian_projection.trace import Trace

DATA_FILE = Path(__file__).resolve().parent / "data" / "gate_rules.json"
SCOPES = ("text", "action", "both")
RULE_NAME_MAX_CHARS = 40


@dataclass(frozen=True)
class GateRule:
    """One data-driven gate rule."""

    name: str
    canon_keywords: tuple[str, ...]
    forbid_text: tuple[str, ...]
    forbid_action: tuple[str, ...]
    max_text_chars: int | None
    scope: str


@dataclass(frozen=True)
class GateRules:
    """The loaded rules, in file order; the first enabled match wins."""

    rules: tuple[GateRule, ...]


@dataclass(frozen=True)
class Verdict:
    """The gate's answer: allowed, or the first violated rule and segment."""

    allowed: bool
    rule: str | None
    segment_index: int | None
    detail: str


def _string_list(rule: str, name: str, value: object) -> tuple[str, ...]:
    """Validate an optional list of non-empty strings."""
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ProjectionError(
            E_PR_GATE_RULES, f"gate rule {rule}: {name} must be non-empty strings"
        )
    return tuple(value)


def _parse_rule(name: str, body: object) -> GateRule:
    """Validate one rule object; unknown fields are rejected."""
    if not isinstance(body, dict):
        raise ProjectionError(E_PR_GATE_RULES, f"gate rule {name} must be an object")
    if not 1 <= len(name) <= RULE_NAME_MAX_CHARS:
        raise ProjectionError(
            E_PR_GATE_RULES, f"gate rule name must be 1-{RULE_NAME_MAX_CHARS} chars"
        )
    unknown = set(body) - {
        "canon_keywords", "forbid_text", "forbid_action", "max_text_chars", "scope",
    }
    if unknown:
        raise ProjectionError(
            E_PR_GATE_RULES, f"gate rule {name}: unknown field {sorted(unknown)[0]}"
        )
    if "scope" not in body:
        raise ProjectionError(E_PR_GATE_RULES, f"gate rule {name}: missing scope")
    scope = body["scope"]
    if not isinstance(scope, str) or scope not in SCOPES:
        raise ProjectionError(
            E_PR_GATE_SCOPE, f"gate rule {name}: unknown scope {scope}"
        )
    keywords = body.get("canon_keywords")
    if not isinstance(keywords, list) or not keywords or not all(
        isinstance(item, str) and item for item in keywords
    ):
        raise ProjectionError(
            E_PR_GATE_RULES, f"gate rule {name}: canon_keywords must be non-empty strings"
        )
    forbid_text = _string_list(name, "forbid_text", body.get("forbid_text"))
    forbid_action = _string_list(name, "forbid_action", body.get("forbid_action"))
    max_text_chars = body.get("max_text_chars")
    if max_text_chars is not None:
        if isinstance(max_text_chars, bool) or not isinstance(max_text_chars, int):
            raise ProjectionError(
                E_PR_GATE_RULES, f"gate rule {name}: max_text_chars must be an integer"
            )
        if max_text_chars < 1:
            raise ProjectionError(
                E_PR_GATE_RULES, f"gate rule {name}: max_text_chars must be >= 1"
            )
    if not forbid_text and not forbid_action and max_text_chars is None:
        raise ProjectionError(
            E_PR_GATE_RULES, f"gate rule {name}: no forbidden condition"
        )
    return GateRule(
        name,
        tuple(keywords),
        forbid_text,
        forbid_action,
        max_text_chars,
        scope,
    )


@lru_cache(maxsize=None)
def load_gate_rules(path: Path | None = None) -> GateRules:
    """Load and validate the gate rules, preserving file order."""
    source = DATA_FILE if path is None else Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectionError(
            E_PR_GATE_RULES, f"cannot read gate rules: {error}"
        ) from error
    if not isinstance(raw, dict) or not raw:
        raise ProjectionError(E_PR_GATE_RULES, "gate rules must be a non-empty object")
    rules = tuple(_parse_rule(name, body) for name, body in raw.items())
    return GateRules(rules)


def _canon_texts(kernel: object) -> tuple[str, ...]:
    """Return the canon texts of a kernel object, tolerating duck typing."""
    canon = getattr(kernel, "canon", ())
    if not canon:
        return ()
    return tuple(str(getattr(entry, "text", "")) for entry in canon)


def _enabled(rule: GateRule, canon: tuple[str, ...]) -> bool:
    """A rule is active only when its keywords appear in the kernel's canon."""
    return any(keyword in text for keyword in rule.canon_keywords for text in canon)


def check(trace: Trace, kernel: object) -> Verdict:
    """Return the first refusal for this trace, or an allow verdict.

    Rules are evaluated in file order; a rule whose ``canon_keywords`` do not
    appear in the kernel's canon is skipped, so a kernel without that
    constraint lets the same trace through. Within a rule, segments are
    scanned in order and scanning stops at the first violation.
    """
    canon = _canon_texts(kernel)
    rules = load_gate_rules().rules
    for rule in rules:
        if not _enabled(rule, canon):
            continue
        violation = _first_violation(rule, trace)
        if violation is not None:
            index, detail = violation
            return Verdict(False, rule.name, index, detail)
    return Verdict(True, None, None, "")


def _first_violation(rule: GateRule, trace: Trace) -> tuple[int, str] | None:
    """Return the first violating segment index and a reason, or None."""
    check_text = rule.scope in ("text", "both")
    check_action = rule.scope in ("action", "both")
    text_total = 0
    for index, segment in enumerate(trace.segments):
        if segment.kind == "text" and check_text:
            for word in rule.forbid_text:
                if word in segment.value:
                    return index, f"text contains forbidden word {word}"
            text_total += len(segment.value)
            if rule.max_text_chars is not None and text_total > rule.max_text_chars:
                return index, (
                    f"text length {text_total} exceeds {rule.max_text_chars}"
                )
        elif segment.kind == "action" and check_action:
            if segment.value in rule.forbid_action:
                return index, f"action {segment.value} is forbidden"
    return None
