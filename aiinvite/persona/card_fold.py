"""Incremental user-card fold (P3): O(delta) instead of O(n) per turn.

``derive_user_card`` is the reference: every call rescans the whole evidence.
The card derivations are order-dependent folds (last call wins, first taboo
wins, first preference wins, last-touch marks a promise done), so the result
can be carried in a ``CardState`` and extended with only the events appended
since the previous turn. ``fold_user_card`` falls back to a full fold
whenever a delta cannot be proved safe: the card rules changed, the evidence
shrank, or ids stopped increasing.

Equivalence with the reference is not assumed; tests/test_card_fold.py
compares the folded card with ``derive_user_card`` at every step on generated
personas, on taboo/call interactions, on promises that a later turn closes,
and after a rules change.

The card is derived data: none of this enters the kernel ``kid``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace

from aiinvite.cn.kinship import lexicon_terms
from aiinvite.kernel.compiler import is_persona_event
from aiinvite.recall.index import is_promise

from aiinvite.persona.errors import E_PERSONA_INPUT, PersonaError
from aiinvite.persona.user_card import (
    DONE_MARKERS,
    NAME_LIMIT,
    ONGOING_LIMIT,
    TEXT_LIMIT,
    UserCard,
    _scan_address,
    _scan_prefs,
    load_rules,
)


# How many covered events are fingerprinted. The evidence is append-only and
# hash-chained, so the prefix cannot change under an append; the prints catch
# the case that is still possible here -- a different store reusing the same
# ids under a live session.
TAIL = 8


@dataclass(frozen=True)
class CardState:
    """Everything the card has accumulated, plus the position it covers."""

    digest: str = ""
    count: int = 0
    last_id: str = ""
    tail: str = ""
    call: str = ""
    call_evidence: str = ""
    never: tuple[dict[str, str], ...] = ()
    taboo_names: frozenset[str] = frozenset()
    self_name: str = ""
    self_evidence: str = ""
    people: tuple[dict[str, str], ...] = ()
    people_seen: frozenset[tuple[str, str]] = frozenset()
    taboos: tuple[dict[str, str], ...] = ()
    promises: tuple[dict[str, str], ...] = ()
    ongoing: tuple[dict[str, str], ...] = ()
    likes: tuple[dict[str, str], ...] = ()
    like_seen: frozenset[str] = frozenset()
    dislikes: tuple[dict[str, str], ...] = ()
    dislike_seen: frozenset[str] = frozenset()


_PEOPLE_PATTERN: re.Pattern[str] | None = None


def _people_pattern() -> re.Pattern[str]:
    """Compile the kinship pattern once; the lexicon is code, not evidence."""
    global _PEOPLE_PATTERN
    if _PEOPLE_PATTERN is None:
        terms = sorted(lexicon_terms(), key=lambda term: (-len(term), term))
        _PEOPLE_PATTERN = re.compile(
            "(" + "|".join(re.escape(term) for term in terms)
            + r")叫([^，。！？,.!?]{1,%d})" % NAME_LIMIT
        )
    return _PEOPLE_PATTERN


def _rules_digest(table: dict[str, object]) -> str:
    """Return a stable digest so a rules edit rebuilds instead of mixing rules."""
    payload = json.dumps(table, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _texts(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def _address_rules(
    table: dict[str, object],
) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[tuple[str, str], ...], str, str]:
    """Return (pattern, negations, suffixes, aliases, rule_key, self_pattern)."""
    address = table.get("address")
    assert isinstance(address, dict)
    pattern = str(address.get("call", ""))
    negations = _texts(address.get("negations", []))
    suffixes = _texts(address.get("suffixes", []))
    aliases: tuple[tuple[str, str], ...] = ()
    raw = address.get("aliases", [])
    if isinstance(raw, list):
        aliases = tuple(
            (str(item[0]), str(item[1]))
            for item in raw
            if isinstance(item, list) and len(item) == 2
            and str(item[0]) and str(item[1])
        )
    rule_key = "|".join((
        pattern,
        ",".join(negations),
        ",".join(suffixes),
        ";".join(source + ">" + target for source, target in aliases),
    ))
    return pattern, negations, suffixes, aliases, rule_key, str(address.get("self", ""))


def _prefs_rules(
    table: dict[str, object],
) -> dict[str, tuple[list, str]]:
    """Return {like|dislike: (patterns, rule_key)} with the reference's checks."""
    prefs = table.get("prefs")
    assert isinstance(prefs, dict)
    output: dict[str, tuple[list, str]] = {}
    for key in ("like", "dislike"):
        patterns = prefs.get(key)
        if not isinstance(patterns, list):
            raise PersonaError(E_PERSONA_INPUT, f"用户卡规则 prefs.{key} 非法")
        output[key] = (
            patterns,
            key + "|" + "|".join(str(pattern) for pattern in patterns),
        )
    return output


