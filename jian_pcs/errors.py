"""Fixed error codes for the PCS package."""

from __future__ import annotations

E_PCS_IO = "E_PCS_IO"
E_PCS_SCHEMA = "E_PCS_SCHEMA"

ALL_CODES = (E_PCS_IO, E_PCS_SCHEMA)


class PcsError(Exception):
    """Per-case error with a fixed ``E_PCS_*`` code."""

    def __init__(self, code: str, message: str) -> None:
        """Store the code and message; ``str`` renders ``code: message``."""
        if code not in ALL_CODES:
            raise ValueError(f"unknown PCS error code: {code}")
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")
