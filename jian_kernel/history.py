"""Kernel ledger: record, history, diff, restore and verify (M4)."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from jian.canonical import dumps

from jian_kernel.compiler import _compile_prefix, compile_kernel, read_evidence
from jian_kernel.errors import E_KN_IO, E_KN_NO_HISTORY, E_KN_STALE, KernelError
from jian_kernel.gate import PreviousState, check_gates, diff_canon
from jian_kernel.kernel import (
    HISTORY_FILE,
    KERNEL_DIR,
    META_FILE,
    ORIGIN_RULE_FALLBACK,
    ORIGIN_RULE_ONLY,
    ORIGINS,
    Delta,
    Diff,
    HistoryEntry,
    Kernel,
    Policy,
    kernel_kid,
    parse_canon,
    stamp_text,
)

STAGING_DIR = "kernel.staging"
STATE_KEYS = ("intimacy", "stability", "trust")
TAMPER_EVENT = "tamper_healed"


@dataclass(frozen=True)
class RecordResult:
    """Outcome of one ``record_kernel`` call.

    ``healed`` is true only when a ``--force`` record replaced a kernel
    directory that had been edited outside the evidence path.
    """

    version: int
    kid: str
    head: str
    delta: Delta
    written: bool
    healed: bool = False
    origin: str = ORIGIN_RULE_ONLY


@dataclass(frozen=True)
class VerifyReport:
    """Outcome of one ``verify_kernel`` call."""

    kid: str
    version: int
    head: str


def history(store: Path) -> list[HistoryEntry]:
    """Return every recorded version; raise when there is none."""
    path = store / KERNEL_DIR / HISTORY_FILE
    if not path.is_file():
        raise KernelError(E_KN_NO_HISTORY, f"尚无历史版本：{path}")
    entries = _read_history(path)
    if not entries:
        raise KernelError(E_KN_NO_HISTORY, f"历史文件为空：{path}")
    return entries


def _read_raw(path: Path) -> bytes:
    """Return the raw history bytes; a missing file is an empty ledger."""
    if not path.is_file():
        return b""
    try:
        return path.read_bytes()
    except OSError as exc:
        raise KernelError(E_KN_IO, f"无法读取历史：{path}") from exc


def _read_history(path: Path) -> list[HistoryEntry]:
    return _parse_entries(_read_raw(path), path)


def _parse_entries(raw: bytes, path: Path) -> list[HistoryEntry]:
    """Return the version lines; audit lines (``event``) are skipped."""
    entries: list[HistoryEntry] = []
    for line in raw.decode("utf-8").splitlines():
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise KernelError(E_KN_IO, f"历史行无法解析：{path}") from exc
        if isinstance(data, dict) and "event" in data:
            continue
        entries.append(_entry_from(data, path))
    return entries


def _entry_from(data: object, path: Path) -> HistoryEntry:
    if not isinstance(data, dict):
        raise KernelError(E_KN_IO, f"历史行不是对象：{path}")
    version = data.get("version")
    kid = data.get("kid")
    head = data.get("head")
    at = data.get("at")
    delta = data.get("delta")
    origin = data.get("origin", ORIGIN_RULE_ONLY)
    if isinstance(version, bool) or not isinstance(version, int):
        raise KernelError(E_KN_IO, f"历史 version 非法：{path}")
    for name, value in (("kid", kid), ("head", head), ("at", at)):
        if not isinstance(value, str):
            raise KernelError(E_KN_IO, f"历史 {name} 非法：{path}")
    if not isinstance(delta, dict):
        raise KernelError(E_KN_IO, f"历史 delta 非法：{path}")
    if not isinstance(origin, str) or origin not in ORIGINS:
        raise KernelError(E_KN_IO, f"历史 origin 非法：{path}")
    counts = [delta.get(name, 0) for name in ("added", "changed", "removed")]
    if not all(isinstance(item, int) and not isinstance(item, bool) for item in counts):
        raise KernelError(E_KN_IO, f"历史 delta 计数非法：{path}")
    return HistoryEntry(
        version=version,
        kid=str(kid),
        head=str(head),
        at=str(at),
        delta=Delta(int(counts[0]), int(counts[1]), int(counts[2])),
        origin=str(origin),
    )


def record_kernel(
    store: Path,
    policy: Policy | None = None,
    force: bool = False,
    allow_fallback: bool = False,
) -> RecordResult:
    """Compile, gate, and only then write one kernel version.

    Before compiling, the kernel currently on disk is hashed and compared
    with the latest history kid. A mismatch means ``kernel/`` was edited
    outside the evidence path: the record is refused with ``E_KN_STALE``
    unless ``force`` is set. A forced heal rewrites the kernel from evidence
    and appends one ``tamper_healed`` audit line to HISTORY.

    ``allow_fallback`` permits a rule-only kernel when the policy requires
    proposals but evidence has none; the resulting origin is
    ``rule_fallback`` and therefore its kid differs from every other origin.

    Nothing is written when a gate fails; the previous directory stays
    byte-identical.
    """
    chosen = policy if policy is not None else Policy()
    if allow_fallback:
        chosen = replace(chosen, allow_fallback=True)
    path = store / KERNEL_DIR / HISTORY_FILE
    raw = _read_raw(path)
    entries = _parse_entries(raw, path)
    disk_kid = _disk_kid(store) if entries else None
    healed = False
    if entries:
        latest = entries[-1]
        if disk_kid != latest.kid:
            if not force:
                raise KernelError(
                    E_KN_STALE,
                    f"内核被手改过（盘上 kid={disk_kid or '缺失'}，"
                    f"历史 kid={latest.kid}），确认请加 --force",
                )
            healed = True
    events = read_evidence(store)
    kernel = compile_kernel(store, chosen)
    moment = chosen.resolved_now(events[-1].stamp)
    at = stamp_text(moment)
    if entries and not healed:
        latest = entries[-1]
        previous = _read_previous(store, latest.head)
        check_gates(previous, kernel, events, chosen)
        version = latest.version
        if kernel.kid != latest.kid:
            version = latest.version + 1
            delta = diff_canon(previous.canon, kernel.canon).delta()
        else:
            delta = Delta(0, 0, 0)
    elif entries:
        latest = entries[-1]
        baseline = _compile_prefix(store, Policy(now=latest.at), latest.head).canon
        version = latest.version
        delta = Delta(0, 0, 0)
        if kernel.kid != latest.kid:
            version = latest.version + 1
            delta = diff_canon(baseline, kernel.canon).delta()
    else:
        check_gates(None, kernel, events, chosen)
        version = 1
        delta = Delta(len(kernel.canon), 0, 0)
    append = True if not entries else version > entries[-1].version
    line = HistoryEntry(
        version, kernel.kid, kernel.head, at, delta, kernel.origin
    ).to_line()
    tamper = (
        b""
        if not healed
        else _tamper_line(disk_kid, version, kernel.kid, kernel.head, at)
    )
    payloads = kernel.files(version)
    payloads[HISTORY_FILE] = raw + tamper + (line if append else b"")
    _write_kernel(store, payloads)
    return RecordResult(
        version, kernel.kid, kernel.head, delta, append, healed, kernel.origin
    )


def _disk_kid(store: Path) -> str | None:
    """Return the kid of the files under ``kernel/``; None means unreadable.

    Hashing the files themselves (not trusting ``META.json``) catches any
    edit of canon, self, state or graph, however small. ``origin`` is the one
    value read from META because it lives there by design.
    """
    folder = store / KERNEL_DIR
    try:
        self_md = (folder / "self.md").read_text(encoding="utf-8")
        canon_md = (folder / "canon.md").read_text(encoding="utf-8")
        state = json.loads((folder / "state.json").read_text(encoding="utf-8"))
        graph = json.loads((folder / "graph.json").read_text(encoding="utf-8"))
        meta = json.loads((folder / META_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict) or not isinstance(graph, dict):
        return None
    if not isinstance(meta, dict):
        return None
    origin = meta.get("origin")
    if not isinstance(origin, str) or origin not in ORIGINS:
        return None
    values: dict[str, int] = {}
    for name in STATE_KEYS:
        value = state.get(name)
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        values[name] = value
    return kernel_kid(self_md, canon_md, values, graph, origin)


def _tamper_line(
    found: str | None, version: int, kid: str, head: str, at: str
) -> bytes:
    """Return one append-only audit line for a forced heal."""
    payload = {
        "at": at,
        "event": TAMPER_EVENT,
        "found": found,
        "head": head,
        "kid": kid,
        "version": version,
    }
    return dumps(payload) + b"\n"


def _read_previous(store: Path, head: str) -> PreviousState:
    canon_path = store / KERNEL_DIR / "canon.md"
    state_path = store / KERNEL_DIR / "state.json"
    try:
        canon_text = canon_path.read_text(encoding="utf-8")
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise KernelError(E_KN_IO, f"无法读取上一版内核：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise KernelError(E_KN_IO, f"上一版 state 无法解析：{exc}") from exc
    if not isinstance(state, dict):
        raise KernelError(E_KN_IO, "上一版 state 不是对象")
    values: dict[str, int] = {}
    for name in STATE_KEYS:
        value = state.get(name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise KernelError(E_KN_IO, f"上一版 state.{name} 非法")
        values[name] = value
    return PreviousState(head, parse_canon(canon_text), values)


def _write_kernel(store: Path, payloads: dict[str, bytes]) -> None:
    staging = store / STAGING_DIR
    target = store / KERNEL_DIR
    try:
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        for name in sorted(payloads):
            (staging / name).write_bytes(payloads[name])
        target.mkdir(parents=True, exist_ok=True)
        for name in sorted(payloads):
            os.replace(staging / name, target / name)
    except OSError as exc:
        raise KernelError(E_KN_IO, f"写入内核失败：{exc}") from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging, True)


def restore(store: Path, version: int) -> Kernel:
    """Recompile the evidence prefix of ``version`` and assert its kid."""
    entries = history(store)
    entry = _find(entries, version)
    kernel = _compile_prefix(store, _policy_for(entry.origin, entry.at), entry.head)
    if kernel.kid != entry.kid:
        raise KernelError(
            E_KN_STALE,
            f"版本 {version} 重算 kid 不一致：{kernel.kid} != {entry.kid}",
        )
    return kernel


def _policy_for(origin: str, at: str) -> Policy:
    """Return the policy that reproduces a recorded origin."""
    if origin == ORIGIN_RULE_FALLBACK:
        return Policy(now=at, require_proposals=True, allow_fallback=True)
    return Policy(now=at)


def diff_versions(store: Path, a: int, b: int) -> Diff:
    """Return the entry-level difference between versions ``a`` and ``b``."""
    left = restore(store, a).canon
    right = restore(store, b).canon
    return diff_canon(left, right)


def verify_kernel(store: Path) -> VerifyReport:
    """Recompile the latest version and compare it with ``kernel/``."""
    meta = _read_meta(store)
    origin = meta.get("origin", ORIGIN_RULE_ONLY)
    if not isinstance(origin, str) or origin not in ORIGINS:
        raise KernelError(E_KN_STALE, "META origin 非法")
    entries = history(store)
    latest = entries[-1]
    kernel = compile_kernel(store, _policy_for(str(origin), latest.at))
    if kernel.kid != latest.kid:
        raise KernelError(E_KN_STALE, "重算 kid 与历史不一致")
    if meta["kid"] != kernel.kid or meta["version"] != latest.version:
        raise KernelError(E_KN_STALE, "META 与重算结果不一致")
    if meta["head"] != kernel.head:
        raise KernelError(E_KN_STALE, "META head 与证据 head 不一致")
    expected = kernel.files(latest.version)
    for name in sorted(expected):
        path = store / KERNEL_DIR / name
        try:
            actual = path.read_bytes()
        except OSError as exc:
            raise KernelError(E_KN_STALE, f"缺少内核文件：{name}") from exc
        if actual != expected[name]:
            raise KernelError(E_KN_STALE, f"内核文件与重算结果不一致：{name}")
    return VerifyReport(kernel.kid, latest.version, kernel.head)


def _read_meta(store: Path) -> dict[str, object]:
    path = store / KERNEL_DIR / META_FILE
    if not path.is_file():
        raise KernelError(E_KN_NO_HISTORY, f"尚未记录内核：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise KernelError(E_KN_IO, f"无法读取 META：{path}") from exc
    except json.JSONDecodeError as exc:
        raise KernelError(E_KN_IO, f"META 无法解析：{path}") from exc
    if not isinstance(data, dict):
        raise KernelError(E_KN_IO, f"META 不是对象：{path}")
    for name in ("kid", "version", "head"):
        if name not in data:
            raise KernelError(E_KN_IO, f"META 缺少 {name}")
    return data


def _find(entries: list[HistoryEntry], version: int) -> HistoryEntry:
    for entry in entries:
        if entry.version == version:
            return entry
    raise KernelError(E_KN_NO_HISTORY, f"没有版本 {version}")
