"""Proposer protocol (M4/M5): null, replay and evidence-replay implementations.

M5 never calls a model. ``ReplayProposer`` reads ``proposal`` events already
recorded in evidence (or a canonical JSONL file, for the M4 K5 path) and
returns them for the compiler. Style proposals only change ``self.md``; the
canonical note path stays available for explicitly passed proposers.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from aiinvite.canonical import dumps
from aiinvite.errors import AiInviteError
from aiinvite.event import (
    GENESIS_PREV,
    MODEL_MAX_CHARS,
    PROMPT_SHA_RE,
    PROPOSAL_TEXT_MAX_CHARS,
    SEGMENT_MAX_EVENTS,
    WEIGHTS_SHA_RE,
    Event,
    event_text,
    new_event,
    utc_now,
)

from aiinvite.kernel.errors import (
    E_KN_BAD_PROPOSAL,
    E_KN_BAD_TARGET,
    E_KN_IO,
    E_KN_THIN_EVIDENCE,
    E_PROPOSER_FAILED,
    KernelError,
)
from aiinvite.kernel.kernel import STYLE_TARGETS, EvidenceEvent, Policy

CHAIN_PATH = "chain.json"
MANIFEST_PATH = "manifest.json"
EVIDENCE_DIR = "evidence"

MIN_EVIDENCE_EVENTS = 10
EVIDENCE_TYPES = ("turn", "feedback")
EVIDENCE_MAX_CHARS = 1200
DEFAULT_PROPOSER_TIMEOUT = 200
PROMPT_TEMPLATE = (
    "你在帮一个 AI 伙伴修订「{style|conduct}」。根据下面这段真实对话，"
    "写一条具体、可执行的要求。\n"
    "要求：\n"
    "- 不超过 40 个字\n"
    "- 不许用形容词堆砌（温柔、体贴、善解人意这类一律不许）\n"
    "- 要写成行为规则，能照着判断「做到了没有」\n"
    "- 只输出这一条，不要解释\n"
    "\n"
    "对话：\n"
    "{evidence}"
)


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


@dataclass(frozen=True)
class LiveProposal:
    """One proposal returned by an external proposer process.

    ``model`` / ``prompt_sha`` are mandatory; the four provenance fields are
    optional and follow the same integer-only rules as the event layer.
    """

    target: str
    text: str
    model: str
    prompt_sha: str
    quant: str | None = None
    weights_sha: str | None = None
    temp_milli: int | None = None
    seed: int | None = None


def prompt_sha_for(target: str) -> str:
    """Return ``sha256(prompt template + target)[:16]`` for one target."""
    payload = (PROMPT_TEMPLATE + target).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def evidence_summary(events: list[EvidenceEvent]) -> str:
    """Return a deterministic plain-text digest of turn/feedback evidence.

    Only the last ``EVIDENCE_MAX_CHARS`` characters are kept, so a long
    conversation still fits one subprocess request.
    """
    lines = [
        f"{event.event_id} {event.text}"
        for event in events
        if event.type in EVIDENCE_TYPES
    ]
    text = "\n".join(lines)
    return text[-EVIDENCE_MAX_CHARS:]


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


class SubprocessProposer:
    """Bridge to an external proposer process; the core never goes online.

    The contract is one JSON line in and one JSON line out. A crash, a
    malformed reply or a timeout is always ``E_PROPOSER_FAILED``.
    """

    def __init__(
        self, command: list[str], timeout: int = DEFAULT_PROPOSER_TIMEOUT
    ) -> None:
        if not command:
            raise KernelError(E_PROPOSER_FAILED, "外部提案器命令为空")
        self._command = list(command)
        self._timeout = timeout

    def propose(self, target: str, evidence: str, prompt_sha: str) -> LiveProposal:
        """Run the process once and return its validated proposal."""
        request = dumps({
            "evidence": evidence,
            "prompt_sha": prompt_sha,
            "target": target,
        })
        try:
            completed = subprocess.run(
                self._command,
                input=request,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise KernelError(
                E_PROPOSER_FAILED, f"外部提案器超时（{self._timeout}s）"
            ) from exc
        except OSError as exc:
            raise KernelError(
                E_PROPOSER_FAILED, f"外部提案器无法启动：{exc}"
            ) from exc
        lines = [
            line for line in completed.stdout.decode("utf-8", "replace").splitlines()
            if line
        ]
        if not lines:
            detail = completed.stderr.decode("utf-8", "replace").strip()
            raise KernelError(
                E_PROPOSER_FAILED,
                f"外部提案器没有输出：{detail or 'empty stdout'}",
            )
        payload = _load_reply(lines[-1], completed.stderr)
        return _live_from_payload(payload, target, prompt_sha)


def _load_reply(line: str, stderr: bytes) -> dict[str, object]:
    """Parse one reply line; a rejected reply becomes ``E_PROPOSER_FAILED``."""
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        detail = stderr.decode("utf-8", "replace").strip()
        raise KernelError(
            E_PROPOSER_FAILED, f"外部提案器输出不是 JSON：{detail or line}"
        ) from exc
    if not isinstance(data, dict):
        raise KernelError(E_PROPOSER_FAILED, "外部提案器输出不是对象")
    if data.get("ok") is not True:
        code = data.get("code", E_PROPOSER_FAILED)
        message = data.get("message", "外部提案器失败")
        hint = f"{code}: {message}" if isinstance(code, str) else str(message)
        raise KernelError(E_PROPOSER_FAILED, f"外部提案器失败：{hint}")
    return data


def _live_from_payload(
    payload: dict[str, object], target: str, prompt_sha: str
) -> LiveProposal:
    """Validate a successful reply line and build a :class:`LiveProposal`."""
    text = payload.get("text")
    model = payload.get("model")
    if not isinstance(text, str) or not 1 <= len(text) <= PROPOSAL_TEXT_MAX_CHARS:
        raise KernelError(E_PROPOSER_FAILED, "外部提案器 text 非法")
    if not isinstance(model, str) or not model or len(model) > MODEL_MAX_CHARS:
        raise KernelError(E_PROPOSER_FAILED, "外部提案器 model 非法")
    quant = _reply_text(payload, "quant", 32)
    weights = _reply_text(payload, "weights_sha", 64)
    if weights is not None and not WEIGHTS_SHA_RE.match(weights):
        raise KernelError(E_PROPOSER_FAILED, "外部提案器 weights_sha 非十六进制")
    return LiveProposal(
        target,
        text,
        model,
        prompt_sha,
        _reply_text(payload, "quant", 32),
        _reply_text(payload, "weights_sha", 64),
        _reply_int(payload, "temp_milli", 0, 2000),
        _reply_int(payload, "seed", 0, 2 ** 31 - 1),
    )


def _reply_text(payload: dict[str, object], name: str, limit: int) -> str | None:
    value = payload.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= limit:
        raise KernelError(E_PROPOSER_FAILED, f"外部提案器 {name} 非法")
    return value


def _reply_int(
    payload: dict[str, object], name: str, low: int, high: int
) -> int | None:
    value = payload.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise KernelError(E_PROPOSER_FAILED, f"外部提案器 {name} 非法")
    return value


def _require_evidence_volume(folder: Path) -> None:
    """Refuse a proposal when turn/feedback evidence is thinner than 10."""
    count = 0
    for path in sorted(folder.glob("seg-*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise KernelError(E_KN_IO, f"无法读取证据段：{path}") from exc
        for line in lines:
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise KernelError(E_KN_IO, f"证据行无法解析：{path}") from exc
            if isinstance(data, dict) and data.get("type") in EVIDENCE_TYPES:
                count += 1
        if count >= MIN_EVIDENCE_EVENTS:
            return
    raise KernelError(
        E_KN_THIN_EVIDENCE,
        f"可提案证据不足：需要 {MIN_EVIDENCE_EVENTS} 条 turn/feedback，"
        f"实际 {count} 条",
    )


def record_proposal(
    store: Path,
    target: str,
    text: str,
    model: str,
    prompt_sha: str,
    t: str | None = None,
    *,
    quant: str | None = None,
    weights_sha: str | None = None,
    temp_milli: int | None = None,
    seed: int | None = None,
) -> EvidenceEvent:
    """Append one ``proposal`` event to the evidence chain.

    The proposal is evidence like any other: it gets the next global event
    id, the chain ``prev`` hash and a segment position. ``capsule.py`` is
    frozen and its ``append_event`` cannot carry ``model`` / ``prompt_sha``,
    so this function maintains the same chain rules itself.

    A proposal needs at least ``MIN_EVIDENCE_EVENTS`` turn/feedback events;
    anything thinner is refused with ``E_KN_THIN_EVIDENCE`` before a byte is
    written. One round of "在吗 / 在" must never be able to define a persona.
    """
    if not store.is_dir() or not (store / EVIDENCE_DIR).is_dir():
        raise KernelError(E_KN_IO, f"存储目录未初始化：{store}")
    _check_proposal_input(target, text, model, prompt_sha)
    folder = store / EVIDENCE_DIR
    _require_evidence_volume(folder)
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
            quant=quant,
            weights_sha=weights_sha,
            temp_milli=temp_milli,
            seed=seed,
        )
    except AiInviteError as exc:
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
        event.quant, event.weights_sha, event.temp_milli, event.seed,
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
    text = event_text(data)
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


@dataclass(frozen=True)
class LiveIngest:
    """Outcome of one live proposal round.

    ``failed`` is operational noise: it is returned to the caller and logged,
    but never stored in META and never mixed into the kid.
    """

    recorded: tuple[EvidenceEvent, ...] = ()
    failed: int = 0
    errors: tuple[str, ...] = ()


def ingest_live(
    store: Path,
    command: list[str],
    timeout: int = DEFAULT_PROPOSER_TIMEOUT,
    strict: bool = False,
) -> LiveIngest:
    """Run the external proposer once per target and record its replies.

    By default a proposer failure (OOM, timeout, bad reply) is downgraded:
    the compile continues with whatever proposals were recorded and the
    caller must mark the kernel as a rule fallback. ``strict`` re-raises so
    CI can treat any proposer failure as fatal.
    """
    from aiinvite.kernel.compiler import read_evidence

    proposer = SubprocessProposer(command, timeout)
    summary = evidence_summary(read_evidence(store))
    recorded: list[EvidenceEvent] = []
    errors: list[str] = []
    failed = 0
    for target in STYLE_TARGETS:
        sha = prompt_sha_for(target)
        try:
            proposal = proposer.propose(target, summary, sha)
            event = record_proposal(
                store, target, proposal.text, proposal.model, sha,
                quant=proposal.quant, weights_sha=proposal.weights_sha,
                temp_milli=proposal.temp_milli, seed=proposal.seed,
            )
        except KernelError as exc:
            if exc.code != E_PROPOSER_FAILED or strict:
                raise
            failed += 1
            errors.append(f"{target}: {exc.code}: {exc.message}")
            continue
        recorded.append(event)
    return LiveIngest(tuple(recorded), failed, tuple(errors))
