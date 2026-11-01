"""Fixed error codes for the persona kernel (M4)."""

from __future__ import annotations

E_KN_UNSOURCED = "E_KN_UNSOURCED"
E_KN_GATE_CANON = "E_KN_GATE_CANON"
E_KN_GATE_DELTA = "E_KN_GATE_DELTA"
E_KN_GATE_STATE = "E_KN_GATE_STATE"
E_KN_NO_HISTORY = "E_KN_NO_HISTORY"
E_KN_STALE = "E_KN_STALE"
E_KN_IO = "E_KN_IO"
E_KN_BAD_TARGET = "E_KN_BAD_TARGET"
E_KN_BAD_PROPOSAL = "E_KN_BAD_PROPOSAL"
E_KN_NO_PROPOSAL = "E_KN_NO_PROPOSAL"
E_KN_THIN_EVIDENCE = "E_KN_THIN_EVIDENCE"
E_KN_SNAPSHOT = "E_KN_SNAPSHOT"
E_KN_DRIFT = "E_KN_DRIFT"
E_KN_TAMPER = "E_KN_TAMPER"
E_PROPOSER_FAILED = "E_PROPOSER_FAILED"

ALL_CODES = (
    E_KN_UNSOURCED,
    E_KN_GATE_CANON,
    E_KN_GATE_DELTA,
    E_KN_GATE_STATE,
    E_KN_NO_HISTORY,
    E_KN_STALE,
    E_KN_IO,
    E_KN_BAD_TARGET,
    E_KN_BAD_PROPOSAL,
    E_KN_NO_PROPOSAL,
    E_KN_THIN_EVIDENCE,
    E_KN_SNAPSHOT,
    E_KN_DRIFT,
    E_KN_TAMPER,
    E_PROPOSER_FAILED,
)


class KernelError(Exception):
    """An error carrying one fixed E_KN_* code."""

    def __init__(self, code: str, message: str) -> None:
        if code not in ALL_CODES:
            raise ValueError(f"unknown error code: {code}")
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
