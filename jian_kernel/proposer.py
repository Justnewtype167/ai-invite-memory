"""Proposer protocol (M4/M5): null, replay and evidence-replay implementations.

M5 never calls a model. ``ReplayProposer`` reads ``proposal`` events already
recorded in evidence (or a canonical JSONL file, for the M4 K5 path) and
returns them for the compiler. Style proposals only change ``self.md``; the
canonical note path stays available for explicitly passed proposers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from jian.canonical import dumps
from jian.errors import JianError
from jian.event import (
    GENESIS_PREV,
    MODEL_MAX_CHARS,
    PROMPT_SHA_RE,
    PROPOSAL_TEXT_MAX_CHARS,
    SEGMENT_MAX_EVENTS,
    Event,
    new_event,
    utc_now,
)

from jian_kernel.errors import (
    E_KN_BAD_PROPOSAL,
    E_KN_BAD_TARGET,
    E_KN_IO,
    KernelError,
)
from jian_kernel.kernel import STYLE_TARGETS, EvidenceEvent, Policy

CHAIN_PATH = "chain.json"
MANIFEST_PATH = "manifest.json"
EVIDENCE_DIR = "evidence"


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


@dataclass(frozen=True)
class StyleProposal:
    """One style proposal read back from a ``proposal`` evidence event."""

    event_id: str
    target: str
    text: str
    model: str
    prompt_sha: str


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
    """Replay proposals: from evidence events, or from a canonical JSONL file.

    With a ``path`` the M4 behaviour is kept: every line is a canonical
    proposal. Without a path the proposer is in evidence mode: it contributes
    no canonical entries and only serves ``style`` for the compiler.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path

    def propose(self, store: Path, policy: Policy) -> list[Proposal]:
        """Return released canonical proposals; evidence mode returns none."""
        if self._path is None:
            return []
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

    def style(self, events: list[EvidenceEvent]) -> list[StyleProposal]:
        """Return every ``proposal`` event ordered by numeric event id."""
        found = [event for event in events if event.type == "proposal"]
        found.sort(key=lambda event: int(event.event_id.split("_")[1]))
        return [
            StyleProposal(
                event.event_id,
                event.target or "",
                event.text,
                event.model or "",
                event.prompt_sha or "",
            )
            for event in found
        ]


