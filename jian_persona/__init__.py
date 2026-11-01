"""L2 persona derivatives: traits, style card, user card (M16).

Nothing here enters the kernel kid. Everything is derived from the evidence
layer, rendered for assembly, and traceable to event ids.
"""

from __future__ import annotations

from jian_persona.errors import PersonaError
from jian_persona.model import (
    ActiveTrait,
    Conflict,
    TraitActivation,
    TraitDef,
    TraitResolution,
)
from jian_persona.style_card import (
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
from jian_persona.traits import (
    DEFAULT_VOCAB_PATH,
    load_vocabulary,
    resolve_traits,
    trait_activations,
)
from jian_persona.user_card import (
    UserCard,
    derive_user_card,
    load_rules,
    pin_user_card,
)
from jian_persona.view import PersonaView, build_persona_view

__all__ = [
    "ActiveTrait",
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
