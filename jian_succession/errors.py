"""Fixed error codes for the succession layer (M15)."""

from __future__ import annotations

E_SUCC_MODE = "E_SUCC_MODE"
E_SUCC_DRIFT = "E_SUCC_DRIFT"
E_SUCC_REDACTION = "E_SUCC_REDACTION"
E_SUCC_HEADER = "E_SUCC_HEADER"
E_SUCC_SCHEMA = "E_SUCC_SCHEMA"
E_SUCC_IO = "E_SUCC_IO"

ALL_CODES = (
    E_SUCC_MODE,
    E_SUCC_DRIFT,
    E_SUCC_REDACTION,
    E_SUCC_HEADER,
    E_SUCC_SCHEMA,
    E_SUCC_IO,
)


class SuccessionError(Exception):
    """An error carrying one fixed E_SUCC_* code."""

    def __init__(self, code: str, message: str) -> None:
        if code not in ALL_CODES:
            raise ValueError(f"unknown error code: {code}")
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
