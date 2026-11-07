"""L2 persona derivatives: traits, style card, user card (M16).

Nothing here enters the kernel kid. Everything is derived from the evidence
layer, rendered for assembly, and traceable to event ids.
"""

from __future__ import annotations

from aiinvite.persona.card_fold import CardState, fold_user_card
from aiinvite.persona.errors import PersonaError
from aiinvite.persona.model import (
    ActiveTrait,
    Conflict,
    TraitActivation,
    TraitDef,
    TraitResolution,
)
from aiinvite.persona.style_card import (
    EchoResult,
    StyleCard,
    StyleInput,
    assert_redacted,
    echo_guard,
    load_style_card,
    parse_style_card,
    record_style_card,
    style_input,
)
from aiinvite.persona.traits import (
    DEFAULT_VOCAB_PATH,
    load_vocabulary,
    resolve_traits,
    trait_activations,
)
from aiinvite.persona.user_card import (
    UserCard,
    derive_user_card,
    load_rules,
    pin_user_card,
)
from aiinvite.persona.view import PersonaView, build_persona_view

__all__ = [
    "ActiveTrait",
    "CardState",
    "Conflict",
    "DEFAULT_VOCAB_PATH",
    "EchoResult",
    "PersonaError",
    "PersonaView",
    "StyleCard",
    "StyleInput",
    "TraitActivation",
    "TraitDef",
    "TraitResolution",
    "UserCard",
    "assert_redacted",
    "build_persona_view",
    "derive_user_card",
    "echo_guard",
    "fold_user_card",
    "load_rules",
    "load_style_card",
    "load_vocabulary",
    "parse_style_card",
    "pin_user_card",
    "record_style_card",
    "resolve_traits",
    "style_input",
    "trait_activations",
]