def record_proposal(
    store: Path,
    target: str,
    text: str,
    model: str,
    prompt_sha: str,
    t: str | None = None,
) -> EvidenceEvent:
    """Append one ``proposal`` event to the evidence chain.

    The proposal is evidence like any other: it gets the next global event
    id, the chain ``prev`` hash and a segment position. ``capsule.py`` is
    frozen and its ``append_event`` cannot carry ``model`` / ``prompt_sha``,
    so this function maintains the same chain rules itself.
    """
    if not store.is_dir() or not (store / EVIDENCE_DIR).is_dir():
        raise KernelError(E_KN_IO, f"存储目录未初始化：{store}")
    _check_proposal_input(target, text, model, prompt_sha)
    folder = store / EVIDENCE_DIR
    paths = sorted(folder.glob("seg-*.jsonl"))
    total = 0
    last_hash: str | None = None
    last_segment: str | None = None
    last_count = 0
    for path in paths:
        try:
            lines = [
                line for line in path.read_text(encoding="utf-8").splitlines() if line
            ]
        except OSError as exc:
            raise KernelError(E_KN_IO, f"无法读取证据段：{path}") from exc
        if not lines:
            continue
        total += len(lines)
        try:
            data = json.loads(lines[-1])
        except json.JSONDecodeError as exc:
            raise KernelError(E_KN_IO, f"证据行无法解析：{path}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("hash"), str):
            raise KernelError(E_KN_IO, f"证据缺少 hash：{path}")
        last_hash = str(data["hash"])
        last_segment = path.stem
        last_count = len(lines)
    chain = _load_chain(store)
    sealed = None if chain is None else chain["sealed_at"]
    if sealed is not None or last_segment is None or last_count >= SEGMENT_MAX_EVENTS:
        rows = chain["segments"] if chain is not None else []
        episode = f"seg-{len(rows) + len(paths) + 1:04d}" if chain is None else \
            f"seg-{len(rows) + 1:04d}"
        new_segment = True
    else:
        episode = last_segment
        new_segment = False
    previous = last_hash if last_hash is not None else GENESIS_PREV
    try:
        event = new_event(
            total + 1,
            episode,
            t if t is not None else utc_now(),
            None,
            text,
            previous,
            type="proposal",
            target=target,
            model=model,
            prompt_sha=prompt_sha,
        )
    except JianError as exc:
        raise KernelError(E_KN_BAD_PROPOSAL, exc.message) from exc
    try:
        with (folder / f"{episode}.jsonl").open("ab") as handle:
            handle.write(event.to_line())
    except OSError as exc:
        raise KernelError(E_KN_IO, f"写入证据失败：{folder}") from exc
    if chain is not None:
        _update_chain(store, chain, event, episode, new_segment)
    _remove_if_exists(store / MANIFEST_PATH)
    return EvidenceEvent(
        event.id, event.t, event.type, None, event.text,
        event.target, event.model, event.prompt_sha,
    )


def _check_proposal_input(
    target: str, text: str, model: str, prompt_sha: str
) -> None:
    """Validate proposal input and raise the fixed G5 error codes."""
    if not isinstance(target, str) or target not in STYLE_TARGETS:
        raise KernelError(
            E_KN_BAD_TARGET, f"提案 target 不在白名单：{target}"
        )
    if not isinstance(text, str) or not 1 <= len(text) <= PROPOSAL_TEXT_MAX_CHARS:
        raise KernelError(E_KN_BAD_PROPOSAL, "提案 text 必须是 1-500 字符")
    if not isinstance(model, str) or not model or len(model) > MODEL_MAX_CHARS:
        raise KernelError(E_KN_BAD_PROPOSAL, "提案 model 必须是非空字符串且不超过 64 字符")
    if not isinstance(prompt_sha, str) or not PROMPT_SHA_RE.match(prompt_sha):
        raise KernelError(E_KN_BAD_PROPOSAL, "提案 prompt_sha 必须是十六进制")


def _load_chain(store: Path) -> dict[str, object] | None:
    """Return ``chain.json`` when present; a missing file is not an error."""
    path = store / CHAIN_PATH
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise KernelError(E_KN_IO, f"无法读取 chain.json：{path}") from exc
    except json.JSONDecodeError as exc:
        raise KernelError(E_KN_IO, f"chain.json 无法解析：{path}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("segments"), list):
        raise KernelError(E_KN_IO, f"chain.json 结构非法：{path}")
    if "sealed_at" not in data:
        raise KernelError(E_KN_IO, f"chain.json 缺少 sealed_at：{path}")
    return data


def _update_chain(
    store: Path,
    chain: dict[str, object],
    event: Event,
    episode: str,
    new_segment: bool,
) -> None:
    """Update ``chain.json`` exactly like ``capsule.append_event`` does."""
    rows = chain["segments"]
    if not isinstance(rows, list):
        raise KernelError(E_KN_IO, f"chain.json segments 非法：{store}")
    if new_segment:
        rows.append({
            "seg": episode,
            "count": 1,
            "first": event.hash,
            "last": event.hash,
            "prev_seg": rows[-1]["seg"] if rows else None,
        })
    else:
        last = rows[-1]
        if not isinstance(last, dict):
            raise KernelError(E_KN_IO, f"chain.json 末段非法：{store}")
        last["count"] = int(last["count"]) + 1
        last["last"] = event.hash
    payload = {"v": 1, "sealed_at": None, "segments": rows}
    try:
        (store / CHAIN_PATH).write_bytes(dumps(payload))
    except OSError as exc:
        raise KernelError(E_KN_IO, f"写入 chain.json 失败：{store}") from exc


def _remove_if_exists(path: Path) -> None:
    """Remove a file if it exists; a failure is reported as E_KN_IO."""
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise KernelError(E_KN_IO, f"无法删除 {path}：{exc}") from exc


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
