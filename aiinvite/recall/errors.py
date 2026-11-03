"""Fixed error codes for the recall layer (M3)."""

from __future__ import annotations

E_RC_NO_INDEX = "E_RC_NO_INDEX"
E_RC_STALE = "E_RC_STALE"
E_RC_BAD_BUDGET = "E_RC_BAD_BUDGET"
E_RC_IO = "E_RC_IO"
E_RC_STREAM = "E_RC_STREAM"

ALL_CODES = (
    E_RC_NO_INDEX,
    E_RC_STALE,
    E_RC_BAD_BUDGET,
    E_RC_IO,
    E_RC_STREAM,
)


class RecallError(Exception):
    """An error carrying one fixed E_RC_* code."""

    def __init__(self, code: str, message: str) -> None:
        if code not in ALL_CODES:
            raise ValueError(f"unknown error code: {code}")
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
