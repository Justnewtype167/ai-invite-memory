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
from jian_persona.traits import (
    DEFAULT_VOCAB_PATH,
    load_vocabulary,
    resolve_traits,
    trait_activations,
)

__all__ = [
    "ActiveTrait",
    "Conflict",
    "DEFAULT_VOCAB_PATH",
    "PersonaError",
    "TraitActivation",
    "TraitDef",
    "TraitResolution",
    "load_vocabulary",
    "resolve_traits",
    "trait_activations",
]
