"""AI Invite kernel: deterministic persona compilation with drift gates (M4)."""

from __future__ import annotations

from aiinvite.kernel.compiler import compile_kernel, read_evidence
from aiinvite.kernel.errors import KernelError
from aiinvite.kernel.history import (
    RecordResult,
    VerifyReport,
    diff_versions,
    history,
    record_kernel,
    restore,
    verify_kernel,
)
from aiinvite.kernel.incremental import (
    ReconcileReport,
    compile_kernel_incremental,
    reconcile,
)
from aiinvite.kernel.kernel import (
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
from aiinvite.kernel.proposer import (
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
