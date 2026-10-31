"""Fixed error codes and the single exception type used by Jian."""

from __future__ import annotations

E_NOT_CANONICAL = "E_NOT_CANONICAL"
E_SCHEMA = "E_SCHEMA"
E_TAMPER = "E_TAMPER"
E_CHAIN_MISSING = "E_CHAIN_MISSING"
E_HEADER_MISMATCH = "E_HEADER_MISMATCH"
E_BLOB_MISSING = "E_BLOB_MISSING"
E_BLOB_MISMATCH = "E_BLOB_MISMATCH"
E_IO = "E_IO"
E_ARG = "E_ARG"

ALL_CODES = (
    E_NOT_CANONICAL,
    E_SCHEMA,
    E_TAMPER,
    E_CHAIN_MISSING,
    E_HEADER_MISMATCH,
    E_BLOB_MISSING,
    E_BLOB_MISMATCH,
    E_IO,
    E_ARG,
)


class JianError(Exception):
    """An error carrying one fixed E_* code and an optional event id."""

    def __init__(self, code: str, message: str, event_id: str | None = None) -> None:
        if code not in ALL_CODES:
            raise ValueError(f"unknown error code: {code}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.event_id = event_id

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
