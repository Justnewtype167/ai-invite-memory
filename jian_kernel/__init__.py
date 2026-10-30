"""Jian kernel: deterministic persona compilation with drift gates (M4)."""

from __future__ import annotations

from jian_kernel.compiler import compile_kernel, read_evidence
from jian_kernel.errors import KernelError
from jian_kernel.history import (
    RecordResult,
    VerifyReport,
    diff_versions,
    history,
    record_kernel,
    restore,
    verify_kernel,
)
from jian_kernel.kernel import (
    Anchor,
    CanonEntry,
    Delta,
    Diff,
    EvidenceEvent,
    GraphEdge,
    HistoryEntry,
    Kernel,
    Policy,
)
from jian_kernel.proposer import (
    NullProposer,
    Proposal,
    Proposer,
    ReplayProposer,
    StyleProposal,
    record_proposal,
)

__all__ = [
    "Anchor",
    "CanonEntry",
    "Delta",
    "Diff",
    "EvidenceEvent",
    "GraphEdge",
    "HistoryEntry",
    "Kernel",
    "KernelError",
    "NullProposer",
    "Policy",
    "Proposal",
    "Proposer",
    "RecordResult",
    "ReplayProposer",
    "StyleProposal",
    "VerifyReport",
    "compile_kernel",
    "diff_versions",
    "history",
    "read_evidence",
    "record_kernel",
    "record_proposal",
    "restore",
    "verify_kernel",
]
