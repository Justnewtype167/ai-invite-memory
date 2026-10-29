"""Fixed error codes for the Chinese rule layer (M2)."""

from __future__ import annotations

E_CN_UNKNOWN_TERM = "E_CN_UNKNOWN_TERM"
E_CN_PARSE = "E_CN_PARSE"
E_CN_BAD_ANCHOR = "E_CN_BAD_ANCHOR"
E_CN_DATA = "E_CN_DATA"

ALL_CODES = (
    E_CN_UNKNOWN_TERM,
    E_CN_PARSE,
    E_CN_BAD_ANCHOR,
    E_CN_DATA,
)


class CnError(Exception):
    """An error carrying one fixed E_CN_* code."""

    def __init__(self, code: str, message: str) -> None:
        if code not in ALL_CODES:
            raise ValueError(f"unknown error code: {code}")
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
