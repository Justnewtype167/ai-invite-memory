"""Kernel data model and deterministic serialization (M4).

``kid`` is the content identity of a compiled kernel. ``version`` is the
ledger position of that ``kid`` in ``HISTORY.jsonl``; it is never part of the
``kid`` computation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from jian.canonical import dumps

from jian_kernel.errors import E_KN_IO, KernelError

COMPILER_VERSION = "0.4"
GENERATION = 0
INITIAL_STATE = {"intimacy": 500, "stability": 500, "trust": 500}
STATE_MIN = 0
STATE_MAX = 1000
STATE_STEP_LIMIT = 200
DEFAULT_DELTA_LIMIT = 200
KERNEL_DIR = "kernel"
HISTORY_FILE = "HISTORY.jsonl"
META_FILE = "META.json"
EVIDENCE_DIR = "evidence"

STYLE_TARGET = "self.style"
CONDUCT_TARGET = "self.conduct"
STYLE_TARGETS = (STYLE_TARGET, CONDUCT_TARGET)
STYLE_SECTIONS = ((STYLE_TARGET, "Style"), (CONDUCT_TARGET, "Conduct"))
STYLE_TEXT_MAX = 120
STYLE_TOTAL_MAX = 800
STYLE_MAX_PER_TARGET = 8

ORIGIN_RULE_ONLY = "rule_only"
ORIGIN_WITH_PROPOSALS = "with_proposals"
ORIGIN_RULE_FALLBACK = "rule_fallback"
ORIGINS = (ORIGIN_RULE_ONLY, ORIGIN_WITH_PROPOSALS, ORIGIN_RULE_FALLBACK)


def parse_stamp(value: str) -> datetime:
    """Parse a timezone-aware ISO 8601 string into a UTC datetime."""
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise KernelError(E_KN_IO, f"时间无法解析：{value}") from exc
    if moment.tzinfo is None:
        raise KernelError(E_KN_IO, f"时间必须带时区：{value}")
    return moment.astimezone(timezone.utc)


def stamp_text(value: datetime) -> str:
    """Format a datetime as the canonical ``YYYY-MM-DDTHH:MM:SSZ`` string."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Policy:
    """Compilation policy. ``delta_limit`` is per mille, never a float."""

    now: str | None = None
    delta_limit: int = DEFAULT_DELTA_LIMIT
    require_proposals: bool = False
    allow_fallback: bool = False
    force_fallback: bool = False

    def resolved_now(self, fallback: str) -> datetime:
        """Return the policy clock, falling back to the latest evidence stamp."""
        return parse_stamp(self.now) if self.now else parse_stamp(fallback)

    def payload(self, moment: datetime) -> dict[str, object]:
        """Return the canonical policy view used for hashing."""
        return {"delta_limit": self.delta_limit, "now": stamp_text(moment)}

    def hash(self, moment: datetime) -> str:
        """Return the sha256 of the canonical policy view."""
        return hashlib.sha256(dumps(self.payload(moment))).hexdigest()


@dataclass(frozen=True)
class EvidenceEvent:
    """One evidence event in the shape the kernel needs."""

    event_id: str
    stamp: str
    type: str
    kind: str | None
    text: str
    target: str | None = None
    model: str | None = None
    prompt_sha: str | None = None
    quant: str | None = None
    weights_sha: str | None = None
    temp_milli: int | None = None
    seed: int | None = None


@dataclass(frozen=True)
class CanonEntry:
    """One canonical entry; every entry carries its evidence ids."""

    kind: str
    text: str
    evidence: tuple[str, ...]

    def identity(self) -> tuple[str, str, tuple[str, ...]]:
        """Return the full identity used to detect any edit of an entry."""
        return (self.kind, self.text, self.evidence)

    def source(self) -> tuple[str, tuple[str, ...]]:
        """Return the source key shared by edited versions of one entry."""
        return (self.kind, self.evidence)

    def to_payload(self) -> dict[str, object]:
        """Return the JSON-ready view of this entry."""
        return {
            "evidence": list(self.evidence),
            "kind": self.kind,
            "text": self.text,
        }

    def line(self) -> str:
        """Return this entry as one machine-readable markdown bullet."""
        return "- " + dumps(self.to_payload()).decode("utf-8")


@dataclass(frozen=True)
class GraphEdge:
    """One kinship edge with its evidence event id."""

    term: str
    candidates: tuple[str, ...]
    event_id: str

    def to_payload(self) -> dict[str, object]:
        """Return the JSON-ready view of this edge."""
        return {
            "candidates": list(self.candidates),
            "event_id": self.event_id,
            "term": self.term,
        }


@dataclass(frozen=True)
class Anchor:
    """One resolved time expression with its evidence event id."""

    expr: str
    start: str | None
    end: str | None
    granularity: str
    certainty: str
    event_id: str

    def to_payload(self) -> dict[str, object]:
        """Return the JSON-ready view of this anchor."""
        return {
            "certainty": self.certainty,
            "end": self.end,
            "event_id": self.event_id,
            "expr": self.expr,
            "granularity": self.granularity,
            "start": self.start,
        }


