"""User card: mechanically derived user facts, pinned in context (M16).

Every non-empty entry points at the kernel event it came from. Fields with
no evidence stay empty; nothing is guessed and nothing is defaulted.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from jian_kernel.compiler import core_events
from jian_kernel.kernel import EvidenceEvent
from jian_cn.kinship import lexicon_terms
from jian_recall.assemble import Context, ContextItem
from jian_recall.index import is_promise
from jian_recall.tokenizer import estimate_tokens

from jian_persona.errors import (
    E_PERSONA_BUDGET,
    E_PERSONA_INPUT,
    E_PERSONA_IO,
    PersonaError,
)

CARD_BUDGET = 400
ONGOING_LIMIT = 3
NAME_LIMIT = 4
TEXT_LIMIT = 20
DONE_MARKERS = ("已完成", "已办", "做到了")
DEFAULT_RULES_PATH = Path(__file__).resolve().parent / "data" / "user_card_rules.json"
PINNED_ID = "user_card"
PINNED_SLOT = "pinned"
CLAUSE_SPLIT = re.compile(r"[，。！？,.!?]")


@dataclass(frozen=True)
class UserCard:
    """A traceable user card; every entry carries an evidence id."""

    address: dict[str, object]
    people: tuple[dict[str, str], ...]
    taboos: tuple[dict[str, str], ...]
    promises: tuple[dict[str, str], ...]
    ongoing: tuple[dict[str, str], ...]
    prefs: dict[str, tuple[dict[str, str], ...]]

    def to_payload(self) -> dict[str, object]:
        """Return the JSON-ready card, empty fields included."""
        return {
            "address": dict(self.address),
            "people": [dict(item) for item in self.people],
            "taboos": [dict(item) for item in self.taboos],
            "promises": [dict(item) for item in self.promises],
            "ongoing": [dict(item) for item in self.ongoing],
            "prefs": {
                "like": [dict(item) for item in self.prefs["like"]],
                "dislike": [dict(item) for item in self.prefs["dislike"]],
            },
        }

    def text(self) -> str:
        """Render the card, trimming the lowest-priority tail until <=400."""
        data = self.to_payload()
        rendered = _render(data)
        while len(rendered) > CARD_BUDGET:
            if not _drop_one(data):
                raise PersonaError(
                    E_PERSONA_BUDGET, f"用户卡无法压到 {CARD_BUDGET} 字符"
                )
            rendered = _render(data)
        return rendered


def load_rules(path: Path | None = None) -> dict[str, object]:
    """Load and compile the derivation rules; code stays ASCII."""
    target = path if path is not None else DEFAULT_RULES_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PersonaError(E_PERSONA_IO, f"无法读取用户卡规则：{target}") from exc
    except json.JSONDecodeError as exc:
        raise PersonaError(E_PERSONA_IO, f"用户卡规则不是合法 JSON：{target}") from exc
    if not isinstance(payload, dict):
        raise PersonaError(E_PERSONA_IO, "用户卡规则必须是对象")
    address = payload.get("address")
    prefs = payload.get("prefs")
    if not isinstance(address, dict) or not isinstance(prefs, dict):
        raise PersonaError(E_PERSONA_IO, "用户卡规则缺少 address / prefs")
    return payload


def derive_user_card(
    events: list[EvidenceEvent], rules: dict[str, object] | None = None
) -> UserCard:
    """Derive the user card from the kernel events only.

    Persona events are filtered out first, so a trait or a previous user-card
    proposal can never become a user fact.
    """
    table = rules if rules is not None else load_rules()
    core = core_events(events)
    address = _derive_address(core, table)
    people = _derive_people(core)
    taboos = tuple(
        {"text": event.text, "evidence": event.event_id}
        for event in core
        if event.type == "directive" and event.kind == "lock"
    )
    promises = _derive_promises(core)
    ongoing = tuple(
        {"text": event.text, "evidence": event.event_id}
        for event in core if event.type == "milestone"
    )[-ONGOING_LIMIT:]
    prefs = _derive_prefs(core, table)
    return UserCard(address, people, taboos, promises, ongoing, prefs)


def _derive_address(
    core: list[EvidenceEvent], table: dict[str, object]
) -> dict[str, object]:
    address = table.get("address")
    assert isinstance(address, dict)
    raw_negations = address.get("negations", [])
    negations = tuple(str(word) for word in raw_negations) if isinstance(
        raw_negations, list
    ) else ()
    raw_suffixes = address.get("suffixes", [])
    suffixes = tuple(str(word) for word in raw_suffixes) if isinstance(
        raw_suffixes, list
    ) else ()
    call, call_evidence, never = _derive_call(
        core, str(address.get("call", "")), negations, suffixes
    )
    self_name = _last_match(core, str(address.get("self", "")))
    payload: dict[str, object] = {
        "call": call,
        "self": self_name[0],
        "never": never,
    }
    if call:
        payload["call_evidence"] = call_evidence
    if self_name[0]:
        payload["self_evidence"] = self_name[1]
    return payload


def _derive_call(
    core: list[EvidenceEvent],
    pattern: str,
    negations: tuple[str, ...],
    suffixes: tuple[str, ...],
) -> tuple[str, str, list[dict[str, str]]]:
    """Split address directives into call and taboo; a taboo always wins.

    Negation is decided per clause, not by a prefix token: any clause that
    contains one of the configured negation words turns its "叫X" match into a
    taboo, whatever the surface form is. A clause with no negation can only set
    the call when it says "叫我X"; "妈妈叫桂花" is kinship, not an address.
    Trailing tails such as "就好" are removed before the name is compared.
    After scanning, a call that equals a taboo is dropped.
    """
    call = ""
    evidence = ""
    never: list[dict[str, str]] = []
    seen: set[str] = set()
    if not pattern:
        return call, evidence, never
    for event in core:
        for clause in CLAUSE_SPLIT.split(event.text):
            if not clause:
                continue
            negative = any(
                word and word in clause for word in negations
            )
            for match in re.finditer(pattern, clause):
                pronoun = (match.group(1) or "").strip()
                name = _trim_suffixes(match.group(2).strip(), suffixes)
                if not name:
                    continue
                if negative:
                    if name not in seen:
                        seen.add(name)
                        never.append({"text": name, "evidence": event.event_id})
                elif pronoun:
                    call = name
                    evidence = event.event_id
    if call and call in seen:
        call = ""
        evidence = ""
    return call, evidence, never


def _trim_suffixes(name: str, suffixes: tuple[str, ...]) -> str:
    """Strip hesitation tails ("就好", "吧", ...) so only the name is left."""
    trimmed = name
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if suffix and trimmed.endswith(suffix) and len(trimmed) > len(suffix):
                trimmed = trimmed[: -len(suffix)].strip()
                changed = True
    return trimmed


def _last_match(
    core: list[EvidenceEvent], pattern: str
) -> tuple[str, str]:
    value = ""
    evidence = ""
    if not pattern:
        return value, evidence
    for event in core:
        for match in re.finditer(pattern, event.text):
            candidate = match.group(1).strip()
            if candidate:
                value = candidate
                evidence = event.event_id
    return value, evidence


def _derive_people(core: list[EvidenceEvent]) -> tuple[dict[str, str], ...]:
    terms = sorted(lexicon_terms(), key=lambda term: (-len(term), term))
    pattern = re.compile(
        "(" + "|".join(re.escape(term) for term in terms)
        + r")叫([^，。！？,.!?]{1,%d})" % NAME_LIMIT
    )
    people: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for event in core:
        for match in pattern.finditer(event.text):
            relation = match.group(1)
            name = match.group(2).strip()
            key = (relation, name)
            if key in seen:
                continue
            seen.add(key)
            people.append({
                "relation": relation,
                "name": name,
                "evidence": event.event_id,
            })
    return tuple(people)


def _derive_promises(core: list[EvidenceEvent]) -> tuple[dict[str, str], ...]:
    promises: list[dict[str, str]] = []
    for event in core:
        if event.type != "turn" or not is_promise(event.text):
            continue
        if _promise_done(event, core):
            continue
        promises.append({
            "text": event.text,
            "since": event.stamp[:10],
            "evidence": event.event_id,
        })
    return tuple(promises)


def _promise_done(event: EvidenceEvent, core: list[EvidenceEvent]) -> bool:
    return any(
        marker in later.text
        for later in core if later.event_id > event.event_id
        for marker in DONE_MARKERS
    )


def _derive_prefs(
    core: list[EvidenceEvent], table: dict[str, object]
) -> dict[str, tuple[dict[str, str], ...]]:
    prefs = table.get("prefs")
    assert isinstance(prefs, dict)
    output: dict[str, tuple[dict[str, str], ...]] = {}
    for key in ("like", "dislike"):
        patterns = prefs.get(key)
        if not isinstance(patterns, list):
            raise PersonaError(E_PERSONA_INPUT, f"用户卡规则 prefs.{key} 非法")
        found: list[dict[str, str]] = []
        seen: set[str] = set()
        for event in core:
            for pattern in patterns:
                for match in re.finditer(str(pattern), event.text):
                    value = match.group(1).strip()[:TEXT_LIMIT]
                    if not value or value in seen:
                        continue
                    seen.add(value)
                    found.append({"text": value, "evidence": event.event_id})
        output[key] = tuple(found)
    return output


def _render(data: dict[str, object]) -> str:
    lines: list[str] = []
    address = data["address"]
    assert isinstance(address, dict)
    lead: list[str] = []
    if address.get("call"):
        lead.append(f"称呼：{address['call']}")
    if address.get("self"):
        lead.append(f"自称：{address['self']}")
    if lead:
        lines.append("；".join(lead))
    never = address.get("never")
    assert isinstance(never, list)
    if never:
        lines.append("忌称：" + "、".join(str(item["text"]) for item in never))
    for key, label in (
        ("taboos", "忌讳"),
        ("people", "人物"),
        ("promises", "承诺"),
        ("ongoing", "近况"),
    ):
        items = data[key]
        assert isinstance(items, list)
        if not items:
            continue
        parts: list[str] = []
        for item in items:
            if key == "people":
                relation = str(item["relation"])
                name = str(item.get("name", ""))
                parts.append(f"{relation} {name}".strip())
            elif key == "promises":
                parts.append(f"{item['text']}（自 {item['since']}）")
            else:
                parts.append(str(item["text"]))
        lines.append(f"{label}：" + "；".join(parts))
    prefs = data["prefs"]
    assert isinstance(prefs, dict)
    likes = [str(item["text"]) for item in prefs["like"]]
    dislikes = [str(item["text"]) for item in prefs["dislike"]]
    if likes or dislikes:
        parts = []
        if likes:
            parts.append("喜欢 " + "、".join(likes))
        if dislikes:
            parts.append("不喜欢 " + "、".join(dislikes))
        lines.append("偏好：" + "；".join(parts))
    return "\n".join(lines)


def _drop_one(data: dict[str, object]) -> bool:
    """Drop the last entry of the lowest-priority section that has one."""
    prefs = data["prefs"]
    assert isinstance(prefs, dict)
    for key in ("dislike", "like"):
        items = prefs[key]
        assert isinstance(items, list)
        if items:
            items.pop()
            return True
    for key in ("ongoing", "promises", "people", "taboos"):
        items = data[key]
        assert isinstance(items, list)
        if items:
            items.pop()
            return True
    address = data["address"]
    assert isinstance(address, dict)
    never = address.get("never")
    assert isinstance(never, list)
    if never:
        never.pop()
        return True
    if address.get("self"):
        del address["self"]
        address.pop("self_evidence", None)
        return True
    if address.get("call"):
        del address["call"]
        address.pop("call_evidence", None)
        return True
    return False


def pin_user_card(
    context: Context, card: UserCard, budget: int = 4096
) -> Context:
    """Put the user card first in the context and keep it there.

    The card is never evicted; when the card is larger than the whole budget
    the call fails instead of silently returning an unfaithful context.
    """
    text = card.text()
    tokens = estimate_tokens(text)
    if tokens > budget:
        raise PersonaError(
            E_PERSONA_BUDGET, f"用户卡需要 {tokens} tokens，超过预算 {budget}"
        )
    items = list(context.items)
    total = sum(item.tokens for item in items) + tokens
    while total > budget and items:
        total -= items.pop().tokens
    if total > budget:
        raise PersonaError(E_PERSONA_BUDGET, "用户卡无法装入预算")
    item = ContextItem(PINNED_ID, PINNED_SLOT, tokens, text)
    return Context(total, (item,) + tuple(items), context.candidates)