def _tail_fingerprint(events: list) -> str:
    """Fingerprint the covered tail; O(TAIL), never O(n)."""
    payload = "\n".join(
        "|".join(
            (event.event_id, event.type, event.kind or "", event.role or "", event.text)
        )
        for event in events
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _extension(events: list, state: CardState) -> list | None:
    """Return the events appended since state, or None when that is not proved.

    The check is O(TAIL) plus O(delta): the covered prefix must still end with
    the same id and the same last few events, and the new ids must strictly
    increase. Anything else -- a rewritten store, a restored capsule, a
    different store with reused ids -- rebuilds from scratch.
    """
    if state.count == 0:
        return events if not state.last_id else None
    if len(events) < state.count:
        return None
    if events[state.count - 1].event_id != state.last_id:
        return None
    start = state.count - min(state.count, TAIL)
    if _tail_fingerprint(events[start:state.count]) != state.tail:
        return None
    delta = events[state.count:]
    previous = state.last_id
    for event in delta:
        if not previous < event.event_id:
            return None
        previous = event.event_id
    return delta


def fold_user_card(
    events: list,
    state: CardState | None = None,
    rules: dict[str, object] | None = None,
    cache: dict | None = None,
) -> tuple[UserCard, CardState]:
    """Return the user card and the state that covers these events.

    Pass the returned state to the next call; the next call then reads only
    the events appended in between. The result is identical to
    ``derive_user_card(events, rules, cache)``.
    """
    table = rules if rules is not None else load_rules()
    digest = _rules_digest(table)
    delta = None
    if state is not None and state.digest == digest:
        delta = _extension(events, state)
    if delta is None:
        state = CardState(digest=digest)
        delta = list(events)
    if not delta:
        current = state if state.digest == digest else replace(state, digest=digest)
        return _card(current), current
    current = _fold(state, delta, table, cache)
    start = current.count - min(current.count, TAIL)
    current = replace(
        current, tail=_tail_fingerprint(events[start:current.count])
    )
    return _card(current), current


def _fold(
    state: CardState,
    delta: list,
    table: dict[str, object],
    cache: dict | None,
) -> CardState:
    """Fold the new events into the carried state, one pass over the delta."""
    pattern, negations, suffixes, aliases, rule_key, self_pattern = _address_rules(table)
    prefs_rules = _prefs_rules(table)
    people_pattern = _people_pattern()

    call = state.call
    call_evidence = state.call_evidence
    never = list(state.never)
    taboo_names = set(state.taboo_names)
    self_name = state.self_name
    self_evidence = state.self_evidence
    people = list(state.people)
    people_seen = set(state.people_seen)
    taboos = list(state.taboos)
    promises = list(state.promises)
    ongoing = list(state.ongoing)
    likes = list(state.likes)
    like_seen = set(state.like_seen)
    dislikes = list(state.dislikes)
    dislike_seen = set(state.dislike_seen)

    for event in delta:
        # The reference filters first; filtering per event gives the same order.
        if is_persona_event(event) or event.role == "assistant":
            continue
        text = event.text
        event_id = event.event_id
        if pattern:
            for name, negative in _scan_address(
                event, pattern, negations, suffixes, aliases, cache, rule_key
            ):
                if negative:
                    if name not in taboo_names:
                        taboo_names.add(name)
                        never.append({"text": name, "evidence": event_id})
                elif name not in taboo_names:
                    # A later match equal to a taboo must not wipe an earlier
                    # good name; the final check still drops a taboo call.
                    call = name
                    call_evidence = event_id
        if self_pattern:
            for match in re.finditer(self_pattern, text):
                candidate = match.group(1).strip()
                if candidate:
                    self_name = candidate
                    self_evidence = event_id
        for match in people_pattern.finditer(text):
            relation = match.group(1)
            name = match.group(2).strip()
            key = (relation, name)
            if key in people_seen:
                continue
            people_seen.add(key)
            people.append(
                {"relation": relation, "name": name, "evidence": event_id}
            )
        if event.type == "directive" and event.kind == "lock":
            taboos.append({"text": text, "evidence": event_id})
        if any(marker in text for marker in DONE_MARKERS):
            # A later event with a completion marker closes every earlier
            # promise, exactly like _promise_done over the full core.
            promises = [
                item for item in promises if not item["evidence"] < event_id
            ]
        if event.type == "turn" and is_promise(text):
            promises.append(
                {"text": text, "since": event.stamp[:10], "evidence": event_id}
            )
        if event.type == "milestone":
            ongoing.append({"text": text, "evidence": event_id})
            if len(ongoing) > ONGOING_LIMIT:
                ongoing = ongoing[-ONGOING_LIMIT:]
        for key in ("like", "dislike"):
            patterns, pref_key = prefs_rules[key]
            values = _scan_prefs(event, patterns, cache, pref_key)
            if key == "like":
                bucket, seen = likes, like_seen
            else:
                bucket, seen = dislikes, dislike_seen
            for value in values:
                if not value or value in seen:
                    continue
                seen.add(value)
                bucket.append({"text": value[:TEXT_LIMIT], "evidence": event_id})

    return CardState(
        digest=state.digest,
        count=state.count + len(delta),
        last_id=delta[-1].event_id,
        call=call,
        call_evidence=call_evidence,
        never=tuple(never),
        taboo_names=frozenset(taboo_names),
        self_name=self_name,
        self_evidence=self_evidence,
        people=tuple(people),
        people_seen=frozenset(people_seen),
        taboos=tuple(taboos),
        promises=tuple(promises),
        ongoing=tuple(ongoing),
        likes=tuple(likes),
        like_seen=frozenset(like_seen),
        dislikes=tuple(dislikes),
        dislike_seen=frozenset(dislike_seen),
    )


def _card(state: CardState) -> UserCard:
    """Render the state into the same UserCard the reference builds."""
    call = state.call
    call_evidence = state.call_evidence
    if call and call in state.taboo_names:
        call = ""
        call_evidence = ""
    address: dict[str, object] = {
        "call": call,
        "self": state.self_name,
        "never": [dict(item) for item in state.never],
    }
    if call:
        address["call_evidence"] = call_evidence
    if state.self_name:
        address["self_evidence"] = state.self_evidence
    prefs = {
        "like": tuple(dict(item) for item in state.likes),
        "dislike": tuple(dict(item) for item in state.dislikes),
    }
    return UserCard(
        address,
        tuple(dict(item) for item in state.people),
        tuple(dict(item) for item in state.taboos),
        tuple(dict(item) for item in state.promises),
        tuple(dict(item) for item in state.ongoing),
        prefs,
    )
