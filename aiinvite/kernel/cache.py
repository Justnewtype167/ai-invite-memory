"""Segment-level evidence cache: parse each segment once per process.

A single-user companion runs one process per user, so the parsed evidence can
live in memory for the life of the process. Segments are append-only: an
append only grows the open file, so the cache remembers the byte offset it
has already parsed and reads just the new bytes. A changed prefix (truncated
segment, rewritten tail, same-size rewrite) is detected and that segment is
parsed again from zero.
"""
from __future__ import annotations

import json
import os
import pathlib

from aiinvite.kernel.compiler import _parse_event
from aiinvite.kernel.errors import E_KN_IO, KernelError

WINDOW = 4096


class EvidenceCache:
    """Keep parsed evidence between turns; re-parse only what changed."""

    def __init__(self) -> None:
        # name -> (bytes parsed, mtime_ns, events, tail event id)
        self._files: dict[str, tuple[int, int, tuple, str | None]] = {}
        self.parsed_segments = 0
        self.parsed_events = 0

    def read(self, store):
        """Return every event, ordered by numeric id, parsing only new bytes."""
        folder = pathlib.Path(store) / "evidence"
        if not folder.is_dir():
            raise KernelError(E_KN_IO, "缺少证据目录：" + str(folder))
        fresh = {}
        events = []
        last_sequence = None
        ordered = True
        # One directory listing carries size and mtime on Windows; calling
        # stat() per segment costs milliseconds per file under a scanner.
        for path, size, mtime in _scan(folder):
            entry = self._advance(path, size, mtime)
            fresh[path.name] = entry
            segment_events = entry[2]
            if not segment_events:
                continue
            first = _sequence(segment_events[0].event_id)
            if last_sequence is not None and first <= last_sequence:
                ordered = False
            last_sequence = _sequence(segment_events[-1].event_id)
            events.extend(segment_events)
        self._files = fresh
        if not events:
            raise KernelError(E_KN_IO, "证据目录为空：" + str(folder))
        if not ordered:
            events.sort(key=lambda event: _sequence(event.event_id))
        return events

    def _advance(self, path, size: int, mtime: int):
        """Return this segment entry, reusing the prefix when it still holds."""
        previous = self._files.get(path.name)
        if previous is not None:
            offset, seen_mtime, parsed, tail = previous
            if size == offset and mtime == seen_mtime:
                return previous
            if (
                size > offset
                and tail is not None
                and _tail_event_id(path, offset) == tail
            ):
                added, complete = _parse_from(path, offset)
                if added:
                    self.parsed_segments += 1
                    self.parsed_events += len(added)
                    merged = parsed + tuple(added)
                    return (complete, mtime, merged, merged[-1].event_id)
                if complete == offset:
                    # Only an unfinished trailing line: keep the old prefix.
                    return previous
        parsed, complete = _parse_from(path, 0)
        self.parsed_segments += 1
        self.parsed_events += len(parsed)
        tail = parsed[-1].event_id if parsed else None
        return (complete, mtime, tuple(parsed), tail)

    @staticmethod
    def _parse_segment(path):
        parsed, _ = _parse_from(path, 0)
        return parsed


def _scan(folder):
    """Return (path, size, mtime_ns) per segment, sorted by segment name."""
    rows = []
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                name = entry.name
                if not (name.startswith("seg-") and name.endswith(".jsonl")):
                    continue
                try:
                    stat = entry.stat()
                except OSError as exc:
                    raise KernelError(E_KN_IO, "无法读取证据段：" + entry.path) from exc
                rows.append((name, pathlib.Path(entry.path), stat.st_size,
                             stat.st_mtime_ns))
    except OSError as exc:
        raise KernelError(E_KN_IO, "无法读取证据目录：" + str(folder)) from exc
    rows.sort(key=lambda row: row[0])
    return [(path, size, mtime) for _name, path, size, mtime in rows]


def _parse_from(path, offset: int):
    """Parse complete lines at offset; ignore a trailing partial line."""
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read()
    except OSError as exc:
        raise KernelError(E_KN_IO, "无法读取证据段：" + str(path)) from exc
    cut = data.rfind(b"\n")
    if cut < 0:
        return [], offset
    body = data[: cut + 1]
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KernelError(E_KN_IO, "证据不是 UTF-8：" + str(path)) from exc
    parsed = [_parse_event(line, path) for line in text.split("\n") if line]
    return parsed, offset + len(body)


def _tail_event_id(path, offset: int) -> str | None:
    """Return the id of the complete line that ends at offset."""
    window = WINDOW
    while True:
        start = max(0, offset - window)
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                chunk = handle.read(offset - start)
        except OSError as exc:
            raise KernelError(E_KN_IO, "无法读取证据段：" + str(path)) from exc
        if not chunk.endswith(b"\n"):
            return None
        body = chunk[:-1]
        cut = body.rfind(b"\n")
        if cut < 0:
            if start > 0:
                window *= 4
                continue
            line = body
        else:
            line = body[cut + 1:]
        try:
            data = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        event_id = data.get("id")
        return event_id if isinstance(event_id, str) else None


def _sequence(event_id: str) -> int:
    return int(event_id.split("_")[1])