@dataclass(frozen=True)
class Delta:
    """Entry-level change counts between two kernel versions."""

    added: int
    changed: int
    removed: int

    def total(self) -> int:
        """Return the number of changed entries."""
        return self.added + self.changed + self.removed

    def to_payload(self) -> dict[str, object]:
        """Return the JSON-ready view of this delta."""
        return {"added": self.added, "changed": self.changed, "removed": self.removed}


@dataclass(frozen=True)
class Diff:
    """Entry-level difference between two versions."""

    added: tuple[CanonEntry, ...]
    changed: tuple[CanonEntry, ...]
    removed: tuple[CanonEntry, ...]

    def to_payload(self) -> dict[str, object]:
        """Return the JSON-ready view of this diff."""
        return {
            "added": [entry.to_payload() for entry in self.added],
            "changed": [entry.to_payload() for entry in self.changed],
            "removed": [entry.to_payload() for entry in self.removed],
        }

    def delta(self) -> Delta:
        """Return the change counts of this diff."""
        return Delta(len(self.added), len(self.changed), len(self.removed))


@dataclass(frozen=True)
class HistoryEntry:
    """One appended line of ``HISTORY.jsonl``."""

    version: int
    kid: str
    head: str
    at: str
    delta: Delta
    origin: str = ORIGIN_RULE_ONLY

    def to_payload(self) -> dict[str, object]:
        """Return the JSON-ready view of this history line."""
        return {
            "at": self.at,
            "delta": self.delta.to_payload(),
            "head": self.head,
            "kid": self.kid,
            "origin": self.origin,
            "version": self.version,
        }

    def to_line(self) -> bytes:
        """Return this entry as one canonical JSONL line."""
        return dumps(self.to_payload()) + b"\n"


@dataclass(frozen=True)
class Kernel:
    """A compiled kernel; it never knows its own version."""

    kid: str
    head: str
    canon: tuple[CanonEntry, ...]
    edges: tuple[GraphEdge, ...]
    anchors: tuple[Anchor, ...]
    state: dict[str, int]
    self_md: str
    canon_md: str
    policy_hash: str
    compiler_version: str = COMPILER_VERSION
    generation: int = GENERATION
    origin: str = ORIGIN_RULE_ONLY
    style: tuple[str, ...] = ()
    rejected: int = 0
    models: tuple[str, ...] = ()

    def graph_payload(self) -> dict[str, object]:
        """Return the canonical graph view."""
        return {
            "anchors": [anchor.to_payload() for anchor in self.anchors],
            "edges": [edge.to_payload() for edge in self.edges],
        }

    def files(self, version: int) -> dict[str, bytes]:
        """Return every kernel file as deterministic bytes for ``version``."""
        meta = {
            "compiler_version": self.compiler_version,
            "generation": self.generation,
            "head": self.head,
            "kid": self.kid,
            "models": list(self.models),
            "origin": self.origin,
            "policy_hash": self.policy_hash,
            "proposals": {"accepted": len(self.style), "rejected": self.rejected},
            "version": version,
        }
        return {
            META_FILE: dumps(meta),
            "canon.md": self.canon_md.encode("utf-8"),
            "graph.json": dumps(self.graph_payload()),
            "self.md": self.self_md.encode("utf-8"),
            "state.json": dumps(dict(self.state)),
        }


def render_canon(entries: tuple[CanonEntry, ...]) -> str:
    """Render canonical entries as a deterministic markdown document."""
    lines = ["# Canon", ""]
    for entry in entries:
        lines.append(entry.line())
    return "\n".join(lines) + "\n"


def parse_canon(text: str) -> tuple[CanonEntry, ...]:
    """Parse a ``canon.md`` document; unreadable bullets are skipped.

    Skipping keeps a hand-edited document from crashing the gate: the
    resulting entry set simply stops matching and the gate reports canon.
    """
    entries: list[CanonEntry] = []
    for line in text.splitlines():
        if not line.startswith("- "):
            continue
        try:
            data = json.loads(line[2:])
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        kind = data.get("kind")
        body = data.get("text")
        evidence = data.get("evidence")
        if not isinstance(kind, str) or not isinstance(body, str):
            continue
        if not isinstance(evidence, list) or not all(
            isinstance(item, str) for item in evidence
        ):
            continue
        entries.append(CanonEntry(kind, body, tuple(evidence)))
    return tuple(entries)


def kernel_kid(self_md: str, canon_md: str, state: dict[str, int],
               graph: dict[str, object], origin: str,
               models: tuple[str, ...] = ()) -> str:
    """Return the content identity of a kernel; version is never included.

    ``origin`` records whether a model-shaped source contributed (or the
    rules had to fall back), so a change of input source always changes the
    kid. ``models`` records every model that proposed, so the same evidence
    under a different model can never share a kid.
    """
    payload = {
        "canon": canon_md,
        "graph": graph,
        "models": list(models),
        "origin": origin,
        "self": self_md,
        "state": dict(state),
    }
    return hashlib.sha256(dumps(payload)).hexdigest()
