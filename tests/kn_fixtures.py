"""Shared fixtures for the M4 kernel tests (not a test module).

M1's frozen event schema only emits ``type=turn``, so typed evidence
(directive / milestone / feedback) is written here as a consistent hash
chain whose body additionally carries ``type`` and an optional ``kind``.
"""

from __future__ import annotations

import json
from pathlib import Path

from jian.canonical import dumps
from jian.event import GENESIS_PREV, compute_hash, format_id, normalize_time

Spec = tuple[str, str, str, str | None]


def write_store(root: Path, events: list[Spec]) -> None:
    """Write a fresh evidence chain in segments of 100 events."""
    folder = root / "evidence"
    folder.mkdir(parents=True, exist_ok=True)
    previous = GENESIS_PREV
    for start in range(0, len(events), 100):
        segment = f"seg-{start // 100 + 1:04d}"
        lines: list[bytes] = []
        for offset, spec in enumerate(events[start:start + 100]):
            sequence = start + offset + 1
            previous = _line(sequence, segment, spec, previous, lines)
        (folder / f"{segment}.jsonl").write_bytes(b"".join(lines))


def append_events(root: Path, events: list[Spec]) -> None:
    """Append typed events to an existing evidence chain."""
    folder = root / "evidence"
    files = sorted(folder.glob("seg-*.jsonl"))
    if not files:
        write_store(root, events)
        return
    last = files[-1]
    lines = [line for line in last.read_text(encoding="utf-8").splitlines() if line]
    previous = str(json.loads(lines[-1])["hash"])
    segment = int(last.stem.split("-")[1])
    used = len(lines)
    total = 0
    for path in files:
        total += len([line for line in path.read_text(encoding="utf-8").splitlines() if line])
    pending: dict[Path, list[bytes]] = {}
    for spec in events:
        if used >= 100:
            segment += 1
            used = 0
        total += 1
        used += 1
        path = folder / f"seg-{segment:04d}.jsonl"
        buffer: list[bytes] = pending.setdefault(path, [])
        previous = _line(total, f"seg-{segment:04d}", spec, previous, buffer)
    for path, buffer in pending.items():
        mode = "ab" if path.exists() else "wb"
        with path.open(mode) as handle:
            handle.write(b"".join(buffer))


def _line(
    sequence: int, segment: str, spec: Spec, previous: str, buffer: list[bytes]
) -> str:
    stamp, text, event_type, kind = spec
    body: dict[str, object] = {
        "ep": segment,
        "id": format_id(sequence),
        "prev": previous,
        "role": "user",
        "t": normalize_time(stamp),
        "text": text,
        "type": event_type,
        "v": 1,
    }
    if kind is not None:
        body["kind"] = kind
    digest = compute_hash(previous, body)
    body["hash"] = digest
    buffer.append(dumps(body) + b"\n")
    return digest


def snapshot(root: Path) -> dict[str, bytes]:
    """Return the bytes of every file under ``root/kernel``."""
    folder = root / "kernel"
    if not folder.is_dir():
        return {}
    return {path.name: path.read_bytes() for path in sorted(folder.iterdir()) if path.is_file()}


def directives(count: int, start: str = "2026-01-01T08:00:00Z") -> list[Spec]:
    """Return ``count`` lock directives one day apart."""
    result: list[Spec] = []
    for index in range(count):
        day = index + 1
        result.append(
            (f"2026-01-{day:02d}T08:00:00Z", f"规则{day}不许半夜打电话",
             "directive", "lock")
        )
    return result
