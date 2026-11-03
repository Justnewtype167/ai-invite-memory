"""emit: the only path from a trace to a sink, always through the gate (M13).

The sink is called at most once and only when the gate allows the trace.
A refusal never reaches the sink; when a store is given, the refusal itself
is written into the evidence layer so that the decision stays auditable.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from aiinvite.capsule import append_refusal

from aiinvite.projection.errors import E_PR_GATE_SCOPE, ProjectionError
from aiinvite.projection.gate import Verdict, check
from aiinvite.projection.trace import Trace

EMIT_MODES = ("text", "action", "both")


def trace_digest(trace: Trace) -> str:
    """Return ``sha256:<hex>`` of the trace's canonical bytes."""
    return "sha256:" + hashlib.sha256(trace.to_bytes()).hexdigest()


def emit(
    trace: Trace,
    kernel: object,
    sink: Callable[[Trace], None],
    store: Path | None = None,
    mode: str = "text",
    t: str | None = None,
) -> Verdict:
    """Judge a trace first, then call ``sink`` only when it is allowed.

    ``mode`` records what was about to be emitted (``text`` / ``action`` /
    ``both``) and becomes the refusal's ``target``. A refused trace never
    touches ``sink``; if ``store`` is not None the refusal is appended to the
    evidence chain. A successful emission writes no event on purpose: only
    rare, meaningful refusals are worth keeping.
    """
    if mode not in EMIT_MODES:
        raise ProjectionError(E_PR_GATE_SCOPE, f"unknown emit mode: {mode}")
    verdict = check(trace, kernel)
    if not verdict.allowed:
        if store is not None:
            append_refusal(
                store, mode, str(verdict.rule), trace_digest(trace), t
            )
        return verdict
    sink(trace)
    return verdict
