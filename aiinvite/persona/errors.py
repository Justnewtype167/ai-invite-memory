"""Fixed error codes for the persona layer (M16)."""

from __future__ import annotations

E_PERSONA_TRAIT_SCHEMA = "E_PERSONA_TRAIT_SCHEMA"
E_PERSONA_TRAIT_MODE = "E_PERSONA_TRAIT_MODE"
E_PERSONA_TRAIT_CONFLICT = "E_PERSONA_TRAIT_CONFLICT"
E_PERSONA_TRAIT_CAP = "E_PERSONA_TRAIT_CAP"
E_PERSONA_UNAPPROVED = "E_PERSONA_UNAPPROVED"
E_PERSONA_STYLE_CARD = "E_PERSONA_STYLE_CARD"
E_PERSONA_REDACTION = "E_PERSONA_REDACTION"
E_PERSONA_BUDGET = "E_PERSONA_BUDGET"
E_PERSONA_IO = "E_PERSONA_IO"
E_PERSONA_INPUT = "E_PERSONA_INPUT"

ALL_CODES = (
    E_PERSONA_TRAIT_SCHEMA,
    E_PERSONA_TRAIT_MODE,
    E_PERSONA_TRAIT_CONFLICT,
    E_PERSONA_TRAIT_CAP,
    E_PERSONA_UNAPPROVED,
    E_PERSONA_STYLE_CARD,
    E_PERSONA_REDACTION,
    E_PERSONA_BUDGET,
    E_PERSONA_IO,
    E_PERSONA_INPUT,
)


class PersonaError(Exception):
    """An error carrying one fixed E_PERSONA_* code."""

    def __init__(self, code: str, message: str) -> None:
        if code not in ALL_CODES:
            raise ValueError(f"unknown error code: {code}")
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
