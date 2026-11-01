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
from jian_kernel.incremental import (
    ReconcileReport,
    compile_kernel_incremental,
    reconcile,
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
    LiveIngest,
    LiveProposal,
    NullProposer,
    Proposal,
    Proposer,
    ReplayProposer,
    StyleProposal,
    SubprocessProposer,
    evidence_summary,
    ingest_live,
    prompt_sha_for,
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
    "LiveIngest",
    "LiveProposal",
    "NullProposer",
    "Policy",
    "Proposal",
    "Proposer",
    "ReconcileReport",
    "RecordResult",
    "ReplayProposer",
    "StyleProposal",
    "SubprocessProposer",
    "VerifyReport",
    "compile_kernel",
    "compile_kernel_incremental",
    "diff_versions",
    "evidence_summary",
    "history",
    "ingest_live",
    "prompt_sha_for",
    "read_evidence",
    "reconcile",
    "record_kernel",
    "record_proposal",
    "restore",
    "verify_kernel",
]
