"""Segment-level evidence cache: parse each segment once per process.

A single-user companion runs one process per user, so the parsed evidence can
live in memory for the life of the process. Segments are append-only, so
(size, mtime_ns) is a sufficient invalidation key: an append changes both,
and nothing else ever writes to a sealed segment.
"""
from __future__ import annotations

import pathlib

from aiinvite.kernel.compiler import _parse_event
from aiinvite.kernel.errors import E_KN_IO, KernelError
from aiinvite.kernel.kernel import EvidenceEvent


class EvidenceCache:
    """Keep parsed evidence between turns; re-parse only what changed."""

    def __init__(self) -> None:
        self._files = {}
        self.parsed_segments = 0

    def read(self, store):
        """Return every event, ordered by numeric id, parsing only new bytes."""
        folder = pathlib.Path(store) / "evidence"
        if not folder.is_dir():
            raise KernelError(E_KN_IO, "缺少证据目录：" + str(folder))
        paths = sorted(folder.glob("seg-*.jsonl"))
        fresh = {}
        events = []
        for path in paths:
            try:
                stat = path.stat()
            except OSError as exc:
                raise KernelError(E_KN_IO, "无法读取证据段：" + str(path)) from exc
            key = (stat.st_size, stat.st_mtime_ns)
            hit = self._files.get(path.name)
            if hit is not None and hit[0] == key[0] and hit[1] == key[1]:
                parsed = hit[2]
            else:
                parsed = tuple(self._parse_segment(path))
                self.parsed_segments += 1
            fresh[path.name] = (key[0], key[1], parsed)
            events.extend(parsed)
        self._files = fresh
        if not events:
            raise KernelError(E_KN_IO, "证据目录为空：" + str(folder))
        events.sort(key=lambda event: int(event.event_id.split("_")[1]))
        return events

    @staticmethod
    def _parse_segment(path):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise KernelError(E_KN_IO, "无法读取证据段：" + str(path)) from exc
        parsed = []
        for line in lines:
            if line:
                parsed.append(_parse_event(line, path))
        return parsed
