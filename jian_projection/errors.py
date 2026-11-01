"""Fixed error codes for the projection layer (M11)."""

from __future__ import annotations

E_PR_SCHEMA = "E_PR_SCHEMA"
E_PR_EMPTY = "E_PR_EMPTY"
E_PR_MISSING_KID = "E_PR_MISSING_KID"
E_PR_UNKNOWN_PROJECTOR = "E_PR_UNKNOWN_PROJECTOR"
E_PR_UNKNOWN_ACTION = "E_PR_UNKNOWN_ACTION"
E_PR_BAD_DURATION = "E_PR_BAD_DURATION"
E_PR_MAP_INVALID = "E_PR_MAP_INVALID"

ALL_CODES = (
    E_PR_SCHEMA,
    E_PR_EMPTY,
    E_PR_MISSING_KID,
    E_PR_UNKNOWN_PROJECTOR,
    E_PR_UNKNOWN_ACTION,
    E_PR_BAD_DURATION,
    E_PR_MAP_INVALID,
)


class ProjectionError(Exception):
    """An error carrying one fixed E_PR_* code."""

    def __init__(self, code: str, message: str) -> None:
        if code not in ALL_CODES:
            raise ValueError(f"unknown error code: {code}")
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
