"""One derivation pipeline: kernel + traits + style card + user card (M16).

``PersonaView.self_md`` is the only place where persona prose is rendered.
The kernel ``self.md`` stays a kid input and is never touched here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from aiinvite.kernel.compiler import compile_kernel, read_evidence
from aiinvite.kernel.kernel import Kernel, Policy

from aiinvite.persona.errors import E_PERSONA_INPUT, PersonaError
from aiinvite.persona.model import ActiveTrait, Conflict
from aiinvite.persona.style_card import StyleCard, load_style_card
from aiinvite.persona.traits import load_vocabulary, resolve_traits
from aiinvite.persona.user_card import UserCard, derive_user_card

GROUP_VALUES = ("A", "B", "C", "D")


@dataclass(frozen=True)
class PersonaView:
    """The derived persona for assembly; none of it enters the kid."""

    kid: str
    head: str
    traits: tuple[ActiveTrait, ...]
    conflicts: tuple[Conflict, ...]
    reasons: tuple[str, ...]
    style_card: StyleCard | None
    user_card: UserCard | None
    self_md: str

    def to_prompt(self, group: str) -> str:
        """Return the prompt body for one of the four comparison groups."""
        if group not in GROUP_VALUES:
            raise PersonaError(E_PERSONA_INPUT, f"未知对照分组：{group}")
        if group == "A":
            return ""
        body = _traits_section(self.traits)
        if group == "B":
            return body
        if self.style_card is not None:
            body = body + "\n" + _style_section(self.style_card)
        if group == "C":
            return body
        if self.user_card is not None:
            body = body + "\n" + _user_section(self.user_card)
        return body


def build_persona_view(
    store: Path,
    *,
    kernel: Kernel | None = None,
    events: list | None = None,
    mode: str = "support",
    exclude: Mapping[str, str] | None = None,
    style_card: StyleCard | None = None,
    user_card: UserCard | None = None,
    card_cache: dict | None = None,
    policy: Policy | None = None,
) -> PersonaView:
    """Build the persona view from evidence, with optional overrides.

    ``kernel`` lets a caller pass a kernel compiled elsewhere, typically the
    result of ``compile_kernel_incremental``, so this call does not recompile
    the evidence. When it is ``None`` the view compiles internally exactly as
    before. The supplied kernel is used as the identity source unchanged:
    ``kid`` and ``head`` still come from it, and no card can move them.

    ``style_card`` and ``user_card`` overrides exist for experiments and for
    tests that compare cards without rewriting evidence. Card changes cannot
    move identity.
    """
    if events is None:
        events = read_evidence(store)
    if kernel is None:
        kernel = compile_kernel(store, policy, events=events)
    resolution = resolve_traits(events, load_vocabulary(), mode)
    traits = tuple(sorted(resolution.active, key=lambda item: item.event_id))
    if style_card is None:
        style_card = load_style_card(store, exclude, events=events)
    if user_card is None:
        user_card = derive_user_card(events, cache=card_cache)
    self_md = _self_md(traits, resolution.conflicts, resolution.reasons)
    return PersonaView(
        kid=kernel.kid,
        head=kernel.head,
        traits=traits,
        conflicts=resolution.conflicts,
        reasons=resolution.reasons,
        style_card=style_card,
        user_card=user_card,
        self_md=self_md,
    )


def _self_md(
    traits: tuple[ActiveTrait, ...],
    conflicts: tuple[Conflict, ...],
    reasons: tuple[str, ...],
) -> str:
    lines = ["# Persona view", "## Traits"]
    if not traits:
        lines.append("- none")
    for item in traits:
        lines.append(
            f"- {item.name}: {item.guidance} ({item.origin} {item.event_id})"
        )
    lines.append("")
    lines.append("### Conflicts")
    if not conflicts:
        lines.append("- none")
    for item in conflicts:
        lines.append(
            f"- {item.winner} beats {item.loser}: {item.reason} "
            f"({item.winner} {item.winner_event}, {item.loser} {item.loser_event})"
        )
    if reasons:
        lines.append("")
        lines.append("## Notes")
        lines.extend(f"- {reason}" for reason in reasons)
    return "\n".join(lines)


def _traits_section(traits: tuple[ActiveTrait, ...]) -> str:
    lines = ["## Traits"]
    if not traits:
        lines.append("- none")
    for item in traits:
        lines.append(f"- {item.name}: {item.guidance}")
    return "\n".join(lines)


def _style_section(card: StyleCard) -> str:
    lines = [
        "## Style",
        f"- rhythm: {card.rhythm}",
        f"- address: {card.address}",
        f"- tics: {'、'.join(card.tics)}",
    ]
    if card.examples:
        lines.append(f"- examples: {' | '.join(card.examples)}")
    if card.counter_examples:
        lines.append(
            f"- counter: {' | '.join(card.counter_examples)}"
        )
    if card.forbidden:
        lines.append(f"- forbidden: {'、'.join(card.forbidden)}")
    return "\n".join(lines)


def _user_section(card: UserCard) -> str:
    text = card.text()
    return "## User\n" + (text if text else "- none")
