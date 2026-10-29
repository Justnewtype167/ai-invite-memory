"""Proposer protocol (M4) with a null and a replay implementation.

M4 never calls a model. ``NullProposer`` contributes nothing, so the compiler
is a pure function of evidence and policy. ``ReplayProposer`` reads proposals
recorded earlier; it exists for M5 and is exercised by tests here without
touching a model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from jian_kernel.errors import E_KN_IO, KernelError
from jian_kernel.kernel import Policy


@dataclass(frozen=True)
class Proposal:
    """One proposed canonical entry; it must cite evidence event ids."""

    text: str
    evidence: tuple[str, ...]
    kind: str = "note"

    def to_payload(self) -> dict[str, object]:
        """Return the JSON-ready view of this proposal."""
        return {
            "evidence": list(self.evidence),
            "kind": self.kind,
            "text": self.text,
        }


class Proposer(Protocol):
    """Anything that can propose canonical entries for a store."""

    def propose(self, store: Path, policy: Policy) -> list[Proposal]:
        """Return proposals for ``store`` under ``policy``."""


class NullProposer:
    """A proposer that never proposes anything."""

    def propose(self, store: Path, policy: Policy) -> list[Proposal]:
        """Return an empty proposal list."""
        return []


class ReplayProposer:
    """A proposer that replays proposals recorded as canonical JSONL."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def propose(self, store: Path, policy: Policy) -> list[Proposal]:
        """Return the recorded proposals in file order."""
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise KernelError(E_KN_IO, f"无法读取提案记录：{self._path}") from exc
        proposals: list[Proposal] = []
        for line in lines:
            if not line:
                continue
            proposals.append(_parse_proposal(line, self._path))
        return proposals


def _parse_proposal(line: str, path: Path) -> Proposal:
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        raise KernelError(E_KN_IO, f"提案行无法解析：{path}") from exc
    if not isinstance(data, dict):
        raise KernelError(E_KN_IO, f"提案行不是对象：{path}")
    text = data.get("text")
    kind = data.get("kind", "note")
    evidence = data.get("evidence", [])
    if not isinstance(text, str) or not text:
        raise KernelError(E_KN_IO, f"提案缺少 text：{path}")
    if not isinstance(kind, str):
        raise KernelError(E_KN_IO, f"提案 kind 不是字符串：{path}")
    if not isinstance(evidence, list) or not all(
        isinstance(item, str) for item in evidence
    ):
        raise KernelError(E_KN_IO, f"提案 evidence 不是字符串数组：{path}")
    return Proposal(text=text, evidence=tuple(evidence), kind=kind)
